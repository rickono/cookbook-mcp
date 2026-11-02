"""Portable hosted service, background publication updates, and authenticated acknowledgement."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .library import Library
from .publication import Runtime
from .reports import ReportSink
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


def s3_store(endpoint_url, bucket, access_key_id, secret_access_key):
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=https_url(endpoint_url),
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=os.environ.get("AWS_DEFAULT_REGION", "auto"),
        config=Config(
            connect_timeout=5,
            read_timeout=20,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )
    return S3Store(client, bucket)


def store_from_environment():
    # Explicit credentials prevent accidental fallback to another AWS account/profile.
    names = (
        "S3_ENDPOINT_URL",
        "S3_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    )
    if any(not os.environ.get(name) for name in names):
        raise ValueError("storage configuration required")
    return s3_store(*(os.environ[name] for name in names))


REPORT_NAMES = (
    "REPORTS_S3_BUCKET",
    "REPORTS_AWS_ACCESS_KEY_ID",
    "REPORTS_AWS_SECRET_ACCESS_KEY",
)


def reports_store_from_environment():
    """The reports-only bucket and its own key, or None when reporting is not configured.

    It is never the library bucket or key: the library credential stays read-only.
    """
    present = [name for name in REPORT_NAMES if os.environ.get(name)]
    if not present:
        return None
    if len(present) != len(REPORT_NAMES):
        raise ValueError("incomplete reports storage configuration")
    if os.environ["REPORTS_S3_BUCKET"] == os.environ.get("S3_BUCKET") or os.environ[
        "REPORTS_AWS_ACCESS_KEY_ID"
    ] == os.environ.get("AWS_ACCESS_KEY_ID"):
        raise ValueError("reports storage must be separate from the library")
    return s3_store(
        os.environ.get("REPORTS_S3_ENDPOINT_URL") or os.environ["S3_ENDPOINT_URL"],
        *(os.environ[name] for name in REPORT_NAMES),
    )


READER_NAMES = (
    "READER_ORIGIN",
    "READER_CLIENT_ID",
    "READER_CLIENT_SECRET",
    "READER_SESSION_KEY",
    "READER_S3_BUCKET",
    "READER_AWS_ACCESS_KEY_ID",
    "READER_AWS_SECRET_ACCESS_KEY",
)


def reader_from_environment(verifier):
    """Opt-in hosted reader. Never borrow library or agent-report write authority."""
    from .reader import Reader, ReaderConfig

    if not any(name.startswith("READER_") for name in os.environ):
        return None
    if any(not os.environ.get(name) for name in READER_NAMES):
        raise ValueError("incomplete reader configuration")
    origin = os.environ["READER_ORIGIN"]
    audience = urlsplit(verifier.audience)
    if origin != f"{audience.scheme}://{audience.netloc}":
        raise ValueError("reader and MCP must share an exact origin")
    for bucket, credential in (
        ("S3_BUCKET", "AWS_ACCESS_KEY_ID"),
        ("REPORTS_S3_BUCKET", "REPORTS_AWS_ACCESS_KEY_ID"),
    ):
        if os.environ["READER_S3_BUCKET"] == os.environ.get(bucket) or os.environ[
            "READER_AWS_ACCESS_KEY_ID"
        ] == os.environ.get(credential):
            raise ValueError("reader session storage must be separate")
    oidc = os.environ.get("READER_OIDC", "0")
    if oidc not in ("0", "1"):
        raise ValueError("READER_OIDC must be 0 or 1")
    config = ReaderConfig(
        origin,
        os.environ["READER_CLIENT_ID"],
        os.environ["READER_CLIENT_SECRET"],
        oidc == "1",
    )
    store = s3_store(
        os.environ.get("READER_S3_ENDPOINT_URL") or os.environ["S3_ENDPOINT_URL"],
        os.environ["READER_S3_BUCKET"],
        os.environ["READER_AWS_ACCESS_KEY_ID"],
        os.environ["READER_AWS_SECRET_ACCESS_KEY"],
    )
    from .owner_report_config import owner_reports_from_environment

    return Reader(
        config,
        verifier,
        store,
        os.environ["READER_SESSION_KEY"].encode(),
        owner_reports=owner_reports_from_environment(s3_store),
    )


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
        except Exception:  # noqa: BLE001 - redacted service boundary
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


def create_hosted_app(
    runtime,
    verifier,
    *,
    poll_seconds=60,
    reports_store=None,
    reader=None,
    search_engine=None,
):
    if search_engine:
        runtime.prepare = search_engine.prepare
    reports = ReportSink(reports_store) if reports_store is not None else None
    app = create_app(
        Library(runtime, search_engine=search_engine), verifier, reports, reader=reader
    )
    original_lifespan = app.router.lifespan_context
    updater = PublicationUpdater(runtime, poll_seconds)

    @asynccontextmanager
    async def lifespan(app):
        if search_engine:
            await asyncio.to_thread(search_engine.start)
        try:
            await asyncio.to_thread(runtime.resume_cached)
        except Exception:  # noqa: BLE001 - redacted service boundary
            event("cached_publication_invalid")
        async with original_lifespan(app):
            updater.start()
            try:
                yield
            finally:
                await asyncio.to_thread(updater.close)
                if search_engine:
                    await asyncio.to_thread(search_engine.close)

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
    trusted_proxies = os.environ.get("COOKBOOK_TRUSTED_PROXY_IPS", "")
    if "*" in trusted_proxies:
        raise ValueError("trusted proxy IPs must be explicit")

    from .book_search import BookSearch

    search_engine = BookSearch(
        os.environ.get("COOKBOOK_TYPESENSE_BINARY", "/usr/local/bin/typesense-server"),
        runtime.root / "typesense",
    )
    uvicorn.run(
        create_hosted_app(
            runtime,
            verifier,
            reports_store=reports_store_from_environment(),
            reader=reader_from_environment(verifier),
            search_engine=search_engine,
        ),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        access_log=False,
        log_level="critical",
        proxy_headers=bool(trusted_proxies),
        forwarded_allow_ips=trusted_proxies,
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
