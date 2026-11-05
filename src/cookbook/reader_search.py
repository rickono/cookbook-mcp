"""Transient browser search adapter over the two existing Library retrieval paths."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from html import escape

from starlette.responses import JSONResponse

from .book_model import MODEL_PATH
from .reader_content import reading_link
from .storage import IntegrityError

KINDS = ("recipe", "passage", "reference_entry", "division", "pairing_assertion")
COVERAGE = (
    "Coverage is partial or unknown: unindexed, unsearched and withheld material "
    "is not established absent. Recipes, essays, techniques and reference entries "
    "are found only where existing indexes cover their authored text."
)


def page(reader, book_id="", *, csrf):
    options = "".join(
        f'<option value="{k}">{k.replace("_", " ")}</option>' for k in KINDS
    )
    return reader.page(
        '<div class="layout layout-page"><header class="page-head"><p class="kicker">Find your next meal</p>'
        '<h1>Search library</h1><p class="lede">An ingredient, a dish, a little inspiration.</p></header>'
        f'<form class="search-form" id="search-form" data-book="{escape(book_id, quote=True)}" data-csrf="{escape(csrf, quote=True)}" method="post" action="/reader/search/results" autocomplete="off">'
        '<div class="search-bar"><div class="field"><label for="query">Keywords</label>'
        '<input id="query" name="query" placeholder="Try lemon, lentils, or a favorite dish" maxlength="200" required></div>'
        '<button type="submit">Search</button></div><div class="search-filters">'
        '<div class="field"><label for="book">Look in</label><select id="book" name="book_id"><option value="">Whole library</option></select>'
        '<button class="button-quiet" type="button" id="more-scopes" hidden>Load more book scopes</button></div>'
        '<div class="field"><label for="kind">Content type</label><select id="kind" name="kind"><option value="">All authored material</option>'
        + options
        + '</select></div></div><details class="search-help"><summary>About search and filters</summary><div>'
        '<p class="fineprint">Content matches use native typo-tolerant keywords. Section matches require all query words. '
        "Ranking is independent; phrase, Boolean and uniform matching are not promised.</p>"
        '<p class="fineprint" id="classification">A content type searches only interpreted Content matches. '
        "Classification is partial; unclassified authored material may be missed.</p>"
        '<fieldset disabled aria-describedby="unsupported"><legend>Unavailable filters</legend>'
        "<label>Author<input></label><label>Tag<input></label><label>Format<input></label></fieldset>"
        '<p class="fineprint" id="unsupported">Author, tag and format filters are disabled because Content search '
        "does not support them consistently with Section search. Format is shown on each match.</p></div></details></form>"
        "<noscript>Search requires script to retain your query privately in this live tab.</noscript>"
        '<p id="search-status" role="status" aria-live="polite"></p>'
        '<button id="fresh-search" hidden>Start fresh search on current publication</button>'
        '<section class="result-group" aria-labelledby="content-title"><h2 id="content-title">Content matches</h2>'
        '<p class="group-status" id="content-status"></p><ol class="results" id="content-results"></ol><button id="content-more" hidden>Load more Content matches</button></section>'
        '<section class="result-group" aria-labelledby="section-title"><h2 id="section-title">Section matches</h2>'
        '<p class="group-status" id="section-status"></p><ol class="results" id="section-results"></ol><button id="section-more" hidden>Load more Section matches</button></section></div>'
        '<script src="/reader/search.js" defer></script>',
        protected=True,
    )


def validate(data):
    if not isinstance(data, dict) or set(data) - {
        "csrf",
        "query",
        "book_id",
        "kind",
        "publication_id",
        "group",
        "content_page",
        "section_offset",
    }:
        raise ValueError
    for name in ("query", "book_id", "kind", "publication_id", "csrf", "group"):
        if name in data and not isinstance(data[name], str):
            raise ValueError
    if not data.get("query", "").strip() or len(data["query"]) > 200:
        raise ValueError
    if data.get("kind") and data["kind"] not in KINDS:
        raise ValueError
    if data.get("group", "both") not in ("both", "content", "section"):
        raise ValueError
    if data.get("publication_id") and not re.fullmatch(
        r"[a-f0-9]{32}", data["publication_id"]
    ):
        raise ValueError
    if len(data.get("book_id", "")) > 256 or len(data.get("publication_id", "")) > 32:
        raise ValueError
    for name, low, high in (("content_page", 1, 100), ("section_offset", 0, 10000)):
        n = data.get(name, low)
        if type(n) is not int or not low <= n <= high:
            raise ValueError
        if n != low and not data.get("publication_id"):
            raise ValueError


async def results(request, library, reader, session):
    if request.query_params:
        return JSONResponse({"error": "use_private_post_body"}, status_code=400)
    if request.headers.get("origin") != reader.config.origin:
        return JSONResponse({"error": "origin_denied"}, status_code=403)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
    try:
        data = json.loads(body)
        validate(data)
    except (ValueError, TypeError, UnicodeError):
        return JSONResponse({"error": "invalid_search"}, status_code=400)
    if not data.get("csrf", "").isascii() or not secrets.compare_digest(
        data.get("csrf", ""), session.csrf
    ):
        return JSONResponse({"error": "csrf_denied"}, status_code=403)
    try:
        pub = await asyncio.to_thread(
            library.publication, data.get("publication_id") or None
        )
    except IntegrityError:
        return JSONResponse(
            {"error": "publication_retired", "fresh_search_required": True},
            status_code=410,
        )
    book_ids = [data["book_id"]] if data.get("book_id") else None

    async def group(name):
        if name == "section" and data.get("kind"):
            return {
                "state": "excluded",
                "results": [],
                "next": None,
                "coverage": "Content type narrows to interpreted Content matches only.",
            }
        try:
            if name == "content":
                manifest = await asyncio.to_thread(library.runtime.manifest, pub)
                if not any(
                    e.path == MODEL_PATH and e.role == "runtime" for e in manifest.files
                ):
                    return {
                        "state": "unavailable",
                        "results": [],
                        "next": None,
                        "coverage": "Content index unavailable for this publication. "
                        + COVERAGE,
                    }
                found = await asyncio.wait_for(
                    asyncio.to_thread(
                        library.find_book_content,
                        data["query"],
                        publication_id=pub,
                        book_ids=book_ids,
                        kinds=[data["kind"]] if data.get("kind") else None,
                        limit=20,
                        page=data.get("content_page", 1),
                    ),
                    7,
                )
                next_value = found.get("next_page")
            else:
                found = await asyncio.wait_for(
                    asyncio.to_thread(
                        library.search,
                        data["query"],
                        publication_id=pub,
                        book_ids=book_ids,
                        limit=20,
                        offset=data.get("section_offset", 0),
                    ),
                    7,
                )
                next_value = found.get("next_offset")
            rows, seen = [], set()
            for item in found["results"]:
                c = item["citation"]
                href = reading_link(c)
                # Identity includes the native snapshot/target or the exact section.
                if href in seen:
                    continue
                seen.add(href)
                rows.append(
                    {
                        "href": href,
                        "book_id": c["book_id"],
                        "source_id": c["source_id"],
                        "title": item.get("title")
                        or c.get("section_title")
                        or c["title"],
                        "book": c["title"],
                        "authors": c["authors"],
                        "format": c["format"],
                        "excerpt": item.get("snippet", "")[:500],
                        "kind": item.get("kind"),
                    }
                )
            return {
                "state": "ok",
                "results": rows,
                "next": next_value,
                "cutoff": bool(found.get("search_cutoff")),
                "coverage": COVERAGE,
                "details": found.get("coverage"),
            }
        except Exception:  # noqa: BLE001 - private engine/storage errors must never reach the browser/logs
            return {
                "state": "failed",
                "results": [],
                "next": None,
                "coverage": "This group failed. Retry explicitly; other results remain usable.",
            }

    names = (
        ["content", "section"]
        if data.get("group", "both") == "both"
        else [data["group"]]
    )
    groups = await asyncio.gather(*(group(n) for n in names))
    return JSONResponse(
        {"publication_id": pub, "groups": dict(zip(names, groups, strict=True))}
    )
