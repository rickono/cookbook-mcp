"""Owner-only identifier metadata, atomically ordered separately from publications."""

import asyncio
import hashlib
import json
import re
import secrets
import unicodedata
from html import escape
from urllib.parse import urlencode

from starlette.responses import JSONResponse, RedirectResponse

from .reader_content import decode_location, encode_location
from .reader_diagnostics import Stage, stage
from .reader_updates import resolve_current, source_location
from .storage import Conflict, IntegrityError, canonical


class PersonalState:
    def __init__(self, store):
        self.store = store

    def load(self, owner):
        key = "reader-personal/owners/" + hashlib.sha256(owner.encode()).hexdigest()
        raw, version = self.store.read_version(key)
        return (
            key,
            json.loads(raw)
            if raw
            else {"bookmarks": {}, "resume": {}, "operations": {}, "revision": 0},
            version,
        )

    def mutate(self, owner, operation, library):
        fingerprint = hashlib.sha256(canonical(operation)).hexdigest()
        for _ in range(8):
            key, state, version = self.load(owner)
            prior = state["operations"].get(operation["operation_id"])
            if prior:
                if prior["fingerprint"] != fingerprint:
                    return {"error": "operation_conflict"}, 409
                return prior["result"], 200
            if len(state["operations"]) >= 10000:
                return {"error": "metadata_limit"}, 429
            action = operation["action"]
            identity = operation.get("bookmark_id", operation["operation_id"])
            if action in ("save", "resume"):
                loc = source_location(library, decode_location(operation["at"]))
                # Contents and chunk offsets are not stable reading progress.
                if action == "resume" and not (
                    loc.get("section_id") or loc.get("target_id")
                ):
                    return {"error": "stable_location_required"}, 400
                if action == "save":
                    if len(state["bookmarks"]) >= 1000:
                        return {"error": "metadata_limit"}, 429
                    state["bookmarks"][identity] = {
                        "location": loc,
                        "name": operation["name"],
                    }
                else:
                    edition = edition_key(loc)
                    state["resume"][edition] = loc
            elif action == "rename":
                if identity not in state["bookmarks"]:
                    return {"error": "bookmark_missing"}, 404
                state["bookmarks"][identity]["name"] = operation["name"]
            else:
                state["bookmarks"].pop(identity, None)
            state["revision"] += 1
            result = {
                "status": "removed" if action == "remove" else "saved",
                "revision": state["revision"],
                "bookmark_id": identity if action != "resume" else None,
            }
            state["operations"][operation["operation_id"]] = {
                "fingerprint": fingerprint,
                "result": result,
            }
            try:
                self.store.put_bytes(key, canonical(state), expected=version)
                return result, 200
            except Conflict:
                continue
        return {"error": "personal_busy"}, 503


def edition_key(loc):
    return hashlib.sha256(canonical([loc["book_id"], loc["source_id"]])).hexdigest()


def clean_name(name):
    if not isinstance(name, str) or len(name) > 120:
        raise ValueError()
    # Plain Unicode text; remove control/bidi formatting and normalize whitespace.
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFC", name)
            if not unicodedata.category(c).startswith("C")
        ).split()
    )


