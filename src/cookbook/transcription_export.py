"""Deterministic, unapproved EPUB reading copies from saved scan evidence only."""

import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile

from .transcription import snapshot_digest
from .transcription_boundaries import validate_boundaries
from .transcription_review import reviewed_view

VERSION = "scanned-reading-export.v1"
_XHTML = "http://www.w3.org/1999/xhtml"
_EPUB = "http://www.idpf.org/2007/ops"
_NOTICE = (
    "Unapproved reading copy. Recognition, proposed boundaries and source review "
    "are not owner acceptance. Original book bytes remain authoritative. "
    "Layout/header flags and membership may be wrong; missing content is not inferred."
)


def _json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _id(kind, value):
    return kind + "-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _xml_text(text):
    if not isinstance(text, str) or any(
        not (
            c in "\t\n\r"
            or 0x20 <= ord(c) <= 0xD7FF
            or 0xE000 <= ord(c) <= 0xFFFD
            or 0x10000 <= ord(c) <= 0x10FFFF
        )
        for c in text
    ):
        raise ValueError("Text cannot be represented in XML 1.0")
    return text


def _add(parent, tag, text=None, **attributes):
    element = ET.SubElement(parent, tag, attributes)
    if text is not None:
        element.text = _xml_text(text)
    return element


