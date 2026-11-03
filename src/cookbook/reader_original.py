"""Protected originals: identifier-bound selection, existing render limits, raster only."""

import asyncio
import io
import json
from html import escape
from urllib.parse import urlencode

from PIL import Image
from starlette.responses import JSONResponse, Response

from .reader_content import decode_location, read
from .reader_diagnostics import Stage, stage
from .rendering import RenderError
from .storage import IntegrityError

MAX_BYTES = 3_000_000
MAX_PIXELS = 16_000_000


def link(at, **selection):
    return "/reader/original?" + urlencode({"at": at, **selection})


def candidates(library, loc, data, offset=0):
    """Only retained page order or explicit document associations, never a guessed match."""
    locator = data["citation"].get("locator", {})
    pages = locator.get("physical_pages", [])
    if locator.get("kind") == "page":
        pages = [locator["physical_page"]]
    if pages:
        return [
            {"page": p, "label": f"Physical page {p}"}
            for p in pages[offset : offset + 20]
        ], (offset + 20 if offset + 20 < len(pages) else None)
    if data["citation"]["format"] == "EPUB" and loc.get("section_id"):
        result = library.list_images(
            loc["publication_id"],
            loc["book_id"],
            loc["source_id"],
            loc["section_id"],
            offset=offset,
            limit=20,
        )
        return [
            {"image": i["image_id"], "label": i.get("caption") or "EPUB document image"}
            for i in result["images"]
        ], result["next_offset"]
    if data["citation"]["format"] == "EPUB" and loc.get("target_id"):
        # The bounded native read already establishes these source documents and
        # validates snapshot/target/occurrence. Never resolve a browser resource URL.
        documents = [c["resource_path"] for c in locator.get("source_parts", [])]
        if documents:
            pub = library.publication(loc["publication_id"])
            with library.db(pub) as db:
                library.book(db, loc["book_id"], loc["source_id"])
                marks = ",".join("?" for _ in documents)
                rows = db.execute(
                    f"select id,caption from images where source_id=? and document in ({marks}) order by rowid limit 21 offset ?",
                    (loc["source_id"], *documents, offset),
                ).fetchall()
            return [
                {"image": r["id"], "label": r["caption"] or "EPUB document image"}
                for r in rows[:20]
            ], (offset + 20 if len(rows) > 20 else None)
    return [], None


def raster(data):
    """Reject active formats and oversized rasters before browser delivery."""
    if len(data) > MAX_BYTES:
        raise RenderError("image exceeds delivery bounds")
    with Image.open(io.BytesIO(data)) as im:
        if (
            im.format not in {"JPEG", "PNG", "WEBP"}
            or im.width * im.height > MAX_PIXELS
        ):
            raise RenderError("unsupported image")
        mime = Image.MIME[im.format]
        im.verify()
    return mime


