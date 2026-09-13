"""Public-client browser PKCE login; bearer credentials remain in process memory."""

import asyncio
import base64
import hashlib
import os
import secrets
import time
import webbrowser
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .hosted import https_url
from .server import JWTVerifier

CALLBACK = "http://127.0.0.1:8766/callback"


class LoginError(ValueError):
    """Fixed error codes only: never include provider responses or credentials."""


@dataclass(frozen=True)
class LoginConfig:
    issuer: str
    audience: str
    client_id: str
    subject: str
    jwks_url: str

    def __post_init__(self):
        for url in (self.issuer, self.audience, self.jwks_url):
            https_url(url)
        issuer = urlsplit(self.issuer)
        if (
            issuer.path != "/"
            or urlsplit(self.jwks_url).netloc != issuer.netloc
            or not self.client_id
            or not self.subject
        ):
            raise LoginError("invalid_login_configuration")

    @classmethod
    def from_environment(cls):
        return cls(
            issuer=os.environ["COOKBOOK_ISSUER"],
            audience=os.environ["COOKBOOK_AUDIENCE"],
            client_id=os.environ["COOKBOOK_PUBLISHER_CLIENT_ID"],
            subject=os.environ["COOKBOOK_ALLOWED_SUBJECT"],
            jwks_url=os.environ["COOKBOOK_JWKS_URL"],
        )


@dataclass(frozen=True)
class LoginToken:
    value: str = field(repr=False)
    expires_at: int

    def bearer(self):
        if self.expires_at <= time.time():
            raise LoginError("login_expired")
        return self.value


def browser_login(config, *, timeout=600):
    return asyncio.run(_browser_login(config, timeout=timeout))


async def _browser_login(
    config, *, timeout=600, open_browser=None, client=None, verifier=None
):
    """Bind before opening the browser, accept one correlated code, then verify JWT."""
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    authorization_url = (
        config.issuer
        + "authorize?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "audience": config.audience,
                "redirect_uri": CALLBACK,
                "scope": "library:read",
                "connection": "google-oauth2",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )
    result = asyncio.get_running_loop().create_future()
    handlers = set()

    async def callback(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        status, message = 400, "Invalid sign-in callback."
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            lines = raw.decode("ascii").split("\r\n")
            method, target, version = lines[0].split(" ")
            headers = [line.split(":", 1) for line in lines[1:] if line]
            hosts = [v.strip() for k, v in headers if k.lower() == "host"]
            url = urlsplit(target)
            params = parse_qs(url.query, keep_blank_values=True, max_num_fields=12)
            valid = (
                method == "GET"
                and version in ("HTTP/1.0", "HTTP/1.1")
                and hosts == ["127.0.0.1:8766"]
                and not url.scheme
                and not url.netloc
                and not url.fragment
                and url.path == "/callback"
                and all(len(v) == 1 for v in params.values())
                and secrets.compare_digest(params.get("state", [""])[0], state)
                and params.get("iss") == [config.issuer]
                and not result.done()
            )
            if valid:
                if params.get("error"):
                    result.set_exception(LoginError("login_denied"))
                    message = "Sign-in was not completed. Return to the publisher."
                elif params.get("code", [""])[0] and "error" not in params:
                    result.set_result(params["code"][0])
                    status = 200
                    message = (
                        "Sign-in received. Return to the publisher for verification."
                    )
            body = message.encode("utf-8")
            writer.write(
                f"HTTP/1.1 {status} {'OK' if status == 200 else 'Bad Request'}\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n"
                "Cache-Control: no-store\r\n"
                "Referrer-Policy: no-referrer\r\n"
                "Content-Security-Policy: default-src 'none'; frame-ancestors 'none'\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except (
            ValueError,
            TypeError,
            UnicodeError,
            OSError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass
        finally:
            writer.close()
            handlers.discard(task)

    try:
        listener = await asyncio.start_server(
            callback, "127.0.0.1", 8766, limit=16384, reuse_address=True
        )
    except OSError:
        raise LoginError("login_callback_port_unavailable") from None
    try:
        async with listener, asyncio.timeout(timeout):
            opened = await asyncio.to_thread(
                open_browser or webbrowser.open, authorization_url
            )
            if not opened:
                raise LoginError("login_browser_unavailable")
            code = await result
    except TimeoutError:
        raise LoginError("login_timeout") from None
    finally:
        for task in tuple(handlers):
            task.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)

    owned = client is None
    client = client or httpx.AsyncClient(follow_redirects=False, trust_env=False)
    try:
        async with asyncio.timeout(15):
            response = await client.post(
                config.issuer + "oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": config.client_id,
                    "code": code,
                    "code_verifier": code_verifier,
                    "redirect_uri": CALLBACK,
                },
                timeout=15,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise LoginError("login_token_exchange_failed")
            payload = response.json()
            if (
                not isinstance(payload, dict)
                or payload.get("token_type", "").lower() != "bearer"
                or not isinstance(payload.get("access_token"), str)
                or "refresh_token" in payload
            ):
                raise LoginError("login_token_invalid")
            verifier = verifier or JWTVerifier(
                issuer=config.issuer,
                audience=config.audience,
                subjects=[config.subject],
                jwks_url=config.jwks_url,
            )
            verified = await verifier.verify_token(payload["access_token"])
            if (
                verified is None
                or verified.client_id != config.client_id
                or set(verified.scopes) != {"library:read"}
                or not verified.expires_at
            ):
                raise LoginError("login_token_invalid")
            return LoginToken(payload["access_token"], verified.expires_at)
    except LoginError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, TimeoutError):
        raise LoginError("login_token_exchange_failed") from None
    finally:
        if owned:
            await client.aclose()
