"""Original-book reader and authenticated source bytes. No extraction or rendering."""

import asyncio
import json
import re
import zipfile
from html import escape
from urllib.parse import urlencode

from starlette.background import BackgroundTask
from starlette.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from .book_model import connection
from .reader_content import decode_location, encode_location, page_error, read
from .storage import IntegrityError


def source_file(library, loc):
    pub = library.publication(loc["publication_id"])
    with library.db(pub) as db:
        book = library.book(db, loc["book_id"], loc["source_id"])
        fmt, logical = book["format"], book["original_path"]
    if fmt not in ("PDF", "EPUB"):
        raise IntegrityError("original format unsupported")
    with library.asset_lock:
        handle = library.cached(pub, logical).open("rb")
    try:
        if fmt == "PDF":
            if handle.read(5) != b"%PDF-":
                raise IntegrityError("original PDF unavailable")
        else:
            with zipfile.ZipFile(handle) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 50000
                    or sum(i.file_size for i in entries) > 256 * 1024**2
                    or any(i.file_size > 32 * 1024**2 for i in entries)
                ):
                    raise IntegrityError("EPUB exceeds browser reading budget")
                if (
                    len({i.filename for i in entries}) != len(entries)
                    or archive.read("mimetype") != b"application/epub+zip"
                ):
                    raise IntegrityError("original EPUB unavailable")
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(0)
        return handle, size, fmt
    except Exception:
        handle.close()
        raise


async def source(request, library):
    try:
        if (
            set(request.query_params) != {"at"}
            or len(request.query_params.getlist("at")) != 1
        ):
            raise ValueError()
        loc = decode_location(request.query_params["at"])
    except (ValueError, TypeError, UnicodeError):
        return JSONResponse({"error": "invalid_destination"}, status_code=400)
    try:
        handle, size, fmt = await asyncio.to_thread(source_file, library, loc)
    except (IntegrityError, zipfile.BadZipFile, KeyError):
        return JSONResponse({"error": "original_unavailable"}, status_code=404)
    start, end = 0, size - 1
    ranged = request.headers.get("range")
    if ranged:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", ranged)
        if len(ranged) > 128 or not match or not any(match.groups()):
            handle.close()
            return Response(
                status_code=416, headers={"Content-Range": f"bytes */{size}"}
            )
        left, right = match.groups()
        if left:
            start, end = int(left), min(int(right) if right else end, end)
        else:
            start = max(0, size - int(right))
        if not 0 <= start <= end < size:
            handle.close()
            return Response(
                status_code=416, headers={"Content-Range": f"bytes */{size}"}
            )
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Disposition": "inline",
    }
    if ranged:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if request.method == "HEAD":
        handle.close()
        return Response(
            status_code=206 if ranged else 200,
            headers=headers,
            media_type="application/pdf" if fmt == "PDF" else "application/epub+zip",
        )

    def chunks():
        try:
            handle.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            handle.close()

    return StreamingResponse(
        chunks(),
        media_type="application/pdf" if fmt == "PDF" else "application/epub+zip",
        status_code=206 if ranged else 200,
        headers=headers,
        background=BackgroundTask(handle.close),
    )


def information(library, loc):
    data = read(library, loc, text=False)
    from .reader_updates import resolve_current, source_location

    citation = data["citation"]
    location = source_location(library, loc, _validated=data)
    result = {
        "personal_at": encode_location(location),
        "personal_stable": data["state"] != "withheld"
        and bool(location.get("section_id") or location.get("target_id")),
        "source_location": location,
        "update": resolve_current(library, location, _validated=data),
        "publication_id": citation["publication_id"],
        "source_id": citation["source_id"],
        "format": citation["format"],
        "title": citation["title"],
        "contents": data["contents"],
        "next_contents": data.get("next_contents"),
        "physical_page": 1,
    }
    locator = citation.get("locator", {})
    if locator.get("physical_pages"):
        result["physical_page"] = locator["physical_pages"][0]
    elif locator.get("physical_page"):
        result["physical_page"] = locator["physical_page"]
    if locator.get("kind") == "epub":
        result["epub_document"] = locator["document"]
        result["epub_anchor"] = locator.get("anchor", "")
    elif locator.get("source_parts"):
        part = locator["source_parts"][0]
        result["epub_document"] = part["resource_path"]
        with connection(library.model(loc["publication_id"]).path) as db:
            row = db.execute(
                "select payload from nodes where id=? and document_id=?",
                (part["start"]["node_id"], part["document_id"]),
            ).fetchone()
            occurrence = db.execute(
                "select ordinal from occurrences where id=? and edition_id=? and document_id=?",
                (
                    part.get("reading_occurrence_id"),
                    loc["book_id"],
                    part["document_id"],
                ),
            ).fetchone()
            if occurrence:
                result["epub_occurrence"] = occurrence[0]
            if row:
                node = json.loads(row[0])
                result["epub_anchor"] = node.get("source_attributes", {}).get("id", "")
                result["epub_xpath"] = node.get("source_xpath", "")
    return result


