"""Conservative same-edition resolution shared by updates and saved locations.

A source key is an identifier digest, never text or authority. Ambiguity, changed
native snapshots, and missing source evidence fail closed. No fuzzy matching.
"""

import hashlib
import json
from html import escape

from .storage import IntegrityError, canonical


def section_key(row):
    locator = json.loads(row["locator"])
    # These locators contain source positions. Empty/page-list-only locators do
    # not identify a section (several recipes may occupy the same pages).
    if (
        locator.get("kind") == "epub"
        and locator.get("document")
        and locator.get("anchor")
    ):
        return hashlib.sha256(canonical(locator)).hexdigest()
    if locator.get("kind") == "page" and locator.get("physical_page"):
        return hashlib.sha256(canonical(locator)).hexdigest()
    return None


def unique_locator(db, source, key):
    # Compare parsed canonical locators, including differently formatted JSON.
    # SQLite scans the source without materializing section text or all matches.
    db.create_function(
        "reader_source_key", 1, lambda raw: section_key({"locator": raw})
    )
    rows = db.execute(
        "select id from sections where source_id=? and reader_source_key(locator)=? limit 2",
        (source, key),
    ).fetchall()
    return len(rows) == 1


def source_location(library, location):
    """Validate a location and return an identifier-only durable reference.

    #104 may store this value, then call resolve_current when opening it. Native
    cursors and text offsets never migrate across publications; updates restart
    the reliably identified section/target. Same-snapshot targets retain occurrence.
    """
    from .reader_content import read

    loc = {
        k: v
        for k, v in location.items()
        if k
        not in {"cursor", "offset", "related_offset", "contents_offset", "source_key"}
    }
    data = read(library, loc)  # Verify native target/snapshot and source bindings.
    if data["citation"].get("model_snapshot_id"):
        loc["model_snapshot_id"] = data["citation"]["model_snapshot_id"]
    if "section_id" in loc:
        with library.db(loc["publication_id"]) as db:
            row = db.execute(
                "select * from sections where source_id=? and id=?",
                (loc["source_id"], loc["section_id"]),
            ).fetchone()
            key = section_key(row) if row else None
            if key and unique_locator(db, loc["source_id"], key):
                loc["source_key"] = key
    return loc


def resolve_current(library, location):
    """Return available + opaque `at`, or unavailable; never return private text.

    An unavailable old publication can recover only from already retained source
    evidence: source_key for a unique section, or an unchanged native snapshot.
    Never map by title, section ID alone, physical-page overlap or text similarity.
    Storage failures propagate to the existing redacted retry boundary.
    """
    from .reader_content import encode_location, read

    current = library.publication(None)
    try:
        pinned_state = read(library, location)["state"]
    except IntegrityError:
        pinned_state = "unavailable"
    result = {
        "state": "unavailable",
        "current_publication_id": current,
        "at": None,
        "pinned_state": pinned_state,
    }
    loc = {
        k: v
        for k, v in location.items()
        if k not in {"cursor", "offset", "related_offset", "contents_offset"}
    }
    try:
        if "section_id" in loc and not loc.get("source_key"):
            loc = source_location(library, loc)
        candidate = {**loc, "publication_id": current}
        book = library.get_book(current, loc["book_id"])
        if book["citation"]["source_id"] != loc["source_id"]:
            return result
        if "section_id" in loc:
            if not loc.get("source_key"):
                return result
            with library.db(current) as db:
                row = db.execute(
                    "select * from sections where source_id=? and id=?",
                    (loc["source_id"], loc["section_id"]),
                ).fetchone()
                if row is None or section_key(row) != loc["source_key"]:
                    return result
                if not unique_locator(db, loc["source_id"], loc["source_key"]):
                    return result
        elif "target_id" in loc and not loc.get("model_snapshot_id"):
            return result
        data = read(library, candidate)
        if data["state"] == "withheld":
            return result
        return {**result, "state": "available", "at": encode_location(candidate)}
    except IntegrityError:
        return result


def notice_markup(result, publication):
    from .reader_content import anchor

    body = (
        '<aside id="publication-update" role="status" aria-label="Publication update">'
    )
    body += "<p>Reading publication " + escape(publication) + ".</p>"
    if result["current_publication_id"] != publication:
        body += "<p>A newer publication is available. This view remains on its referenced publication while retained.</p>"
        if result["at"]:
            body += anchor(result["at"], "Open current text").replace(
                '">Open', '#text">Open'
            )
        else:
            body += "<p>Current text unavailable at a reliable location in this edition.</p>"
    return body + "</aside>"
