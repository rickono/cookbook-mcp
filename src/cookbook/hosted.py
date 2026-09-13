"""Portable hosted service, background publication updates, and authenticated acknowledgement."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import httpx

from .library import Library
from .publication import Runtime
from .server import JWTVerifier, create_app
from .storage import S3Store
from .telemetry import event


def https_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("HTTPS configuration required")
    return value


def store_from_environment():
    import boto3
    from botocore.config import Config

    # Explicit credentials prevent accidental fallback to another AWS account/profile.
    names = (
        "S3_ENDPOINT_URL",
        "S3_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    )
    if any(not os.environ.get(name) for name in names):
        raise ValueError("storage configuration required")
    client = boto3.client(
        "s3",
        endpoint_url=https_url(os.environ["S3_ENDPOINT_URL"]),
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_DEFAULT_REGION", "auto"),
        config=Config(
            connect_timeout=5,
            read_timeout=20,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )
    return S3Store(client, os.environ["S3_BUCKET"])


class PublicationUpdater:
    def __init__(self, runtime, interval=60):
        self.runtime = runtime
        self.interval = interval
        self.stop = threading.Event()
        self.thread = None
        self.last_status = None

    def tick(self):
        try:
            raw, _ = self.runtime.store.read_version("control/active.json")
            if raw is None:
                status = "publication_waiting"
            else:
                pointer = json.loads(raw)
                if pointer != self.runtime.active():
                    self.runtime.activate(pointer)
                    status = "publication_activated"
                else:
                    status = "publication_current"
        except Exception:
            # Activation stages separately, so failures leave the old pointer intact.
            status = "publication_update_failed"
        if status != self.last_status:
            event(status)
            self.last_status = status
        return status

    def run(self):
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(self.interval)

    def start(self):
        self.thread = threading.Thread(
            target=self.run, daemon=True, name="publication-updater"
        )
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)


def create_hosted_app(runtime, verifier, *, poll_seconds=60):
    app = create_app(Library(runtime), verifier)
    original_lifespan = app.router.lifespan_context
    updater = PublicationUpdater(runtime, poll_seconds)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await asyncio.to_thread(runtime.resume_cached)
        except Exception:
            event("cached_publication_invalid")
        async with original_lifespan(app):
            updater.start()
            try:
                yield
            finally:
                await asyncio.to_thread(updater.close)

    app.router.lifespan_context = lifespan
    return app


def serve():
    import logging
    import uvicorn

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    runtime = Runtime(
        store_from_environment(), Path(os.environ["COOKBOOK_RUNTIME"]).resolve()
    )
    verifier = JWTVerifier(
        issuer=https_url(os.environ["COOKBOOK_ISSUER"]),
        audience=https_url(os.environ["COOKBOOK_AUDIENCE"]),
        subjects=[os.environ["COOKBOOK_ALLOWED_SUBJECT"]]
        if os.environ.get("COOKBOOK_ALLOWED_SUBJECT")
        else [],
        jwks_url=https_url(os.environ["COOKBOOK_JWKS_URL"]),
    )
    uvicorn.run(
        create_hosted_app(runtime, verifier),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        access_log=False,
        log_level="critical",
        proxy_headers=False,
        timeout_graceful_shutdown=10,
    )


def wait_for_activation(
    pointer,
    readiness_url,
    token_provider,
    *,
    timeout=300,
    interval=5,
    client=None,
    clock=time.monotonic,
    sleep=asyncio.sleep,
):
    """Bound total acknowledgement time, including slow connections and response bodies."""
    return asyncio.run(
        _wait_for_activation(
            pointer,
            readiness_url,
            token_provider,
            timeout=timeout,
            interval=interval,
            client=client,
            clock=clock,
            sleep=sleep,
        )
    )


async def _wait_for_activation(
    pointer, readiness_url, token_provider, *, timeout, interval, client, clock, sleep
):
    https_url(readiness_url)
    deadline = clock() + timeout
    owned = client is None
    client = client or httpx.AsyncClient(follow_redirects=False, trust_env=False)
    try:
        async with asyncio.timeout(timeout):
            while clock() < deadline:
                try:
                    token = token_provider()
                    remaining = deadline - clock()
                    if remaining <= 0:
                        break
                    async with asyncio.timeout(min(10, remaining)):
                        response = await client.get(
                            readiness_url,
                            headers={"Authorization": "Bearer " + token},
                            timeout=min(10, remaining),
                            follow_redirects=False,
                        )
                    if response.status_code == 200:
                        data = response.json()
                        if (
                            isinstance(data, dict)
                            and data.get("status") == "ready"
                            and all(
                                data.get(k) == pointer[k]
                                for k in ("publication_id", "manifest_sha256")
                            )
                        ):
                            return pointer["publication_id"]
                except (httpx.HTTPError, ValueError, OSError, TimeoutError):
                    pass
                remaining = deadline - clock()
                if remaining > 0:
                    await sleep(min(interval, remaining))
    except TimeoutError:
        pass
    finally:
        if owned:
            await client.aclose()
    return None
