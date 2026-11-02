"""Identifier-only reading destinations and bounded shared-library delivery.

No browser-supplied locator is used as a storage path or redirect URL. Destinations
are references, never authorization. Every delivery rechecks the session and Library.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from html import escape
from urllib.parse import urlencode

from starlette.responses import JSONResponse

from .storage import IntegrityError, canonical

KEYS = {
    "publication_id",
    "book_id",
    "source_id",
    "section_id",
    "offset",
    "related_offset",
    "contents_offset",
    "target_id",
    "model_snapshot_id",
    "cursor",
    "source_key",
}


def encode_location(value):
    return base64.urlsafe_b64encode(canonical(value)).decode().rstrip("=")


def decode_location(raw):
    if not raw or len(raw) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        raise ValueError("invalid destination")
    value = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    if (
        not isinstance(value, dict)
        or set(value) - KEYS
        or not {"publication_id", "book_id", "source_id"} <= value.keys()
    ):
        raise ValueError("invalid destination")
    for key, item in value.items():
        if key.endswith("offset"):
            if type(item) is not int or not 0 <= item <= 1000000000:
                raise ValueError("invalid offset")
        elif key == "cursor":
            if not isinstance(item, str) or not re.fullmatch(
                r"[A-Za-z0-9_=-]{1,512}", item
            ):
                raise ValueError("invalid cursor")
        elif not isinstance(item, str) or not re.fullmatch(
            r"[A-Za-z0-9:_-]{1,256}", item
        ):
            raise ValueError("invalid identifier")
    if "source_key" in value and not re.fullmatch(r"[a-f0-9]{64}", value["source_key"]):
        raise ValueError("invalid source key")
    if not re.fullmatch(r"[a-f0-9]{32}", value["publication_id"]):
        raise ValueError("invalid publication")
    if "section_id" in value and any(
        k in value for k in ("target_id", "cursor", "model_snapshot_id")
    ):
        raise ValueError("mixed source paths")
    if "cursor" in value and not {"target_id", "model_snapshot_id"} <= value.keys():
        raise ValueError("unbound native continuation")
    return value


def reading_link(citation):
    """Shared contract for catalog/search/dashboard; source identifiers only."""
    value = {k: citation[k] for k in ("publication_id", "book_id", "source_id")}
    for key in ("section_id", "target_id", "model_snapshot_id"):
        if citation.get(key):
            value[key] = citation[key]
    return "/reader/read?" + urlencode({"at": encode_location(value)})


def move(location, **changes):
    return encode_location({**location, **changes})


def anchor(at, label, *, back=None):
    query = {"at": at}
    if back:
        query["back"] = back
    return (
        '<a href="/reader/read?'
        + escape(urlencode(query))
        + '">'
        + escape(label)
        + "</a>"
    )


async def deliver(reader, request, library, owner=None, csrf=""):
    raw = request.query_params.get("at", "")
    try:
        loc = decode_location(raw)
        back = request.query_params.get("back")
        if back:
            decode_location(back)
    except (ValueError, TypeError, UnicodeError):
        return JSONResponse({"error": "invalid_destination"}, status_code=400)
    from .reader_updates import notice_markup, resolve_current, source_location

    if request.url.path == "/reader/updates":
        return JSONResponse(await asyncio.to_thread(resolve_current, library, loc))
    try:
        # Distinguish a retired publication from a transient storage/runtime failure.
        await asyncio.to_thread(library.publication, loc["publication_id"])
    except IntegrityError:
        return page_error(
            reader,
            "Publication unavailable or retired. This exact reading link cannot be opened.",
            410,
            notice_markup(
                await asyncio.to_thread(resolve_current, library, loc),
                loc["publication_id"],
            ),
        )
    try:
        data = await asyncio.to_thread(read, library, loc)
    except IntegrityError:
        return page_error(
            reader,
            "Source location unavailable. No replacement location was selected.",
            404,
            notice_markup(
                await asyncio.to_thread(resolve_current, library, loc),
                loc["publication_id"],
            ),
        )
    data["source_location"] = await asyncio.to_thread(source_location, library, loc)
    if data["source_location"].get("source_key"):
        for key in ("next_text", "next_related", "next_contents"):
            if data.get(key):
                data[key] = move(
                    decode_location(data[key]),
                    source_key=data["source_location"]["source_key"],
                )
    data["update"] = await asyncio.to_thread(
        resolve_current, library, data["source_location"]
    )
    if request.url.path == "/reader/content":
        return JSONResponse(data)
    c = data["citation"]
    body = '<nav aria-label="Library"><a href="/reader/catalog">Books</a>'
    if back:
        body += anchor(back, "Return to originating location")
    body += (
        "</nav><header><h2>"
        + escape(c.get("section_title", c["title"]))
        + "</h2><p>"
        + escape(c["title"] + " · " + ", ".join(c["authors"]))
        + "</p></header>"
    )
    body += (
        '<p role="status">'
        + {
            "partial_text": "Partial text — more text remains.",
            "complete_text": "End of section text. Earlier chunks remain available through Previous text. This does not establish a complete recipe or supporting work.",
            "withheld": "Text withheld by current withdrawal or supersession.",
        }.get(data["state"], "Book contents")
        + "</p>"
    )
    if "text" in data:
        body += (
            "<p>"
            + (
                "Approved content"
                if c["eligibility"]["eligible"]
                else "Unapproved content — readable text is not approval."
            )
            + "</p>"
        )
        body += (
            '<article id="text" tabindex="-1" aria-label="Source text"><div class="source-text">'
            + escape(data["text"])
            + "</div></article>"
        )
        if data["next_text"]:
            body += anchor(data["next_text"], "Continue text", back=back).replace(
                "<a ", "<a data-next-text ", 1
            )
        if loc.get("offset", 0) and "target_id" not in loc:
            body += anchor(
                move(loc, offset=max(0, loc["offset"] - 4000)),
                "Previous text",
                back=back,
            )
    for note in data.get("structure_notes", []):
        body += "<p>" + escape(note) + "</p>"
    body += (
        "<details><summary>Source and trust details</summary><pre>"
        + escape(
            json.dumps(
                {k: data[k] for k in ("citation", "check_regions") if k in data},
                ensure_ascii=False,
                indent=2,
            )
        )
        + "</pre><p>Corrections and crop confirmation do not establish approval. Printed page labels remain unverified unless source metadata establishes them.</p></details>"
    )
    body += '<details><summary>Contents</summary><nav aria-label="Contents">'
    for item in data["contents"]:
        body += (
            anchor(item["at"], item["title"], back=raw)
            if item.get("at")
            else "<p>" + escape(item["title"]) + " — source target unresolved</p>"
        )
    if data["next_contents"]:
        body += anchor(data["next_contents"], "More contents", back=back)
    body += "</nav><p>Only retained source structure is shown; missing chapter structure is not inferred.</p></details>"
    for item in data.get("adjacent", []):
        body += anchor(item["at"], item["label"], back=raw)
    if "text" in data:
        body += '<nav aria-label="Authored references">'
        for item in data["related"] + data.get("references", []):
            body += (
                anchor(item["at"], item["label"], back=raw)
                if item.get("at")
                else "<p>" + escape(item["label"]) + " — target unavailable</p>"
            )
        if data["next_related"]:
            body += anchor(data["next_related"], "More related targets", back=back)
        body += "</nav><p>Absent relationships do not establish complete supporting work.</p>"
    body += (
        '<a href="/reader/original?'
        + escape(urlencode({"at": raw}))
        + '">Inspect originals</a>'
    )
    from .owner_reports import form

    body += form(reader, data, loc, owner, csrf)
    body += '<script src="/reader/content.js" defer></script>'
    durable = {
        **loc,
        **{
            k: v
            for k, v in data["source_location"].items()
            if k in ("source_key", "model_snapshot_id")
        },
    }
    body += anchor(encode_location(durable), "Link to this location")
    body += notice_markup(data["update"], loc["publication_id"]).replace(
        'id="publication-update"',
        'id="publication-update" data-at="' + encode_location(durable) + '"',
    )
    body += '<script src="/reader/updates.js" defer></script>'
    return reader.page(body, protected=True)


def page_error(reader, message, status, recovery=""):
    result = reader.page(
        '<p role="status">'
        + escape(message)
        + '</p><a href="/reader/catalog">Books</a>'
        + recovery,
        protected=True,
    )
    result.status_code = status
    return result


def read(library, loc):
    pub, book, source = (loc[k] for k in ("publication_id", "book_id", "source_id"))
    book_data = library.get_book(
        pub, book, offset=loc.get("contents_offset", 0), limit=30
    )
    from .book_model import MODEL_PATH

    if (
        "section_id" not in loc
        and book_data["citation"]["format"] == "EPUB"
        and any(e.path == MODEL_PATH for e in library.runtime.manifest(pub).files)
    ):
        from .reader_native import read_native

        return read_native(library, loc)
    if book_data["citation"]["source_id"] != source:
        raise IntegrityError("source mismatch")
    base = {"publication_id": pub, "book_id": book, "source_id": source}
    data = {
        "citation": book_data["citation"],
        "state": "contents",
        "contents": [],
        "next_contents": None,
    }
    for item in book_data["toc"]:
        if item.get("section_id"):
            data["contents"].append(
                {
                    "title": item["title"],
                    "at": encode_location({**base, "section_id": item["section_id"]}),
                }
            )
    if book_data["next_offset"] is not None:
        data["next_contents"] = move(loc, contents_offset=book_data["next_offset"])
    if "target_id" in loc:
        raise IntegrityError("native target unavailable")
    if "section_id" not in loc:
        return data
    section = library.read_section(
        pub, book, source, loc["section_id"], offset=loc.get("offset", 0), limit=4000
    )
    # Related targets are delivered only through their independent bounded page.
    section["citation"]["locator"].pop("references", None)
    data.update(section)
    reasons = section["eligibility"]["reasons"]
    withheld = any(
        r in reasons
        for r in (
            "approval_revoked",
            "confirmed_substantive_error",
            "superseded_transcription",
        )
    )
    data["state"] = (
        "withheld"
        if withheld
        else "partial_text"
        if section["next_offset"] is not None
        else "complete_text"
    )
    data["next_text"] = (
        move(loc, offset=section["next_offset"])
        if section["next_offset"] is not None
        else None
    )
    relationships = library.section_navigation(
        pub, book, source, loc["section_id"], offset=loc.get("related_offset", 0)
    )
    data["related"] = [
        {
            "label": r["label"],
            "at": encode_location({**base, "section_id": r["section_id"]})
            if r.get("section_id")
            else None,
        }
        for r in relationships["related"]
    ]
    data["next_related"] = (
        move(loc, related_offset=relationships["next_offset"])
        if relationships["next_offset"] is not None
        else None
    )
    data["adjacent"] = [
        {
            "label": r["label"],
            "at": encode_location({**base, "section_id": r["section_id"]}),
        }
        for r in relationships["adjacent"]
    ]
    return data