def _serialize(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _document(title, language):
    root = ET.Element(
        "html",
        {"xmlns": _XHTML, "xmlns:epub": _EPUB, "lang": language, "xml:lang": language},
    )
    head = _add(root, "head")
    _add(head, "title", title)
    _add(head, "link", rel="stylesheet", href="style.css", type="text/css")
    return root, _add(root, "body")


def _navigation(snapshot, boundary, view, title, language, reading):
    root, body = _document(title, language)
    _add(body, "h1", "Reading navigation")
    _add(body, "p", _NOTICE)
    toc = _add(body, "nav", **{"epub:type": "toc", "id": "toc"})
    _add(toc, "h2", "Source order")
    listing = _add(toc, "ol")
    _add(_add(listing, "li"), "a", "Source reading and evidence", href="source.xhtml")
    if boundary and boundary["selections"]:
        # Use current membership only when explicitly displaying the review view.
        # Linked spans remain discontiguous; no neighboring lines are pulled in.
        semantic = _add(body, "nav", id="selections")
        _add(semantic, "h2", "Semantic selection proposals")
        _add(
            semantic,
            "p",
            "Candidate labels are identifiers, not reviewed titles or completeness claims. Links select evidence without copying recipe text.",
        )
        choices = _add(semantic, "ol")
        by_line = {line["line_id"]: line for line in view["lines"]}
        by_selection = {selection["id"]: [] for selection in boundary["selections"]}
        for line_id, membership in view["memberships"].items():
            if membership["value"] and len(membership["value"]) == 1:
                by_selection[membership["value"][0]].append(line_id)
        for selection in boundary["selections"]:
            ids = selection["line_ids"]
            if reading == "review":
                ids = by_selection[selection["id"]]
            entry = _add(choices, "li", id=_id("selection", selection["id"]))
            _add(
                entry,
                "p",
                f"{selection['id']} — {selection['kind']} ({selection['state']}; membership {'review overlay' if reading == 'review' else 'boundary proposal'})",
            )
            for reason in selection["reasons"]:
                _add(entry, "p", reason)
            spans = _add(entry, "ol") if ids else None
            for line_id in ids:
                line = by_line[line_id]
                _add(
                    _add(spans, "li"),
                    "a",
                    f"Physical page {line['physical_page']} / line {line_id}",
                    href="source.xhtml#" + _id("line", line_id),
                )
            if not ids:
                _add(
                    entry,
                    "p",
                    "No lines currently assigned in this overlay.",
                )
    if snapshot["pages"]:
        page_nav = _add(body, "nav", **{"epub:type": "page-list", "id": "pages"})
        _add(page_nav, "h2", "Original physical pages")
        pages = _add(page_nav, "ol")
        for page in snapshot["pages"]:
            _add(
                _add(pages, "li"),
                "a",
                f"Physical page {page['physical_page']}",
                href="source.xhtml#" + _id("page", page["id"]),
            )
    return _serialize(root)


def _source(snapshot, boundary, view, title, language, reading):
    root, body = _document(title, language)
    _add(body, "h1", title)
    _add(body, "p", _NOTICE)
    _add(
        body,
        "p",
        f"Reading mode: {reading}. Raw OCR is evidence, not a verified quantity. Quantity corrections are separate annotations, never inferred replacements.",
    )
    _add(
        body,
        "p",
        f"Edition {snapshot['edition']['id']} / source SHA-256 {snapshot['edition']['source_sha256']} / snapshot {view['snapshot_sha256']}",
        **{"class": "evidence"},
    )
    _add(
        _add(body, "p"),
        "a",
        "Exact raw snapshot, revisions and geometry (JSON)",
        href="provenance.json",
    )
    by_line = {line["line_id"]: line for line in view["lines"]}
    markers = {}
    for block in snapshot["blocks"]:
        if block["marker"] and block["line_ids"]:
            markers.setdefault(block["line_ids"][0], set()).add(block["marker"])
    cells = {}
    for table in snapshot["tables"]:
        for cell in table["cells"]:
            for line_id in cell["line_ids"]:
                cells[line_id] = cell
    for page in snapshot["pages"]:
        section = _add(body, "section", id=_id("page", page["id"]))
        _add(
            section,
            "h2",
            f"Physical page {page['physical_page']}",
            **{
                "epub:type": "pagebreak",
                "role": "doc-pagebreak",
                "aria-label": f"Physical page {page['physical_page']}",
            },
        )
        _add(
            section,
            "p",
            f"Page ID {page['id']} / page evidence {page['source_page_sha256']} / render {page['render_sha256']} / recognition {page['recognition']['artifact_sha256']}",
            **{"class": "evidence"},
        )
        for canonical in page["lines"]:
            line_id = canonical["id"]
            line, cell = by_line[line_id], cells.get(line_id)
            article = _add(section, "div", id=_id("line", line_id), **{"class": "line"})
            _add(
                article,
                "p",
                f"Citation: {snapshot['edition']['id']} / physical page {page['physical_page']} / line {line_id}",
                **{"class": "citation"},
            )
            for marker in sorted(markers.get(line_id, ())):
                if not canonical["text"].lstrip().startswith(marker):
                    _add(
                        article,
                        "p",
                        "Separate authored list marker: " + marker,
                        **{"class": "marker"},
                    )
            # Raw text occurs once in the main reading content, even when revised.
            if reading == "review" and line["state"] != "original":
                _add(
                    article,
                    "p",
                    f"Reading overlay ({line['state']}):",
                    **{"class": "status"},
                )
                _add(
                    article,
                    "p",
                    line["text"]
                    if line["text"] is not None
                    else "[UNRESOLVED TEXT — no reading asserted]",
                    **{"class": "reading"},
                )
                _add(article, "p", line["reason"], **{"class": "status"})
                label = "Raw recognition evidence (not the revised reading):"
            else:
                label = "Raw recognition (unreviewed reading):"
                if line["state"] == "unresolved":
                    label = "[UNRESOLVED TEXT] Raw recognition evidence; no resolved reading:"
                elif line["state"] != "original":
                    label = f"Raw recognition; {line['state']} overlay available only in review mode:"
            if cell and view["quantities"][cell["id"]]["state"] == "unresolved":
                label += " [UNRESOLVED QUANTITY — raw OCR is not an asserted value]"
            _add(article, "p", label, **{"class": "status"})
            _add(article, "p", canonical["text"], **{"class": "raw"})
            membership = view["memberships"][line_id]
            if membership["state"] == "unresolved":
                _add(
                    article,
                    "p",
                    "[UNRESOLVED MEMBERSHIP] Recipe ownership is not established.",
                    **{"class": "status"},
                )
            if cell and line_id == cell["line_ids"][0]:
                quantity = view["quantities"][cell["id"]]
                if quantity["state"] == "unresolved":
                    note = "[UNRESOLVED QUANTITY — no value asserted] " + quantity.get(
                        "reason", ""
                    )
                elif reading == "review" and quantity["state"] != "unparsed":
                    note = f"Quantity overlay ({quantity['state']}): {quantity['value']}. {quantity.get('reason', '')}"
                else:
                    note = f"Quantity cell {cell['id']}: {quantity['state']}; raw recognition is not an interpreted amount."
                _add(article, "p", note, **{"class": "quantity"})
                if cell["column_header"] or cell["row_header"]:
                    _add(
                        article,
                        "p",
                        "Model header flags are unverified; ingredient/formulation meaning is not established.",
                        **{"class": "status"},
                    )
    notes = _add(body, "section", id="diagnostics")
    _add(notes, "h2", "Uncertainty and structure diagnostics")
    if not snapshot["diagnostics"]:
        _add(
            notes,
            "p",
            "No recorded adapter diagnostics. This does not establish complete or accurate transcription.",
        )
    for diagnostic in snapshot["diagnostics"]:
        _add(
            notes,
            "p",
            f"{diagnostic['code']} / {diagnostic['page_id'] or 'snapshot'}: {diagnostic['detail']}",
        )
    if boundary:
        for item in boundary["unresolved_elements"]:
            _add(
                notes,
                "p",
                "[UNRESOLVED ELEMENT] "
                + item["block_id"]
                + ": "
                + " ".join(item["reasons"]),
            )
    return _serialize(root)


def export_epub(
    snapshot,
    *,
    boundaries=None,
    revisions=(),
    reading="raw",
    title="Scanned transcription — unapproved reading copy",
    language="en",
) -> bytes:
    """Export saved evidence; corrections require explicit ``reading='review'``.

    No IO, OCR, image rendering, inferred quantities or publication activation.
    Embedded provenance preserves the full canonical snapshot and revision chain.
    """
    identity = snapshot_digest(snapshot)
    if reading not in {"raw", "review"}:
        raise ValueError("reading must be raw or review")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a nonempty string")
    _xml_text(title)
    if not isinstance(language, str) or not re.fullmatch(
        r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language
    ):
        raise ValueError("language must be a language tag")
    if boundaries is not None:
        validate_boundaries(snapshot, boundaries)
    selections = boundaries["selections"] if boundaries else ()
    view = reviewed_view(snapshot, revisions=revisions, selections=selections)
    provenance = {
        "version": VERSION,
        "reading": reading,
        "approval": "unapproved",
        "snapshot_sha256": identity,
        "snapshot": snapshot,
        "boundaries": boundaries,
        "revisions": list(revisions),
        "reviewed_view": view,
    }
    digest = hashlib.sha256(
        _json({**provenance, "title": title, "language": language})
    ).hexdigest()
    package = ET.Element(
        "package",
        {
            "xmlns": "http://www.idpf.org/2007/opf",
            "version": "3.0",
            "unique-identifier": "publication-id",
            "xml:lang": language,
        },
    )
    metadata = _add(
        package, "metadata", **{"xmlns:dc": "http://purl.org/dc/elements/1.1/"}
    )
    _add(metadata, "dc:identifier", "urn:sha256:" + digest, id="publication-id")
    _add(metadata, "dc:title", title)
    _add(metadata, "dc:language", language)
    _add(metadata, "dc:description", _NOTICE)
    _add(metadata, "meta", "1980-01-01T00:00:00Z", property="dcterms:modified")
    manifest = _add(package, "manifest")
    _add(
        manifest,
        "item",
        id="reading",
        href="source.xhtml",
        **{"media-type": "application/xhtml+xml"},
    )
    _add(
        manifest,
        "item",
        id="nav",
        href="nav.xhtml",
        **{"media-type": "application/xhtml+xml", "properties": "nav"},
    )
    _add(manifest, "item", id="css", href="style.css", **{"media-type": "text/css"})
    _add(
        manifest,
        "item",
        id="provenance",
        href="provenance.json",
        **{"media-type": "application/json", "fallback": "reading"},
    )
    spine = _add(package, "spine")
    _add(spine, "itemref", idref="reading")
    container = ET.Element(
        "container",
        {"version": "1.0", "xmlns": "urn:oasis:names:tc:opendocument:xmlns:container"},
    )
    _add(
        _add(container, "rootfiles"),
        "rootfile",
        **{
            "full-path": "EPUB/package.opf",
            "media-type": "application/oebps-package+xml",
        },
    )
    files = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": _serialize(container),
        "EPUB/package.opf": _serialize(package),
        "EPUB/nav.xhtml": _navigation(
            snapshot, boundaries, view, title, language, reading
        ),
        "EPUB/source.xhtml": _source(
            snapshot, boundaries, view, title, language, reading
        ),
        "EPUB/provenance.json": _json(provenance),
        "EPUB/style.css": b"body{font-family:serif;max-width:48em;margin:2em auto;padding:0 1em}.line{margin:1em 0;border-top:1px solid #ccc}.raw,.reading{white-space:pre-wrap}.citation,.evidence,.status,.quantity{font-family:sans-serif;font-size:.85em;overflow-wrap:anywhere}.status,.quantity{color:#654000}",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return output.getvalue()
