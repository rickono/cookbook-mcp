"""Hosted browser session boundary. Library access remains shared and read-only."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
import zipfile
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import jwt
from cryptography.fernet import Fernet
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import reader_diagnostics as diagnostics
from .reader_content import decode_location, deliver, reading_link
from .reader_diagnostics import Stage, stage
from .reader_sessions import (
    LIFETIME,
    Access,
    LogoutScope,
    ProviderTokens,
    SessionBook,
    SessionLimit,
    SignIn,
)
from .storage import canonical

VENDOR_ROOT = Path(__file__).with_name("book_vendor").resolve()
VENDOR_ASSETS = frozenset(json.loads((VENDOR_ROOT / "assets.json").read_text()))

COOKIE = "__Host-reader"
TRANSACTION = "__Host-reader-login"
DEADLINE = 10.0
IMAGE_DEADLINE = 30.0
PASSIVE_PATHS = frozenset({"/reader/session", "/reader/updates", "/reader/logout"})

# Public generic first-party assets; protected routes are registered separately.
ASSETS = {
    "/reader/presentation.css": ("reader_presentation.css", "text/css"),
    "/reader/presentation.js": ("reader_presentation.js", "text/javascript"),
    "/reader/epub.js": ("reader_epub.mjs", "text/javascript"),
    "/reader/book.js": ("reader_book.js", "text/javascript"),
    "/reader/book.css": ("reader_book.css", "text/css"),
    "/reader/style.css": ("reader_style.css", "text/css"),
    "/reader/personal.js": ("reader_personal.js", "text/javascript"),
    "/reader/search.js": ("reader_search.js", "text/javascript"),
    "/reader/original.js": ("reader_original.js", "text/javascript"),
    "/reader/original.css": ("reader_original.css", "text/css"),
    "/reader/reports.js": ("owner_reports.js", "text/javascript"),
    "/reader/content.js": ("reader_content.js", "text/javascript"),
    "/reader/updates.js": ("reader_updates.js", "text/javascript"),
    "/reader/session.js": ("reader_session.js", "text/javascript"),
}


def opaque():
    return secrets.token_urlsafe(32)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class ReaderConfig:
    origin: str
    client_id: str
    client_secret: str = field(repr=False)
    oidc: bool = False

    def __post_init__(self):
        p = urlsplit(self.origin)
        if (
            p.scheme != "https"
            or not p.hostname
            or p.username
            or p.password
            or p.path
            or p.query
            or p.fragment
        ):
            raise ValueError("reader requires an exact HTTPS origin")
        if not self.client_id or not self.client_secret:
            raise ValueError("confidential reader client required")

    @property
    def callback(self):
        return self.origin + "/reader/callback"


class IdentityProvider:
    """Auth0 confidential web client; no discovery-controlled redirect endpoints."""

    def __init__(self, config, verifier):
        self.config, self.verifier = config, verifier

    async def post(self, path, data):
        async with httpx.AsyncClient(
            timeout=5, follow_redirects=False, trust_env=False
        ) as client:
            r = await client.post(
                self.verifier.issuer + path,
                data={
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    **data,
                },
            )
            r.raise_for_status()
            return r.json() if path == "oauth/token" else None

    async def exchange(self, code, verifier, nonce):
        tokens = await self.post(
            "oauth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": self.config.callback,
            },
        )
        if self.config.oidc:
            raw = tokens.get("id_token", "")
            key = (
                self.verifier.public_key
                or (
                    await asyncio.to_thread(
                        self.verifier.jwks.get_signing_key_from_jwt, raw
                    )
                ).key
            )
            claims = jwt.decode(
                raw,
                key,
                algorithms=["RS256"],
                issuer=self.verifier.issuer,
                audience=self.config.client_id,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
            )
            access = await self.verifier.verify_token(tokens.get("access_token", ""))
            if (
                claims["nonce"] != nonce
                or not access
                or claims["sub"] != access.subject
            ):
                raise ValueError("identity mismatch")
            if claims.get("azp", self.config.client_id) != self.config.client_id:
                raise ValueError("identity client mismatch")
            if (
                isinstance(claims["aud"], list)
                and len(claims["aud"]) > 1
                and claims.get("azp") != self.config.client_id
            ):
                raise ValueError("identity client mismatch")
        return tokens

    async def renew(self, token):
        return await self.post(
            "oauth/token", {"grant_type": "refresh_token", "refresh_token": token}
        )

    async def revoke(self, token):
        await self.post("oauth/revoke", {"token": token})


class Reader:
    def __init__(
        self,
        config,
        verifier,
        store,
        encryption_key,
        *,
        identity=None,
        clock=time.time,
        owner_reports=None,
        personal_state=None,
        session_database=None,
    ):
        if urlsplit(verifier.issuer).scheme != "https" or not verifier.issuer.endswith(
            "/"
        ):
            raise ValueError("exact HTTPS issuer ending in slash required")
        self.config, self.verifier, self.store = config, verifier, store
        self.cipher = Fernet(encryption_key)
        self.identity = identity or IdentityProvider(config, verifier)
        self.clock = clock
        self.owner_reports = owner_reports
        self.personal_state = personal_state
        if session_database is None:
            self.sessions = SessionBook(
                store, self.cipher, verifier, self.identity, clock
            )
        else:
            from .reader_sessions_postgres import PostgresSessionBook

            self.sessions = PostgresSessionBook(
                session_database,
                self.cipher,
                verifier,
                self.identity,
                encryption_key,
                clock=None if clock is time.time else clock,
            )

    async def start(self):
        if start := getattr(self.sessions, "start", None):
            await start()

    async def close(self):
        if close := getattr(self.sessions, "close", None):
            await close()

    async def read(self, key):
        with stage(Stage.CALLBACK_TRANSACTION) as span:
            span.attempt()
            raw, version = await asyncio.to_thread(self.store.read_version, key)
            return (json.loads(self.cipher.decrypt(raw)) if raw else None), version

    async def write(self, key, value, version=None):
        with stage(
            Stage.CALLBACK_TRANSACTION if version is not None else Stage.LOGIN_START
        ) as span:
            span.attempt()
            return await asyncio.to_thread(
                self.store.put_bytes,
                key,
                self.cipher.encrypt(canonical(value)),
                expected=version,
            )

    def cookie(self, response, name, value, age):
        response.set_cookie(
            name,
            value,
            max_age=age,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )

    def page(self, body, *, protected=False, presentation=False):
        return HTMLResponse(
            '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cookbook library</title><link rel="stylesheet" href="/reader/style.css">'
            + ('<script src="/reader/session.js" defer></script>' if protected else "")
            + (
                '<link rel="stylesheet" href="/reader/presentation.css"><script src="/reader/presentation.js" defer></script>'
                if presentation
                else ""
            )
            + '<body><a class="skip-link" href="#reader-main">Skip to reading</a>'
            '<header class="site-header"><div class="site-header-inner">'
            '<a class="brand" href="/reader/catalog"><span class="brand-mark" aria-hidden="true"></span>Cookbook library</a>'
            '<nav class="site-nav" aria-label="Library navigation"><a href="/reader/catalog">Library</a>'
            '<a href="/reader/search">Search library</a><a href="/reader/bookmarks">Bookmarks</a></nav>'
            '</div></header><main id="reader-main" tabindex="-1">'
            + body
            + "</main></body></html>"
        )

    def expired(self, destination=None):
        r = self.page(
            '<section class="layout layout-narrow signin"><p class="kicker">Your books, close at hand</p>'
            "<h1>A little time with your cookbooks.</h1>"
            '<p class="lede" role="status">Sign in to read your private library.</p><a class="button button-primary" href="/reader/login?'
            + escape(urlencode({"return": destination or "catalog"}))
            + '">Sign in</a><p class="fineprint">Browse the books you know, find something to cook, and pick up where you left off.</p></section>'
        )
        r.status_code = 401
        self.cookie(r, COOKIE, "", 0)
        return r

    async def dispatch(self, request, library, trace):
        path = request.url.path
        if path.startswith("/reader/vendor/"):
            import mimetypes

            name = path.removeprefix("/reader/vendor/")
            if name not in VENDOR_ASSETS:
                return Response(status_code=404)
            with zipfile.ZipFile(VENDOR_ROOT / "assets.zip") as archive:
                binary = archive.read(name)
            mime = (
                {
                    ".mjs": "text/javascript",
                    ".js": "text/javascript",
                    ".css": "text/css",
                    ".wasm": "application/wasm",
                }.get(Path(name).suffix)
                or mimetypes.guess_type(name)[0]
                or "application/octet-stream"
            )
            return Response(binary, media_type=mime)
        if path in ASSETS:
            filename, media_type = ASSETS[path]
            return Response(
                Path(__file__).with_name(filename).read_text(), media_type=media_type
            )
        if path == "/reader/login":
            # Only named, opaque destinations; never accept a URL supplied by a client.
            destination = request.query_params.get("return", "catalog")
            if destination != "catalog":
                try:
                    decode_location(destination)
                except (ValueError, TypeError, UnicodeError):
                    return JSONResponse(
                        {"error": "invalid_destination"}, status_code=400
                    )
            state, browser, pkce, nonce = opaque(), opaque(), opaque(), opaque()
            await self.write(
                "reader/transactions/" + digest(state),
                {
                    "browser": digest(browser),
                    "destination": destination,
                    "pkce": pkce,
                    "nonce": nonce,
                    "expires": self.clock() + 600,
                },
            )
            query = {
                "response_type": "code",
                "client_id": self.config.client_id,
                "redirect_uri": self.config.callback,
                "audience": self.verifier.audience,
                "scope": "library:read offline_access"
                + (" openid" if self.config.oidc else ""),
                "state": state,
                "code_challenge": base64.urlsafe_b64encode(
                    hashlib.sha256(pkce.encode()).digest()
                )
                .rstrip(b"=")
                .decode(),
                "code_challenge_method": "S256",
            }
            if self.config.oidc:
                query["nonce"] = nonce
            r = RedirectResponse(
                self.verifier.issuer + "authorize?" + urlencode(query), status_code=303
            )
            self.cookie(r, TRANSACTION, browser, 600)
            return r
        if path == "/reader/callback":
            q = request.query_params
            if (
                any(len(q.getlist(k)) != 1 for k in ("state", "code", "iss"))
                or len(q["state"]) != 43
                or not q["code"]
                or "error" in q
            ):
                return self.expired()
            key = "reader/transactions/" + digest(q["state"])
            txn, version = await self.read(key)
            if (
                not txn
                or txn.get("expires", 0) <= self.clock()
                or txn.get("browser") != digest(request.cookies.get(TRANSACTION, ""))
                or q["iss"] != self.verifier.issuer
            ):
                return self.expired()
            await self.write(
                key, {}, version
            )  # Consume before exchange; replay fails across workers.
            try:
                with stage(Stage.PROVIDER_EXCHANGE) as span:
                    span.attempt()
                    tokens = await self.identity.exchange(
                        q["code"], txn["pkce"], txn["nonce"]
                    )
                with stage(Stage.TOKEN_VERIFY) as span:
                    span.attempt()
                    token = await self.verifier.verify_token(
                        ProviderTokens.parse(tokens).access
                    )
                if not token or "library:read" not in token.scopes:
                    raise ValueError("unauthorized")
            except Exception:  # noqa: BLE001 - callback failure must leave the protocol URL
                return self.expired()
            created = await self.sessions.begin(token, ProviderTokens.parse(tokens))
            if isinstance(created, SessionLimit):
                return JSONResponse({"error": "session_limit"}, status_code=409)
            destination = txn.get("destination", "catalog")
            if destination != "catalog":
                decode_location(destination)
            r = RedirectResponse(
                "/reader/catalog"
                if destination == "catalog"
                else "/reader/book-view?" + urlencode({"at": destination}),
                status_code=303,
            )
            self.cookie(r, COOKIE, created.cookie, LIFETIME)
            self.cookie(r, TRANSACTION, "", 0)
            return r
        if path == "/reader/signed-out":
            provider = (
                self.verifier.issuer
                + "v2/logout?"
                + urlencode(
                    {
                        "client_id": self.config.client_id,
                        "returnTo": self.config.origin + "/reader",
                    }
                )
            )
            response = self.page(
                '<p role="status">Reader signed out on this device. Refresh-token revocation was attempted. '
                "If the provider is unavailable, reader logout still stands; provider SSO may remain active.</p>"
                '<a href="' + escape(provider) + '">Continue to Auth0 SSO sign-out</a>'
                "<p>This does not sign out Google or MCP, immediately revoke a copied valid access token, "
                'or erase content already delivered.</p><a href="/reader/login">Sign in again</a>'
            )
            response.headers["Clear-Site-Data"] = '"cache", "storage"'
            return response
        if path == "/reader/signin-failed":
            return self.expired()
        auth = await self.sessions.authorize(
            request.cookies.get(COOKIE),
            Access.PASSIVE if path in PASSIVE_PATHS else Access.ACTIVE,
        )
        if isinstance(auth, SignIn):
            trace.signed_out(auth.reason)
            destination = (
                request.query_params.get("at")
                if path
                in (
                    "/reader/read",
                    "/reader/book-view",
                    "/reader/book-info",
                    "/reader/source",
                    "/reader/content",
                    "/reader/updates",
                    "/reader/original",
                    "/reader/image",
                )
                else None
            )
            if destination:
                try:
                    decode_location(destination)
                except (ValueError, TypeError, UnicodeError):
                    destination = None
            return self.expired(destination)
        session = auth
        subject = auth.subject
        if path == "/reader/personal":
            from .reader_personal import endpoint

            with stage(Stage.PERSONAL_STATE):
                return await endpoint(self, request, library, subject, session)
        if path == "/reader/bookmarks":
            from .reader_personal import bookmarks_page

            return bookmarks_page(self)
        if path == "/reader/book":
            from .reader_personal import book_entry

            with stage(Stage.PERSONAL_STATE):
                return await book_entry(self, request, library, subject, session.csrf)
        if path == "/reader/search":
            from .reader_search import page

            if set(request.query_params) - {"at"}:
                return JSONResponse({"error": "use_private_post_body"}, status_code=400)
            try:
                location = (
                    decode_location(request.query_params["at"])
                    if "at" in request.query_params
                    else {}
                )
            except (ValueError, TypeError, UnicodeError):
                return JSONResponse({"error": "invalid_destination"}, status_code=400)
            return page(self, location.get("book_id", ""), csrf=session.csrf)
        if path == "/reader/search/results":
            from .reader_search import results

            with stage(Stage.LIBRARY_SEARCH):
                return await results(request, library, self, session)
        if path == "/reader/source":
            from .reader_book import source

            with stage(Stage.ORIGINAL_DELIVER):
                return await source(request, library)
        if path in ("/reader/book-view", "/reader/book-info"):
            from .reader_book import deliver as book_view

            with stage(Stage.CONTENT_DELIVER):
                return await book_view(self, request, library, subject, session.csrf)
        if path in ("/reader/original", "/reader/image"):
            from .reader_original import deliver as original

            with stage(Stage.ORIGINAL_DELIVER):
                return await original(self, request, library)
        if path in ("/reader/read", "/reader/content", "/reader/updates"):
            with stage(Stage.CONTENT_DELIVER):
                return await deliver(self, request, library, subject, session.csrf)
        if path == "/reader/reports":
            from .owner_reports import intake

            with stage(Stage.REPORT_INTAKE):
                return await intake(self, request, subject, session)
        if path == "/reader/session":
            return JSONResponse({"authenticated": True, "csrf": session.csrf})
        if path == "/reader/logout":
            if request.headers.get("origin") != self.config.origin:
                return JSONResponse({"error": "origin_denied"}, status_code=403)
            if int(request.headers.get("content-length", "0")) > 4096:
                return Response(status_code=413)
            payload = bytearray()
            async for chunk in request.stream():
                payload.extend(chunk)
                if len(payload) > 4096:
                    return Response(status_code=413)
            scripted = (
                request.headers.get("content-type", "").split(";", 1)[0]
                == "application/json"
            )
            try:
                data = (
                    json.loads(payload)
                    if scripted
                    else dict(parse_qsl(payload.decode()))
                )
            except (ValueError, UnicodeError):
                return JSONResponse({"error": "invalid_logout"}, status_code=400)
            if not isinstance(data, dict):
                return JSONResponse({"error": "invalid_logout"}, status_code=400)
            csrf = data.get("csrf", "")
            if (
                not isinstance(csrf, str)
                or not csrf.isascii()
                or not secrets.compare_digest(csrf, session.csrf)
                or data.get("scope") not in ("device", "all")
            ):
                return JSONResponse({"error": "csrf_or_scope_denied"}, status_code=403)
            await self.sessions.end(session, LogoutScope(data["scope"]))
            r = self.page(
                '<p role="status">Reader signed out. Google, MCP and copied access tokens may remain signed in.</p><a href="/reader/login">Sign in again</a>'
            )
            if scripted:
                r = JSONResponse({"status": "signed_out", "scope": data["scope"]})
            elif data["scope"] == "device":
                r = RedirectResponse("/reader/signed-out", status_code=303)
            self.cookie(r, COOKIE, "", 0)
            if not scripted:
                r.headers["Clear-Site-Data"] = '"cache", "storage"'
            return r
        if path in ("/reader", "/reader/catalog"):
            q = request.query_params
            with stage(Stage.LIBRARY_SEARCH):
                result = await asyncio.to_thread(
                    library.search,
                    "",
                    mode="catalog",
                    publication_id=q.get("publication"),
                    offset=int(q.get("offset", "0")),
                    limit=20,
                )
            rows = []
            for item in result["results"]:
                c = item["citation"]
                rows.append(
                    '<li class="book"><a href="'
                    + escape(reading_link(c).replace("/reader/read?", "/reader/book?"))
                    + '" class="book-link"><span class="book-spine" aria-hidden="true">'
                    + escape(c["title"][0:1])
                    + '</span><span class="book-body"><strong class="book-title">'
                    + escape(c["title"])
                    + '</strong><span class="book-byline">'
                    + escape(", ".join(c["authors"]))
                    + '</span><span class="book-format">'
                    + escape(c["format"])
                    + '</span><span class="book-open">Open book <span aria-hidden="true">→</span></span></span></a></li>'
                )
            body = (
                '<header class="page-head catalog-head"><div><p class="kicker">Your collection</p><h1>Your cookbook library.</h1>'
                '<p class="lede">The books you return to. The recipes still to discover.</p></div>'
                '<a class="search-entry" href="/reader/search">Search library</a></header>'
                '<h2 class="section-label">Published books</h2><ul class="book-list">'
                + "".join(rows)
                + '</ul><details class="account"><summary>Your account</summary>'
                '<form method="post" action="/reader/logout"><input type="hidden" name="csrf" value="'
                + escape(session.csrf)
                + '"><button name="scope" value="device">Sign out this device</button><button name="scope" value="all">Sign out all reader devices</button></form>'
                '<p class="fineprint">Logout ends reader access. It does not sign out Google or MCP, revoke copied valid tokens immediately, or erase content already delivered.</p></details>'
            )
            if result.get("next_offset") is not None:
                body += (
                    '<a href="/reader/catalog?'
                    + escape(
                        urlencode(
                            {
                                "publication": result["publication_id"],
                                "offset": result["next_offset"],
                            }
                        )
                    )
                    + '">More books</a>'
                )
            return self.page(body, protected=True)
        return Response(status_code=404)

    def failure(self, request, failure):
        code = failure.category.value
        message = "Reader unavailable. Retry or sign in again."
        if request.url.path in ("/reader/original", "/reader/image"):
            from .reader_original import failure as original_failure
            from .reader_original import link

            at = request.query_params.get("at", "")
            try:
                decode_location(at)
            except (ValueError, TypeError, UnicodeError):
                return JSONResponse({"error": "invalid_destination"}, status_code=400)
            return original_failure(
                self,
                at,
                "Original interrupted or unavailable. Retry explicitly or return to text.",
                503,
                retry=link(at),
            )
        if request.url.path in ("/reader/read", "/reader/book-view"):
            at = request.query_params.get("at", "")
            try:
                decode_location(at)
            except (ValueError, TypeError, UnicodeError):
                at = ""
            target = request.url.path + "?" + urlencode({"at": at})
            response = self.page(
                '<p role="status">Reading interrupted. Retry this location or sign in again.</p><a href="'
                + escape(target)
                + '">Retry this location</a><a href="/reader/login?'
                + escape(urlencode({"return": at or "catalog"}))
                + '">Sign in again</a>'
            )
            response.status_code = 503
            return response
        if request.url.path in ("/reader", "/reader/catalog"):
            response = self.page(
                '<p role="status">'
                + escape(message)
                + '</p><a href="/reader/catalog">Retry catalog</a><a href="/reader/login">Sign in again</a>'
            )
            response.status_code = 503
            return response
        return JSONResponse({"error": code, "message": message}, status_code=503)

    def install(self, app, library):
        async def endpoint(request):
            with diagnostics.request(
                request.scope["route"].path
                if "route" in request.scope
                else request.url.path,
                request.method,
            ) as trace:
                deadline = asyncio.timeout(
                    IMAGE_DEADLINE if request.url.path == "/reader/image" else DEADLINE
                )
                try:
                    async with deadline:
                        if (
                            f"{request.url.scheme}://{request.url.netloc}"
                            != self.config.origin
                        ):
                            response = Response(status_code=400)
                        else:
                            response = await self.dispatch(request, library, trace)
                except Exception as error:  # noqa: BLE001 - boundary classification
                    failure = trace.fail(error, deadline_expired=deadline.expired())
                    response = self.failure(request, failure)
                return self.finish(request, response, trace)

        for path in (
            *ASSETS,
            "/reader",
            "/reader/catalog",
            "/reader/book",
            "/reader/bookmarks",
            "/reader/session",
            "/reader/read",
            "/reader/book-view",
            "/reader/book-info",
            "/reader/source",
            "/reader/content",
            "/reader/updates",
            "/reader/login",
            "/reader/callback",
            "/reader/signin-failed",
            "/reader/signed-out",
            "/reader/search",
            "/reader/original",
            "/reader/image",
        ):
            app.routes.insert(0, Route(path, endpoint))
        app.routes.insert(0, Route("/reader/vendor/{asset:path}", endpoint))
        app.routes.insert(
            0, Route("/reader/search/results", endpoint, methods=["POST"])
        )
        app.routes.insert(
            0, Route("/reader/personal", endpoint, methods=["GET", "POST"])
        )
        app.routes.insert(0, Route("/reader/reports", endpoint, methods=["POST"]))
        app.routes.insert(0, Route("/reader/logout", endpoint, methods=["POST"]))

    def finish(self, request, response, trace):
        if request.url.path == "/reader/callback" and response.status_code != 303:
            # Every failure, including storage/timeout/origin rejection, leaves
            # the transient protocol URL before rendering any reader UI.
            response = RedirectResponse("/reader/signin-failed", status_code=303)
            self.cookie(response, TRANSACTION, "", 0)
        response.headers.update(
            {
                "Cache-Control": "private, no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Strict-Transport-Security": "max-age=31536000",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' blob: 'unsafe-inline'; connect-src 'self'; img-src 'self' blob: data:; font-src 'self' blob: data:; frame-src 'self' blob:; worker-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'",
            }
        )
        if response.status_code == 503:
            if trace.failure is None:
                trace.fail(RuntimeError(), deadline_expired=False)
            failure = trace.failure
            if response.media_type == "application/json":
                body = json.loads(response.body)
                body.update(stage=failure.stage.label, request=failure.request)
                if body.get("error") != failure.category.value:
                    body["category"] = failure.category.value
                response.body = json.dumps(body).encode()
            elif response.media_type == "text/html":
                response.body += (
                    f'<meta name="reader-category" content="{failure.category.value}">'
                    f'<meta name="reader-stage" content="{failure.stage.label}">'
                    f'<p role="status">{escape(failure.reference())}</p>'
                ).encode()
            response.headers["Content-Length"] = str(len(response.body))
        trace.finish(response)
        return response
