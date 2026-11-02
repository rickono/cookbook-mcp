"""Hosted browser session boundary. Library access remains shared and read-only."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import jwt
from cryptography.fernet import Fernet
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .reader_content import decode_location, deliver, reading_link
from .storage import Conflict, canonical

COOKIE = "__Host-reader"
TRANSACTION = "__Host-reader-login"
IDLE = 7 * 86400
LIFETIME = 30 * 86400


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
        self, config, verifier, store, encryption_key, *, identity=None, clock=time.time
    ):
        if urlsplit(verifier.issuer).scheme != "https" or not verifier.issuer.endswith(
            "/"
        ):
            raise ValueError("exact HTTPS issuer ending in slash required")
        self.config, self.verifier, self.store = config, verifier, store
        self.cipher = Fernet(encryption_key)
        self.identity = identity or IdentityProvider(config, verifier)
        self.clock = clock

    async def read(self, key):
        raw, version = await asyncio.to_thread(self.store.read_version, key)
        return (json.loads(self.cipher.decrypt(raw)) if raw else None), version

    async def write(self, key, value, version=None):
        return await asyncio.to_thread(
            self.store.put_bytes,
            key,
            self.cipher.encrypt(canonical(value)),
            expected=version,
        )

    def owner_key(self, subject):
        return "reader/owners/" + digest(subject)

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

    async def revoke(self, sessions):
        async def attempt(session):
            if session.get("refresh"):
                try:
                    async with asyncio.timeout(5):
                        await self.identity.revoke(session["refresh"])
                except Exception:  # noqa: BLE001
                    return False  # Reader invalidation is independent of provider availability.

        await asyncio.gather(*(attempt(session) for session in sessions))

    async def authenticate(self, request):
        """Authorize one request; returned session is server-only and must never be serialized."""
        sid = request.cookies.get(COOKIE, "")
        if len(sid) != 43:
            return None
        # Allowlist is normally one owner; tokens still undergo verification every request.
        for subject in self.verifier.subjects:
            key = self.owner_key(subject)
            owner, version = await self.read(key)
            sessions = owner.get("sessions", {}) if owner else {}
            session = sessions.get(digest(sid))
            if not session:
                continue
            now = self.clock()
            if now - session["seen"] >= IDLE or now - session["created"] >= LIFETIME:
                del sessions[digest(sid)]
                await self.write(key, owner, version)
                await self.revoke([session])
                return None
            if session.get("renewing"):
                # Concurrent tabs retry; a crashed exchange expires instead of replaying a rotating token.
                if now - session["renewing"] < 10:
                    raise Conflict("renewal pending")
                del sessions[digest(sid)]
                await self.write(key, owner, version)
                await self.revoke([session])
                return None
            expected_session = canonical(session)
            renewed = False
            token = await self.verifier.verify_token(session["access"])
            if token is None:
                # Only expiry can renew. Invalid claims/signatures must never be repaired by login state.
                expired = await self.verifier.verify_token(
                    session["access"], allow_expired=True
                )
                if (
                    not expired
                    or expired.subject != subject
                    or "library:read" not in expired.scopes
                    or not session.get("refresh")
                ):
                    del sessions[digest(sid)]
                    await self.write(key, owner, version)
                    await self.revoke([session])
                    return None
                session["renewing"] = now
                version = await self.write(key, owner, version)
                expected_session = canonical(session)
                try:
                    tokens = await self.identity.renew(session["refresh"])
                    token = await self.verifier.verify_token(
                        tokens.get("access_token", "")
                    )
                    if (
                        not token
                        or token.subject != subject
                        or "library:read" not in token.scopes
                    ):
                        raise ValueError("authorization lost")
                    session["access"] = tokens["access_token"]
                    session["refresh"] = (
                        tokens.get("refresh_token") or session["refresh"]
                    )
                    session.pop("renewing")
                    renewed = True
                except Exception:  # noqa: BLE001
                    del sessions[digest(sid)]
                    await self.write(key, owner, version)
                    await self.revoke([session])
                    return None
            if token.subject != subject or "library:read" not in token.scopes:
                del sessions[digest(sid)]
                await self.write(key, owner, version)
                await self.revoke([session])
                return None
            if request.url.path != "/reader/session":
                session["seen"] = now
            for attempt in range(3):
                try:
                    await self.write(key, owner, version)
                    return subject, session
                except Conflict:
                    # Preserve other devices' updates without resurrecting a logged-out session.
                    owner, version = await self.read(key)
                    current = (
                        owner.get("sessions", {}).get(digest(sid)) if owner else None
                    )
                    if current is None:
                        if renewed:
                            await self.revoke([session])
                        return None
                    if canonical(current) != expected_session or attempt == 2:
                        if renewed:
                            await self.revoke([session])
                        raise
                    owner["sessions"][digest(sid)] = session
        return None

    def page(self, body, *, protected=False):
        return HTMLResponse(
            '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cookbook library</title><link rel="stylesheet" href="/reader/style.css">'
            + ('<script src="/reader/session.js" defer></script>' if protected else "")
            + "<body><main><h1>Cookbook library</h1>"
            + body
            + "</main></body></html>"
        )

    def expired(self, destination=None):
        r = self.page(
            '<p role="status">Sign in to read your private library.</p><a href="/reader/login?'
            + escape(urlencode({"return": destination or "catalog"}))
            + '">Sign in</a>'
        )
        r.status_code = 401
        self.cookie(r, COOKIE, "", 0)
        return r

    async def dispatch(self, request, library):
        path = request.url.path
        if path == "/reader/style.css":
            return Response(
                "body{font:18px/1.6 system-ui;margin:0;color:#20251f;background:#faf8f2}main{max-width:65ch;padding:1rem;margin:auto}a,button{display:inline-block;min-height:44px;box-sizing:border-box;padding:.5rem}button{font:inherit}.source-text{white-space:pre-wrap;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{min-height:44px;cursor:pointer}li{margin-block:1rem;overflow-wrap:anywhere}:focus-visible{outline:3px solid #375d9c;outline-offset:3px}",
                media_type="text/css",
            )
        if path == "/reader/content.js":
            return Response(
                Path(__file__).with_name("reader_content.js").read_text(),
                media_type="text/javascript",
            )
        if path == "/reader/session.js":
            return Response(
                """async function check(){try{let r=await fetch('/reader/session',{cache:'no-store'});if(r.status===401){document.querySelector('main').replaceChildren();const at=new URL(location.href).searchParams.get('at');location.replace(at?'/reader/login?'+new URLSearchParams({return:at}):'/reader');}}catch{}}setInterval(check,60000);addEventListener('pageshow',check);addEventListener('focus',check);document.addEventListener('visibilitychange',()=>{if(!document.hidden)check()});""",
                media_type="text/javascript",
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
                tokens = await self.identity.exchange(
                    q["code"], txn["pkce"], txn["nonce"]
                )
                token = await self.verifier.verify_token(tokens.get("access_token", ""))
                if not token or "library:read" not in token.scopes:
                    raise ValueError("unauthorized")
            except Exception:  # noqa: BLE001
                return self.expired()
            owner_key = self.owner_key(token.subject)
            owner, version = await self.read(owner_key)
            owner = owner or {"sessions": {}}
            now = self.clock()
            owner["sessions"] = {
                k: s
                for k, s in owner["sessions"].items()
                if now - s["seen"] < IDLE and now - s["created"] < LIFETIME
            }
            if len(owner["sessions"]) >= 100:
                return JSONResponse({"error": "session_limit"}, status_code=409)
            sid = opaque()
            owner["sessions"][digest(sid)] = {
                "access": tokens["access_token"],
                "refresh": tokens.get("refresh_token"),
                "created": now,
                "seen": now,
                "csrf": opaque(),
            }
            await self.write(owner_key, owner, version)
            destination = txn.get("destination", "catalog")
            r = RedirectResponse(
                "/reader/catalog"
                if destination == "catalog"
                else "/reader/read?" + urlencode({"at": destination}),
                status_code=303,
            )
            self.cookie(r, COOKIE, sid, LIFETIME)
            self.cookie(r, TRANSACTION, "", 0)
            return r
        auth = await self.authenticate(request)
        if not auth:
            destination = (
                request.query_params.get("at")
                if path in ("/reader/read", "/reader/content")
                else None
            )
            if destination:
                try:
                    decode_location(destination)
                except (ValueError, TypeError, UnicodeError):
                    destination = None
            return self.expired(destination)
        subject, session = auth
        if path in ("/reader/read", "/reader/content"):
            return await deliver(self, request, library)
        if path == "/reader/session":
            return JSONResponse({"authenticated": True, "csrf": session["csrf"]})
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
            data = dict(parse_qsl(payload.decode()))
            if not secrets.compare_digest(
                data.get("csrf", ""), session["csrf"]
            ) or data.get("scope") not in ("device", "all"):
                return JSONResponse({"error": "csrf_or_scope_denied"}, status_code=403)
            key = self.owner_key(subject)
            owner, version = await self.read(key)
            if data["scope"] == "all":
                removed = list(owner["sessions"].values())
                owner["sessions"] = {}
            else:
                removed = [
                    owner["sessions"].pop(digest(request.cookies[COOKIE]), session)
                ]
            await self.write(key, owner, version)
            await self.revoke(removed)
            r = self.page(
                '<p role="status">Reader signed out. Google, MCP and copied access tokens may remain signed in.</p><a href="/reader/login">Sign in again</a>'
            )
            if data["scope"] == "device":
                r = RedirectResponse(
                    self.verifier.issuer
                    + "v2/logout?"
                    + urlencode(
                        {
                            "client_id": self.config.client_id,
                            "returnTo": self.config.origin + "/reader",
                        }
                    ),
                    status_code=303,
                )
            self.cookie(r, COOKIE, "", 0)
            r.headers["Clear-Site-Data"] = '"cache", "storage"'
            return r
        if path in ("/reader", "/reader/catalog"):
            q = request.query_params
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
                    "<li><strong>"
                    + escape(c["title"])
                    + "</strong><br>"
                    + escape(", ".join(c["authors"]))
                    + " · "
                    + escape(c["format"])
                    + ' · Published <a href="'
                    + escape(reading_link(c))
                    + '">Open book</a></li>'
                )
            body = (
                '<nav aria-label="Account"><form method="post" action="/reader/logout"><input type="hidden" name="csrf" value="'
                + escape(session["csrf"])
                + '"><button name="scope" value="device">Sign out this device</button><button name="scope" value="all">Sign out all reader devices</button></form></nav><p>Logout ends reader access. It does not sign out Google or MCP, revoke copied valid tokens immediately, or erase content already delivered.</p><h2>Published books</h2><ul>'
                + "".join(rows)
                + "</ul>"
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

    def failure(self, request, code, message):
        if request.url.path == "/reader/read":
            at = request.query_params.get("at", "")
            try:
                decode_location(at)
            except (ValueError, TypeError, UnicodeError):
                at = ""
            target = "/reader/read?" + urlencode({"at": at})
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
            try:
                async with asyncio.timeout(10):
                    if (
                        f"{request.url.scheme}://{request.url.netloc}"
                        != self.config.origin
                    ):
                        response = Response(status_code=400)
                    else:
                        response = await self.dispatch(request, library)
            except Conflict:
                response = self.failure(
                    request, "session_changed", "Retry this request."
                )
            except Exception:  # noqa: BLE001
                response = self.failure(
                    request,
                    "reader_unavailable",
                    "Reader unavailable. Retry or sign in again.",
                )
            response.headers.update(
                {
                    "Cache-Control": "private, no-store",
                    "Pragma": "no-cache",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                    "Strict-Transport-Security": "max-age=31536000",
                    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
                }
            )
            return response

        for path in (
            "/reader",
            "/reader/catalog",
            "/reader/session",
            "/reader/read",
            "/reader/content",
            "/reader/login",
            "/reader/callback",
            "/reader/style.css",
            "/reader/session.js",
            "/reader/content.js",
        ):
            app.routes.insert(0, Route(path, endpoint))
        app.routes.insert(0, Route("/reader/logout", endpoint, methods=["POST"]))