async def deliver(reader, request, library):
    q = request.query_params
    at = q.get("at", "")
    try:
        if any(len(q.getlist(k)) != 1 for k in q) or set(q) - {
            "at",
            "back",
            "page",
            "image",
            "region",
            "offset",
        }:
            raise ValueError("invalid selection")
        loc = decode_location(at)
        back = q.get("back")
        if back:
            decode_location(back)
        offset = int(q.get("offset", "0"))
        if not 0 <= offset <= 100000 or ("page" in q and "image" in q):
            raise ValueError("invalid selection")
        page = int(q["page"]) if "page" in q else None
        region = int(q["region"]) if "region" in q else None
        if (page is not None and page < 1) or (region is not None and region < 0):
            raise ValueError("invalid selection")
    except (ValueError, TypeError, UnicodeError):
        return JSONResponse({"error": "invalid_original_destination"}, status_code=400)
    try:
        with stage(Stage.LIBRARY_RESOLVE):
            await asyncio.to_thread(library.publication, loc["publication_id"])
    except IntegrityError:
        return failure(
            reader, at, "Publication unavailable or retired.", 410, back=back
        )
    try:
        data = await asyncio.to_thread(read, library, loc)
        items, more = await asyncio.to_thread(candidates, library, loc, data, offset)
        selected = next(
            (
                i
                for i in items
                if (page is not None and i.get("page") == page)
                or ("image" in q and i.get("image") == q["image"])
            ),
            None,
        )
        if ("page" in q or "image" in q) and selected is None:
            raise IntegrityError("source selection unavailable")
        box = None
        if region is not None:
            regions = data.get("check_regions", [])
            if region >= len(regions) or regions[region]["physical_page"] != page:
                raise IntegrityError("region source mismatch")
            box = regions[region]["box"]
        if request.url.path == "/reader/image":
            if selected is None:
                raise IntegrityError("no image selected")
            args = [loc[k] for k in ("publication_id", "book_id", "source_id")]
            if page is not None:
                _, binary = await asyncio.to_thread(
                    library.get_page, *args, page, edge=1600, region=box
                )
            else:
                _, binary = await asyncio.to_thread(
                    library.get_image, *args, selected["image"]
                )
            return Response(
                binary,
                media_type=raster(binary),
                headers={"Content-Disposition": "inline"},
            )
    except RenderError:
        return failure(
            reader,
            at,
            "Original unavailable within serving limits or renderer busy. Retry explicitly, use the whole page, or return to text.",
            503,
            back=back,
            retry=link(at, **{k: v for k, v in q.items() if k != "at"}),
        )
    except IntegrityError:
        return failure(
            reader,
            at,
            "Original source location unavailable. No replacement was selected.",
            404,
            back=back,
        )
    body = (
        '<link rel="stylesheet" href="/reader/original.css"><div class="original-view"><nav class="reading-crumbs"><a href="/reader/read?'
        + escape(urlencode({"at": at, **({"back": back} if back else {})}))
        + '#text">Return to same text position</a></nav>'
    )
    body += (
        '<header class="page-head"><p class="kicker">From the book</p><h1>Original source</h1><p class="lede">'
        + escape(data["citation"]["title"])
        + "</p></header>"
    )
    body += (
        '<p class="fineprint">Physical page ordinals follow source order. Printed page labels remain unverified.</p>'
        if data["citation"]["format"] != "EPUB"
        else '<p class="fineprint">EPUB images follow retained document associations; these are not verified recipe matches. No facsimile pages or original CSS are promised.</p>'
    )
    body += '<nav class="original-options" aria-label="Originals">'
    for item in items:
        selection = {k: v for k, v in item.items() if k != "label"}
        body += (
            '<a href="'
            + escape(
                link(at, offset=offset, **selection, **({"back": back} if back else {}))
            )
            + '">'
            + escape(item["label"])
            + "</a>"
        )
    if more is not None:
        body += (
            '<a href="'
            + escape(link(at, offset=more, **({"back": back} if back else {})))
            + '">More originals</a>'
        )
    body += "</nav>"
    if selected:
        from .reader_presentation import text_html

        text_state = (
            "Text withheld by current withdrawal or supersession."
            if data["state"] == "withheld"
            else "Partial text; more remains."
            if data["state"] == "partial_text"
            else "End of this text delivery; this does not establish a complete recipe."
        )
        body += (
            '<p class="fineprint">'
            + text_state
            + " Corrections and crop confirmation do not establish approval.</p>"
        )
        body += (
            '<button type="button" data-compare aria-pressed="false">Compare text and original</button><div class="original-layout"><article class="comparison-text" aria-label="Text at originating location">'
            + text_html(data)
            + '</article><section aria-label="Selected original">'
        )
        params = dict(q)
        image_url = "/reader/image?" + urlencode(params)
        body += (
            '<p id="original-status" role="status">Selected original. If it does not display, retry or return to text.</p><img data-original-image src="'
            + escape(image_url)
            + '" alt="'
            + escape(selected["label"])
            + '"><a data-image-retry href="'
            + escape(link(at, **{k: v for k, v in params.items() if k != "at"}))
            + '">Retry selected original</a>'
        )
        if page is not None:
            body += (
                '<a href="'
                + escape(
                    link(
                        at, page=page, offset=offset, **({"back": back} if back else {})
                    )
                )
                + '">Whole page at supported size</a><ol aria-label="Check regions">'
            )
            for n, r in enumerate(data.get("check_regions", [])):
                if r["physical_page"] == page:
                    meaning = {
                        "unresolved": "Unresolved content",
                        "crop_confirmed": "Crop confirmed; not approval",
                    }.get(r.get("state", r.get("status")), "Review state not recorded")
                    body += (
                        '<li><a href="'
                        + escape(
                            link(
                                at,
                                page=page,
                                region=n,
                                offset=offset,
                                **({"back": back} if back else {}),
                            )
                        )
                        + '">Check region '
                        + str(n + 1)
                        + " — "
                        + meaning
                        + "</a><span> Normalized page geometry: "
                        + escape(str(r["box"]))
                        + "</span></li>"
                    )
            body += "</ol>"
        body += '</section></div><script src="/reader/original.js" defer></script>'
    elif not items:
        body += '<p role="status">No supported originals are associated with this location.</p>'
    body += "<details><summary>Source citation</summary><pre>"
    body += (
        escape(json.dumps(data["citation"], ensure_ascii=False, indent=2))
        + "</pre></details>"
    )
    return reader.page(body + "</div>", protected=True, presentation=True)


def failure(reader, at, message, status, *, retry=None, back=None):
    body = (
        '<p role="status">'
        + escape(message)
        + '</p><a href="'
        + escape(link(at, **({"back": back} if back else {})))
        + '">Choose original or whole page</a><a href="/reader/read?'
        + escape(urlencode({"at": at, **({"back": back} if back else {})}))
        + '#text">Return to same text position</a>'
    )
    if retry:
        body += '<a href="' + escape(retry) + '">Retry selected original</a>'
    response = reader.page(body, protected=True, presentation=True)
    response.status_code = status
    return response
