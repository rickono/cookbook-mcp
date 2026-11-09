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

from .reader_diagnostics import Stage, stage
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


async def deliver(reader, request, library, owner=None, csrf="", *, entry_banner=""):
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
        with stage(Stage.LIBRARY_RESOLVE):
            return JSONResponse(await asyncio.to_thread(resolve_current, library, loc))
    try:
        # Distinguish a retired publication from a transient storage/runtime failure.
        with stage(Stage.LIBRARY_RESOLVE):
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
    data["source_location"] = await asyncio.to_thread(
        source_location, library, loc, _validated=data
    )
    if data["source_location"].get("source_key"):
        for key in ("next_text", "next_related", "next_contents"):
            if data.get(key):
                data[key] = move(
                    decode_location(data[key]),
                    source_key=data["source_location"]["source_key"],
                )
    data["update"] = await asyncio.to_thread(
        resolve_current, library, data["source_location"], _validated=data
    )
    if request.url.path == "/reader/content":
        return JSONResponse(data)
    c = data["citation"]
    body = (
        '<div class="reader-view '
        + ("contents-view" if "text" not in data else "")
        + '"><nav class="reading-crumbs" aria-label="Library"><a href="/reader/catalog">Books</a>'
        '<a href="/reader/search?'
        + escape(urlencode({"at": raw}))
        + '">Search this book</a>'
    )
    body += (
        '<a href="/reader/book-view?'
        + escape(urlencode({"at": raw}))
        + '">Read original</a>'
    )
    if back:
        body += anchor(back, "Return to originating location").replace(
            '">', '#text">', 1
        )
    body += (
        '</nav><header class="reading-head"><p class="kicker">'
        + escape(c["format"] + (" · " + c["title"] if c.get("section_title") else ""))
        + "</p><h1>"
        + escape(c.get("section_title", c["title"]))
        + '</h1><p class="reading-byline">'
        + escape(", ".join(c["authors"]))
        + "</p></header>"
    )
    body += entry_banner
    if "text" in data:
        body += (
            '<div class="reading-preferences" aria-label="Reading preferences" hidden>'
            '<details class="reading-menu"><summary>Contents</summary><nav aria-label="Book contents">'
        )
        from .reader_contents import contents_html

        body += contents_html(data, raw, back, anchor)
        body += (
            '</nav></details><button type="button" data-reading-focus aria-expanded="true">Reading tools</button>'
            '<details class="reading-menu type-menu"><summary>Text size</summary><div class="type-controls">'
            '<button type="button" data-text-smaller aria-label="Smaller text">A−</button>'
            '<output data-text-size aria-live="polite">100%</output>'
            '<button type="button" data-text-larger aria-label="Larger text">A+</button></div></details></div>'
        )
    elif not loc.get("contents_offset", 0):
        first = next((item for item in data["contents"] if item.get("at")), None)
        start = data.get("start_reading") or (first["at"] if first else None)
        if start:
            body += anchor(start, "Start reading").replace(
                "<a ", '<a class="button start-reading" ', 1
            )
    status = (
        '<p class="reading-status" data-reading-status role="status">'
        + {
            "partial_text": "More text follows.",
            "complete_text": "End of this section.",
            "withheld": "Text withheld by current withdrawal or supersession.",
        }.get(data["state"], "Book contents")
        + "</p>"
    )
    body += '<div class="reading-layout"><section class="reading-body">'
    if "text" not in data:
        body += status
    if "text" in data:
        from .reader_presentation import text_html

        body += (
            '<p class="trust-label">'
            + (
                "Approved content"
                if c["eligibility"]["eligible"]
                else "Unapproved source text · completeness not verified"
            )
            + "</p>"
        )
        body += (
            '<article id="text" tabindex="-1" aria-label="Source text">'
            + '<div class="reading-chunk" id="chunk-start">'
            + text_html(data)
            + "</div></article>"
            + status
        )
        if data["next_text"]:
            body += anchor(data["next_text"], "Continue reading", back=back).replace(
                "<a ", "<a data-next-text ", 1
            )
        if loc.get("offset", 0) and "target_id" not in loc:
            body += anchor(
                move(loc, offset=max(0, loc["offset"] - 4000)),
                "Previous text",
                back=back,
            )
    if "text" in data and data["state"] != "withheld":
        body += '<nav class="book-navigation" aria-label="Book navigation">'
        for item in data.get("adjacent", []):
            # Never skip undelivered text when offering forward navigation.
            forward = item["label"].startswith("Next")
            attributes = (
                "data-book-next" + (" hidden" if data.get("next_text") else "")
                if forward
                else "data-book-previous"
            )
            label = (
                "← Previous section"
                if item["label"].startswith("Previous")
                else "Next section →"
            )
            if item.get("title"):
                label += " · " + item["title"]
            body += anchor(item["at"], label).replace(
                "<a ", "<a " + attributes + " ", 1
            )
        contents = {
            k: v
            for k, v in loc.items()
            if k
            in (
                "publication_id",
                "book_id",
                "source_id",
                "source_key",
                "model_snapshot_id",
            )
        }
        body += anchor(encode_location(contents), "Book contents")
        body += "</nav>"
    for note in data.get("structure_notes", []):
        body += "<p>" + escape(note) + "</p>"
    body += '</section><aside class="reading-tools" aria-label="Reading tools">'
    body += (
        '<details class="source-details"><summary>Source and trust details</summary><pre>'
        + escape(
            json.dumps(
                {k: data[k] for k in ("citation", "check_regions") if k in data},
                ensure_ascii=False,
                indent=2,
            )
        )
        + "</pre><p>Reading a section does not establish complete recipe content or supporting preparations. Corrections and crop confirmation do not establish approval. Printed page labels remain unverified unless source metadata establishes them.</p></details>"
    )
    body += (
        '<details class="contents-panel"'
        + (" open" if "text" not in data else "")
        + '><summary>Contents</summary><nav aria-label="Contents">'
    )
    from .reader_contents import contents_html

    body += contents_html(data, raw, back, anchor)
    if c["format"] in ("PDF", "DJVU"):
        body += "<p>Page numbers count from the first page of the source file. Sections follow retained source order.</p>"
    body += "</nav><p>Only retained source structure is shown; missing chapter structure is not inferred.</p></details>"
    if "text" in data:
        body += '<nav aria-label="Authored references">'
        for item in data["related"] + data.get("references", []):
            body += (
                '<span data-reference-id="' + escape(item["id"]) + '">'
                if item.get("id")
                else ""
            )
            body += (
                anchor(item["at"], item["label"], back=raw)
                if item.get("at")
                else "<p>" + escape(item["label"]) + " — target unavailable</p>"
            )
            if item.get("id"):
                body += "</span>"
        if data["next_related"]:
            body += anchor(data["next_related"], "More related targets", back=back)
        body += '</nav><p class="fineprint">Absent relationships do not establish complete supporting work.</p>'
    body += (
        '<a class="button original-action" href="/reader/original?'
        + escape(urlencode({"at": raw, **({"back": back} if back else {})}))
        + '">Inspect originals</a>'
    )
    from .owner_reports import form
    from .reader_personal import controls

    body += controls(data["source_location"], data["state"] != "withheld")
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
    body += "</aside></div></div>"
    return reader.page(body, protected=True, presentation=True)


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
        pub,
        book,
        offset=loc.get("contents_offset", 0),
        limit=30,
        _reader_contents=True,
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
                    **({"group": item["group"]} if item.get("group") else {}),
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
    if section["citation"]["format"] in ("PDF", "DJVU"):
        from .reader_contents import section_label

        citation = data["citation"]
        citation["section_title"] = section_label(
            citation.get("section_title"),
            section["kind"],
            citation["locator"].get("physical_pages", []),
        )
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