# Viewer code is public and revalidated; fetching it while the page parses lets
# opening overlap with the first source ranges instead of waiting for book.js.
PRELOAD = {
    "PDF": '<link rel="modulepreload" href="/reader/vendor/pdfjs-dist/build/pdf.mjs">'
    '<link rel="modulepreload" href="/reader/vendor/pdfjs-dist/web/pdf_viewer.mjs">',
    "EPUB": '<link rel="modulepreload" href="/reader/epub.js">'
    '<link rel="preload" as="script" href="/reader/vendor/jszip/dist/jszip.min.js">'
    '<link rel="preload" as="script" href="/reader/vendor/epubjs/dist/epub.min.js">',
}


async def deliver(reader, request, library, owner=None, csrf="", *, entry_banner=""):
    at = request.query_params.get("at", "")
    try:
        if (
            set(request.query_params) != {"at"}
            or len(request.query_params.getlist("at")) != 1
        ):
            raise ValueError()
        loc = decode_location(at)
    except (ValueError, TypeError, UnicodeError):
        if request.url.path != "/reader/book-info":
            return page_error(reader, "Invalid reading destination.", 400)
        return JSONResponse({"error": "invalid_destination"}, status_code=400)
    try:
        await asyncio.to_thread(library.publication, loc["publication_id"])
    except IntegrityError:
        return await unavailable(reader, request, library, loc, 410)
    try:
        data = await asyncio.to_thread(information, library, loc)
    except IntegrityError:
        return await unavailable(reader, request, library, loc, 404)
    if request.url.path == "/reader/book-info":
        return JSONResponse(data)
    if data["format"] not in ("PDF", "EPUB"):
        if entry_banner:
            from .reader_content import deliver as text_view

            return await text_view(
                reader, request, library, owner, csrf, entry_banner=entry_banner
            )
        return RedirectResponse(
            "/reader/read?" + urlencode({"at": at}), status_code=303
        )
    from .reader_personal import controls

    personal = controls(data["source_location"], data["personal_stable"])
    update = original_notice(data["update"], loc["publication_id"])
    personal += update.replace(
        'id="publication-update"',
        'id="publication-update" data-view="original" data-at="'
        + data["personal_at"]
        + '"',
    )
    personal += '<script src="/reader/updates.js" defer></script>'
    query = escape(urlencode({"at": at}))
    navigation = "".join(
        '<a href="/reader/book-view?'
        + escape(urlencode({"at": item["at"]}))
        + '">'
        + escape(item["title"])
        + "</a>"
        for item in data["contents"]
        if item.get("at")
    )
    # The opening needs these immediately; /reader/book-info remains for navigation.
    inline = (
        json.dumps(data)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    body = (
        PRELOAD[data["format"]]
        + '<link rel="stylesheet" href="/reader/book.css"><section class="book-view" data-book-at="'
        + escape(at)
        + '"><script type="application/json" data-book-info>'
        + inline
        + "</script>"
        '<header class="book-toolbar"><a href="/reader/catalog">Books</a><details class="book-contents"><summary>Contents</summary><nav aria-label="Book contents">'
        + navigation
        + "</nav></details>"
        + '<details class="book-places"><summary>Places</summary><div>'
        + personal
        + "</div></details>"
        '<span class="book-title">'
        + escape(data["title"])
        + '</span><a aria-label="Search this book" href="/reader/search?'
        + query
        + '">Search</a><a href="/reader/read?'
        + query
        + '">Text view</a></header>'
        + entry_banner
        + '<div class="book-controls"><button type="button" data-book-prev aria-label="Previous page" disabled>← Previous</button><label>Page <input data-book-page type="number" min="1" value="1" inputmode="numeric"></label><span data-book-total></span><button type="button" data-book-next-page aria-label="Next page" disabled>Next →</button><button type="button" data-book-zoom-out aria-label="Zoom out">−</button><button type="button" data-book-zoom-in aria-label="Zoom in">+</button></div>'
        '<p data-book-status role="status">Opening original book…</p><div class="book-stage"><div class="pdf-stage" tabindex="0" aria-label="Original PDF pages" hidden><div class="pdfViewer"></div></div><div class="epub-stage" aria-label="Original EPUB" hidden></div></div>'
        '<noscript><p>Enable JavaScript to read the original here, or use the text view.</p></noscript></section><script src="/reader/book.js" defer></script>'
    )
    return reader.page(body, protected=True)


def original_notice(result, publication):
    from .reader_updates import notice_markup

    return (
        notice_markup(result, publication)
        .replace("/reader/read?", "/reader/book-view?")
        .replace("Open current text", "Open current original")
        .replace('#text"', '"')
    )


async def unavailable(reader, request, library, loc, status):
    if request.url.path == "/reader/book-info":
        return JSONResponse(
            {
                "error": "publication_unavailable"
                if status == 410
                else "source_location_unavailable"
            },
            status_code=status,
        )
    from .reader_updates import resolve_current

    result = await asyncio.to_thread(resolve_current, library, loc)
    message = (
        "Publication unavailable or retired. This exact reading link cannot be opened."
        if status == 410
        else "Source location unavailable. No replacement location was selected."
    )
    return page_error(
        reader, message, status, original_notice(result, loc["publication_id"])
    )