async def endpoint(reader, request, library, owner, session):
    if request.query_params:
        return JSONResponse({"error": "use_private_body"}, status_code=400)
    if request.method == "GET":
        if reader.personal_state is None:
            return JSONResponse({"error": "personal_unavailable"}, status_code=503)
        _, state, _ = await asyncio.to_thread(reader.personal_state.load, owner)
        resolved_locations = {}

        def resolve(location):
            key = canonical(location)
            if key not in resolved_locations:
                resolved_locations[key] = resolve_current(library, location)
            return resolved_locations[key]

        rows = []
        for identity, row in state["bookmarks"].items():
            with stage(Stage.LIBRARY_RESOLVE):
                resolved = await asyncio.to_thread(resolve, row["location"])
            rows.append({"bookmark_id": identity, "name": row["name"], **resolved})
        resumes = []
        for loc in state["resume"].values():
            with stage(Stage.LIBRARY_RESOLVE):
                resolved = await asyncio.to_thread(resolve, loc)
            resumes.append(
                {"book_id": loc["book_id"], "source_id": loc["source_id"], **resolved}
            )
        return JSONResponse(
            {"bookmarks": rows, "resume": resumes, "revision": state["revision"]}
        )
    if request.headers.get("origin") != reader.config.origin:
        return JSONResponse({"error": "origin_denied"}, status_code=403)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            return JSONResponse({"error": "too_large"}, status_code=413)
    try:
        value = json.loads(body)
        if not isinstance(value, dict) or not secrets.compare_digest(
            value.get("csrf", ""), session.csrf
        ):
            return JSONResponse({"error": "csrf_denied"}, status_code=403)
        action = value["action"]
        fields = {
            "save": {"at", "name"},
            "resume": {"at"},
            "rename": {"bookmark_id", "name"},
            "remove": {"bookmark_id"},
        }[action]
        if set(value) != fields | {"csrf", "action", "operation_id"}:
            raise ValueError()
        for field in ("operation_id", "bookmark_id"):
            if field in value and not re.fullmatch("[a-f0-9]{32}", value[field]):
                raise ValueError()
        value.pop("csrf")
        if "name" in value:
            value["name"] = clean_name(value["name"])
        if "at" in value:
            decode_location(value["at"])
    except (ValueError, TypeError, KeyError):
        return JSONResponse({"error": "invalid_metadata"}, status_code=400)
    if reader.personal_state is None:
        return JSONResponse({"error": "personal_unavailable"}, status_code=503)
    try:
        async with asyncio.timeout(8):
            result, status = await asyncio.to_thread(
                reader.personal_state.mutate, owner, value, library
            )
    except IntegrityError:
        return JSONResponse({"error": "location_unavailable"}, status_code=404)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "persistence_unconfirmed"}, status_code=503)
    return JSONResponse(result, status_code=status)


async def book_entry(reader, request, library, owner, csrf=""):
    """Offer resume alongside contents; explicit /read destinations bypass it."""
    try:
        loc = decode_location(request.query_params["at"])
        if set(loc) != {"publication_id", "book_id", "source_id"}:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        return JSONResponse({"error": "invalid_destination"}, status_code=400)
    if reader.personal_state:
        _, state, _ = await asyncio.to_thread(reader.personal_state.load, owner)
        saved = state["resume"].get(edition_key(loc))
        if saved:
            with stage(Stage.LIBRARY_RESOLVE):
                resolved = await asyncio.to_thread(resolve_current, library, saved)
            body = '<div class="actions resume-reading">'
            if resolved["at"]:
                body += (
                    '<a class="button button-primary" href="/reader/book-view?'
                    + escape(urlencode({"at": resolved["at"]}))
                    + '">Resume this edition</a>'
                )
            else:
                body += "<p>Remembered location unavailable. Your reference is retained.</p>"
            body += "</div>"
            from .reader_book import deliver

            return await deliver(
                reader, request, library, owner, csrf, entry_banner=body
            )
    return RedirectResponse(
        "/reader/book-view?" + urlencode({"at": encode_location(loc)}), status_code=303
    )


def controls(location, available=True):
    stable = available and bool(location.get("section_id") or location.get("target_id"))
    return (
        '<section id="reader-personal" data-at="'
        + encode_location(location)
        + '" data-stable="'
        + ("true" if stable else "false")
        + '"><details class="bookmark-panel"><summary>Save a bookmark</summary>'
        '<form id="bookmark-save" method="post" action="/reader/personal" autocomplete="off"><label>Bookmark name (optional)<input name="name" maxlength="120" placeholder="A name to remember"></label><button>Save bookmark</button></form></details>'
        '<button class="button-quiet" id="remember-location" type="button"'
        + ("" if stable else " disabled")
        + '>Remember this location</button><p id="personal-status" role="status"></p></section><script src="/reader/personal.js" defer></script>'
    )


def bookmarks_page(reader):
    return reader.page(
        '<div class="layout layout-page"><header class="page-head"><p class="kicker">Worth coming back to</p><h1>Bookmarks</h1><p class="lede">Good things, kept close.</p></header>'
        '<section id="reader-personal"><div class="bookmarks-toolbar"><button class="button-quiet" id="personal-refresh">Refresh bookmarks</button></div>'
        '<ul id="bookmark-list"></ul><p id="personal-status" role="status"></p></section></div><script src="/reader/personal.js" defer></script>',
        protected=True,
    )
