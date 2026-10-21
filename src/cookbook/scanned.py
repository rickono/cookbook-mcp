"""scanned-candidate.v1: shape validator and pure import for agent-transcribed scanned PDFs.

A candidate is the frozen output of the offline reader pipeline for one PDF: one row per
physical page, the authored sections, crop quantity reviews, unresolved items and the
reader-vote corrections, bound by ``candidate.json`` (schema:
docs/schemas/scanned-candidate.v1.schema.json). The import turns a candidate into library
units (page units first, then section units) without reading the PDF, rendering, OCR or
model calls. Unresolved content becomes an inline ``[unresolved <id>: <code>]`` marker; crop
readings never enter the library.

Standard library plus ``storage``/``reports`` only, so the reader pipeline can import the
validator without the extraction stack.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .reports import check_region, squash
from .storage import IntegrityError, canonical

VERSION = "scanned-candidate.v1"
SUMMARY_VERSION = "transcription-summary.v1"
SUMMARY_PATH = "quality/transcription-summary.json"
REGISTRY_VERSION = "scanned-registry.v1"
INVENTORY = "quality/scanned"
CANDIDATE = "candidate.json"
FILES = (
    "pages.jsonl",
    "sections.jsonl",
    "quantity-review.jsonl",
    "unresolved.jsonl",
    "vote-corrections.jsonl",
)
PROVENANCE = "transcription"
LABEL = "agent transcription, unapproved"
PAGE_STATUSES = ("transcribed", "blank", "failed")
SECTION_KINDS = (
    "chapter",
    "recipe",
    "passage",
    "technique",
    "reference_entry",
    "contents",
    "index",
    "frontmatter",
)
PART_KINDS = (
    "title",
    "headnote",
    "ingredients",
    "instructions",
    "table",
    "note",
    "variation",
    "assembly",
    "heading",
    "text",
    "menu",
    "timeline",
    "index_entries",
    "contents",
    "caption",
    "footer",
    "graphic",
)
UNRESOLVED_FIELDS = ("amount", "ownership", "other")
UNRESOLVED_CODES = ("amount", "failed_page", "label", "other")
# Parts that are not authored section content: running heads/folios and image-only parts.
NOT_READ = ("footer", "graphic")
_HEX = re.compile(r"[0-9a-f]{64}")


class CandidateError(IntegrityError):
    """A scanned candidate that does not satisfy scanned-candidate.v1."""


def ident(*parts):
    """Same identity function as extract.ident, without importing the extraction stack."""
    return hashlib.sha256(canonical(list(parts))).hexdigest()[:32]


def page_unit_id(source_id, physical_page):
    return ident(source_id, "scanned-page", physical_page)


def section_unit_id(source_id, section_id):
    return ident(source_id, "scanned-section", section_id)


def marker(row):
    return f"[unresolved {row['id']}: {row['code']}]"


# -- parsing and shape checks ---------------------------------------------------------------


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise CandidateError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def _constant(name):
    raise CandidateError(f"non-finite number {name}")


def _json(data, where):
    try:
        return json.loads(
            data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (UnicodeDecodeError, ValueError) as e:
        raise CandidateError(f"{where}: invalid JSON") from e


def _jsonl(data, where):
    if data and not data.endswith(b"\n"):
        raise CandidateError(f"{where}: must end with a newline")
    rows = []
    for n, line in enumerate(data.split(b"\n")[:-1] if data else [], 1):
        row = _json(line, f"{where}:{n}")
        if not isinstance(row, dict):
            raise CandidateError(f"{where}:{n}: row must be an object")
        rows.append(row)
    return rows


def _keys(row, where, required, optional=()):
    if not isinstance(row, dict):
        raise CandidateError(f"{where}: must be an object")
    missing = set(required) - set(row)
    extra = set(row) - set(required) - set(optional)
    if missing or extra:
        raise CandidateError(
            f"{where}: missing {sorted(missing)} unexpected {sorted(extra)}"
        )


def _int(value, where, low=None, high=None):
    if not isinstance(value, int) or isinstance(value, bool):
        raise CandidateError(f"{where}: must be an integer")
    if (low is not None and value < low) or (high is not None and value > high):
        raise CandidateError(f"{where}: out of range")
    return value


def _str(value, where, *, null=False, empty=False):
    if value is None and null:
        return value
    if not isinstance(value, str) or (not empty and not value):
        raise CandidateError(
            f"{where}: must be a {'' if empty else 'non-empty '}string"
        )
    return value


def _hex(value, where, *, null=False):
    if value is None and null:
        return value
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise CandidateError(f"{where}: must be a lowercase sha256 hex digest")
    return value


def _strs(value, where, *, unique=False):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CandidateError(f"{where}: must be a list of strings")
    if unique and len(set(value)) != len(value):
        raise CandidateError(f"{where}: repeated values")
    return value


def _enum(value, where, allowed):
    if value not in allowed:
        raise CandidateError(f"{where}: must be one of {list(allowed)}")
    return value


def _box(value, where):
    try:
        box = check_region(value)
    except IntegrityError as e:
        raise CandidateError(f"{where}: {e}") from e
    if box is None:
        raise CandidateError(f"{where}: box required")
    return box


def _unique(rows, where):
    ids = {}
    for n, row in enumerate(rows, 1):
        rid = _str(row.get("id"), f"{where}:{n}.id")
        if rid in ids:
            raise CandidateError(f"{where}: repeated id {rid!r}")
        ids[rid] = row
    return ids


CANDIDATE_KEYS = (
    "version",
    "book_id",
    "source",
    "config_id",
    "reader",
    "assembler",
    "prompts_sha256",
    "code_sha256",
    "repo_head",
    "coverage",
    "counts",
    "approval",
    "files",
)
PAGE_KEYS = (
    "physical_page",
    "status",
    "text",
    "text_sha256",
    "image_sha256",
    "printed_page",
    "section_ids",
    "unresolved_ids",
    "page_reader",
    "vote_correction_ids",
    "blank_evidence",
)
PAGE_OPTIONAL = ()
BLANK_EVIDENCE_KEYS = ("rule", "attempts", "page_read_errors")
BLANK_RULE = "page_read_empty_response"
EMPTY_RESPONSE = "empty response"
SECTION_KEYS = (
    "id",
    "kind",
    "title",
    "physical_pages",
    "printed_pages",
    "parts",
    "references",
)
SECTION_OPTIONAL = ("status",)
PART_KEYS = ("kind", "source_page", "text", "description", "unresolved_ids")
REFERENCE_KEYS = (
    "source_page",
    "label",
    "printed_target",
    "target_section_id",
    "scope",
)
REVIEW_KEYS = (
    "id",
    "physical_page",
    "box",
    "section_ids",
    "crop_sha256",
    "fields_reviewed",
    "remaining_uncertainty",
    "readers",
)
UNRESOLVED_KEYS = (
    "id",
    "section_id",
    "physical_page",
    "field",
    "code",
    "reason",
    "source_fragment",
    "box",
    "review_id",
    "crop_readings",
)
UNRESOLVED_OPTIONAL = ("span",)
CORRECTION_KEYS = ("id", "physical_page")


def _check_candidate(c, files, source_sha256, physical_pages):
    _keys(c, CANDIDATE, CANDIDATE_KEYS)
    if c["version"] != VERSION:
        raise CandidateError("unsupported candidate version")
    _int(c["book_id"], "book_id")
    _keys(c["source"], "source", ("sha256", "format", "physical_pages"))
    if c["source"]["format"] != "PDF":
        raise CandidateError("source.format must be PDF")
    if _hex(c["source"]["sha256"], "source.sha256") != source_sha256:
        raise CandidateError("candidate is for a different source")
    if (
        _int(c["source"]["physical_pages"], "source.physical_pages", 1)
        != physical_pages
    ):
        raise CandidateError("candidate page count does not match the source")
    _str(c["config_id"], "config_id")
    _keys(c["reader"], "reader", ("spec", "samples", "sample_labels", "fallback"))
    _str(c["reader"]["spec"], "reader.spec")
    samples = _int(c["reader"]["samples"], "reader.samples", 1)
    if len(_strs(c["reader"]["sample_labels"], "reader.sample_labels")) != samples:
        raise CandidateError("reader.sample_labels must have one label per sample")
    _str(c["reader"]["fallback"], "reader.fallback", null=True)
    _str(c["assembler"], "assembler")
    _keys(
        c["prompts_sha256"], "prompts_sha256", ("page", "region", "crop", "sectioning")
    )
    for k, v in c["prompts_sha256"].items():
        _hex(v, f"prompts_sha256.{k}")
    _hex(c["code_sha256"], "code_sha256")
    _str(c["repo_head"], "repo_head", null=True)
    _keys(c["coverage"], "coverage", ("pages_total", "transcribed", "blank", "failed"))
    for k, v in c["coverage"].items():
        _int(v, f"coverage.{k}", 0)
    _keys(c["counts"], "counts", ("sections", "quantity_reviews", "unresolved"))
    for k, v in c["counts"].items():
        _int(v, f"counts.{k}", 0)
    if c["approval"] != "unapproved":
        raise CandidateError("approval must be unapproved")
    _keys(c["files"], "files", FILES)
    for name in FILES:
        entry = c["files"][name]
        _keys(entry, f"files.{name}", ("sha256", "bytes"))
        data = files[name]
        if _hex(entry["sha256"], f"files.{name}.sha256") != hashlib.sha256(
            data
        ).hexdigest() or _int(entry["bytes"], f"files.{name}.bytes", 0) != len(data):
            raise CandidateError(f"{name} does not match candidate.json")


def validate(files, *, source_sha256, physical_pages):
    """Check a candidate's shape and internal references; returns the parsed candidate.

    ``files`` maps each contract file name to its bytes. Binding is by the source's
    sha256 and physical page count; ``book_id`` is informational.
    """
    if not isinstance(files, dict) or set(files) != {CANDIDATE, *FILES}:
        raise CandidateError(f"candidate must be exactly {[CANDIDATE, *FILES]}")
    c = _json(files[CANDIDATE], CANDIDATE)
    _check_candidate(c, files, source_sha256, physical_pages)
    pages = _jsonl(files["pages.jsonl"], "pages")
    sections = _jsonl(files["sections.jsonl"], "sections")
    reviews = _jsonl(files["quantity-review.jsonl"], "quantity-review")
    unresolved = _jsonl(files["unresolved.jsonl"], "unresolved")
    corrections = _jsonl(files["vote-corrections.jsonl"], "vote-corrections")
    n_pages = physical_pages

    def page_no(value, where):
        return _int(value, where, 1, n_pages)

    for n, row in enumerate(corrections, 1):
        _keys(
            row,
            f"vote-corrections:{n}",
            CORRECTION_KEYS,
            set(row) - {"id", "physical_page"},
        )
        page_no(row["physical_page"], f"vote-corrections:{n}.physical_page")
    correction_ids = _unique(corrections, "vote-corrections")

    section_ids = _unique(sections, "sections")
    for sid, s in section_ids.items():
        w = f"sections[{sid}]"
        _keys(s, w, SECTION_KEYS, SECTION_OPTIONAL)
        _enum(s["kind"], f"{w}.kind", SECTION_KINDS)
        _str(s["title"], f"{w}.title", null=True)
        spages = s["physical_pages"]
        if not isinstance(spages, list) or not spages:
            raise CandidateError(f"{w}.physical_pages must be a non-empty list")
        for p in spages:
            page_no(p, f"{w}.physical_pages")
        if spages != sorted(set(spages)):
            raise CandidateError(f"{w}.physical_pages must be ascending and unique")
        printed = s["printed_pages"]
        if not isinstance(printed, list) or len(printed) != len(spages):
            raise CandidateError(f"{w}.printed_pages must match physical_pages")
        for v in printed:
            _str(v, f"{w}.printed_pages", null=True)
        if s.get("status") is not None:
            _str(s["status"], f"{w}.status")  # untrusted: the import derives status
        if not isinstance(s["parts"], list) or not s["parts"]:
            raise CandidateError(f"{w}.parts must be a non-empty list")
        for k, part in enumerate(s["parts"]):
            pw = f"{w}.parts[{k}]"
            _keys(part, pw, PART_KEYS)
            kind = _enum(part["kind"], f"{pw}.kind", PART_KINDS)
            if page_no(part["source_page"], f"{pw}.source_page") not in spages:
                raise CandidateError(
                    f"{pw}.source_page is not one of the section's pages"
                )
            _str(part["text"], f"{pw}.text", null=True, empty=True)
            if (part["text"] is None) != (kind == "graphic"):
                raise CandidateError(f"{pw}: only graphic parts have no text")
            _str(part["description"], f"{pw}.description", null=True)
            _strs(part["unresolved_ids"], f"{pw}.unresolved_ids", unique=True)
        if not isinstance(s["references"], list):
            raise CandidateError(f"{w}.references must be a list")
        for k, ref in enumerate(s["references"]):
            rw = f"{w}.references[{k}]"
            _keys(ref, rw, REFERENCE_KEYS)
            if page_no(ref["source_page"], f"{rw}.source_page") not in spages:
                raise CandidateError(
                    f"{rw}.source_page is not one of the section's pages"
                )
            _str(ref["label"], f"{rw}.label", null=True)
            _str(ref["printed_target"], f"{rw}.printed_target", null=True)
            target = _str(
                ref["target_section_id"], f"{rw}.target_section_id", null=True
            )
            if target is not None and target not in section_ids:
                raise CandidateError(f"{rw}.target_section_id does not resolve")
            _str(ref["scope"], f"{rw}.scope")

    def section_on(sid, page, where):
        if sid not in section_ids:
            raise CandidateError(f"{where}: unknown section {sid!r}")
        if page not in section_ids[sid]["physical_pages"]:
            raise CandidateError(f"{where}: section {sid!r} is not on page {page}")

    review_ids = _unique(reviews, "quantity-review")
    for rid, r in review_ids.items():
        w = f"quantity-review[{rid}]"
        _keys(r, w, REVIEW_KEYS)
        page_no(r["physical_page"], f"{w}.physical_page")
        _box(r["box"], f"{w}.box")
        for sid in _strs(r["section_ids"], f"{w}.section_ids", unique=True):
            section_on(sid, r["physical_page"], f"{w}.section_ids")
        _hex(r["crop_sha256"], f"{w}.crop_sha256")
        _strs(r["fields_reviewed"], f"{w}.fields_reviewed")
        _strs(r["remaining_uncertainty"], f"{w}.remaining_uncertainty")
        _strs(r["readers"], f"{w}.readers")

    unresolved_ids = _unique(unresolved, "unresolved")
    for uid, u in unresolved_ids.items():
        w = f"unresolved[{uid}]"
        _keys(u, w, UNRESOLVED_KEYS, UNRESOLVED_OPTIONAL)
        page = page_no(u["physical_page"], f"{w}.physical_page")
        if u["section_id"] is not None:
            section_on(
                _str(u["section_id"], f"{w}.section_id"), page, f"{w}.section_id"
            )
        _enum(u["field"], f"{w}.field", UNRESOLVED_FIELDS)
        _enum(u["code"], f"{w}.code", UNRESOLVED_CODES)
        _str(u["reason"], f"{w}.reason")
        fragment = _str(u["source_fragment"], f"{w}.source_fragment", null=True)
        if "span" in u:
            span = _str(u["span"], f"{w}.span")
            if fragment is None or span not in fragment:
                raise CandidateError(f"{w}.span must occur in source_fragment")
        _box(u["box"], f"{w}.box")
        if u["review_id"] is not None:
            review = review_ids.get(u["review_id"])
            if review is None or review["physical_page"] != page:
                raise CandidateError(f"{w}.review_id does not resolve on its page")
        _strs(u["crop_readings"], f"{w}.crop_readings")

    for s in sections:
        for k, part in enumerate(s["parts"]):
            for uid in part["unresolved_ids"]:
                u = unresolved_ids.get(uid)
                if u is None or u["physical_page"] != part["source_page"]:
                    raise CandidateError(
                        f"sections[{s['id']}].parts[{k}]: unresolved {uid!r} not on the part's page"
                    )
                if u["section_id"] not in (None, s["id"]):
                    raise CandidateError(
                        f"sections[{s['id']}].parts[{k}]: unresolved {uid!r} belongs to another section"
                    )

    if [p.get("physical_page") for p in pages] != list(range(1, n_pages + 1)):
        raise CandidateError(
            "pages must be exactly 1..N in order, none missing or repeated"
        )
    for p in pages:
        n = p["physical_page"]
        w = f"pages[{n}]"
        _keys(p, w, PAGE_KEYS, PAGE_OPTIONAL)
        status = _enum(p["status"], f"{w}.status", PAGE_STATUSES)
        text = _str(p["text"], f"{w}.text", empty=True)
        if (
            _hex(p["text_sha256"], f"{w}.text_sha256")
            != hashlib.sha256(text.encode()).hexdigest()
        ):
            raise CandidateError(f"{w}.text_sha256 does not match the text")
        _hex(p["image_sha256"], f"{w}.image_sha256")
        _str(p["printed_page"], f"{w}.printed_page", null=True)
        _str(p["page_reader"], f"{w}.page_reader", null=True)
        if (status == "transcribed") != bool(text.strip()):
            raise CandidateError(f"{w}: only transcribed pages have text")
        evidence = p["blank_evidence"]
        if status != "blank":
            if evidence is not None:
                raise CandidateError(f"{w}: blank_evidence only on blank pages")
        else:
            # Production blank rule: every recorded page-read error was an empty response.
            if evidence is None:
                raise CandidateError(
                    f"{w}: a blank page requires recorded blank_evidence"
                )
            _keys(evidence, f"{w}.blank_evidence", BLANK_EVIDENCE_KEYS)
            if evidence["rule"] != BLANK_RULE:
                raise CandidateError(f"{w}.blank_evidence.rule must be {BLANK_RULE!r}")
            _int(evidence["attempts"], f"{w}.blank_evidence.attempts", 1)
            errors = _strs(
                evidence["page_read_errors"], f"{w}.blank_evidence.page_read_errors"
            )
            if not errors or any(e != EMPTY_RESPONSE for e in errors):
                raise CandidateError(
                    f"{w}.blank_evidence: page-read errors must all be empty responses"
                )
        on_page = {sid for sid, s in section_ids.items() if n in s["physical_pages"]}
        if set(_strs(p["section_ids"], f"{w}.section_ids", unique=True)) != on_page:
            raise CandidateError(f"{w}.section_ids do not match the sections")
        rows_here = {
            uid for uid, u in unresolved_ids.items() if u["physical_page"] == n
        }
        if (
            set(_strs(p["unresolved_ids"], f"{w}.unresolved_ids", unique=True))
            != rows_here
        ):
            raise CandidateError(f"{w}.unresolved_ids do not match the unresolved rows")
        failed_rows = {
            uid for uid in rows_here if unresolved_ids[uid]["code"] == "failed_page"
        }
        if (status == "failed") != bool(failed_rows):
            raise CandidateError(
                f"{w}: a failed page needs exactly a failed_page unresolved row"
            )
        for cid in _strs(
            p["vote_correction_ids"], f"{w}.vote_correction_ids", unique=True
        ):
            if cid not in correction_ids or correction_ids[cid]["physical_page"] != n:
                raise CandidateError(
                    f"{w}.vote_correction_ids do not resolve on the page"
                )

    statuses = [p["status"] for p in pages]
    coverage = {
        "pages_total": n_pages,
        **{s: statuses.count(s) for s in PAGE_STATUSES},
    }
    counts = {
        "sections": len(sections),
        "quantity_reviews": len(reviews),
        "unresolved": len(unresolved),
    }
    if c["coverage"] != coverage:
        raise CandidateError("candidate.json coverage does not match pages")
    if c["counts"] != counts:
        raise CandidateError("candidate.json counts do not match the rows")
    return {
        "candidate": c,
        "pages": pages,
        "sections": sections,
        "quantity-review": reviews,
        "unresolved": unresolved,
        "vote-corrections": corrections,
    }


# -- import ---------------------------------------------------------------------------------


def mark(text, row):
    """Replace the row's uncertain span (or its whole line) with its marker.

    Returns (text, found). Lines match the row's source fragment after whitespace
    normalization. Raw or crop readings are never inserted.
    """
    fragment = row["source_fragment"]
    if fragment is None:
        return text, False
    want = squash(fragment)
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if squash(line) == want]
    if not hits:
        hits = [i for i, line in enumerate(lines) if want and want in squash(line)]
    span = row.get("span")
    for i in hits:
        if span and lines[i].count(span) == 1:
            lines[i] = lines[i].replace(span, marker(row))
        else:
            lines[i] = marker(row)
    return "\n".join(lines), bool(hits)


def _page_text(page, rows):
    text = page["text"]
    for row in rows:
        text, found = mark(text, row)
        if not found:
            text = marker(row) if not text else text + "\n" + marker(row)
    return text


def _section_text(section, rows, explicit):
    """Readable section text with markers; returns (text, ids of rows marked in it)."""
    segments = [
        [part["source_page"], part["text"]]
        for part in section["parts"]
        if part["kind"] not in NOT_READ
    ]
    marked = []
    for row in rows:
        hit = False
        for seg in segments:
            if seg[0] == row["physical_page"]:
                seg[1], found = mark(seg[1], row)
                hit = hit or found
        if not hit and row["id"] in explicit:
            at = max(
                (i for i, seg in enumerate(segments) if seg[0] <= row["physical_page"]),
                default=-1,
            )
            segments.insert(at + 1, [row["physical_page"], marker(row)])
            hit = True
        if hit:
            marked.append(row["id"])
    return "\n\n".join(seg[1] for seg in segments), marked


def _label(c, candidate_sha256):
    return {
        "method": "agent_transcription",
        "approval": "unapproved",
        "description": LABEL,
        "reader": c["reader"]["spec"],
        "samples": c["reader"]["samples"],
        "fallback": c["reader"]["fallback"],
        "assembler": c["assembler"],
        "config_id": c["config_id"],
        "candidate_sha256": candidate_sha256,
    }


def _review_region(r):
    return {
        "state": "crop_reviewed",
        "physical_page": r["physical_page"],
        "box": check_region(r["box"]),
        "review_id": r["id"],
    }


def _unresolved_region(u):
    return {
        "state": "unresolved",
        "physical_page": u["physical_page"],
        "box": check_region(u["box"]),
        "unresolved_id": u["id"],
        "code": u["code"],
        "review_id": u["review_id"],
    }


def import_candidate(files, *, source_id, source_sha256, physical_pages, ledger=None):
    """Validate a candidate and turn it into library units, a TOC and a summary entry.

    ``ledger`` is the future correction ledger (#51). It is accepted and nothing from it
    is applied yet; the summary's correction lists stay empty.
    """
    del ledger  # reserved: corrections are applied by a later ticket
    v = validate(files, source_sha256=source_sha256, physical_pages=physical_pages)
    c = v["candidate"]
    candidate_sha256 = hashlib.sha256(files[CANDIDATE]).hexdigest()
    label = _label(c, candidate_sha256)
    rows_on = {}
    for u in v["unresolved"]:
        rows_on.setdefault(u["physical_page"], []).append(u)
    reviews_on = {}
    for r in v["quantity-review"]:
        reviews_on.setdefault(r["physical_page"], []).append(r)
    covered = {p for s in v["sections"] for p in s["physical_pages"]}
    unit_of = {s["id"]: section_unit_id(source_id, s["id"]) for s in v["sections"]}

    units = []
    for page in v["pages"]:
        n = page["physical_page"]
        rows = rows_on.get(n, [])
        units.append(
            {
                "id": page_unit_id(source_id, n),
                "title": f"Page {n}",
                "text": _page_text(page, rows),
                "locator": {
                    "kind": "page",
                    "physical_page": n,
                    "printed_page_unverified": page["printed_page"],
                    "status": page["status"],
                    "section_ids": sorted(unit_of[s] for s in page["section_ids"]),
                },
                "provenance": PROVENANCE,
                "kind": "page",
                "images": [],
                "searchable": n not in covered,
                "transcription": {
                    "label": label,
                    "check_regions": [_review_region(r) for r in reviews_on.get(n, [])]
                    + [_unresolved_region(u) for u in rows],
                    "corrections": [],
                },
            }
        )
    toc = []
    for s in v["sections"]:
        pages = s["physical_pages"]
        rows = [u for p in pages for u in rows_on.get(p, [])]
        explicit = {u["id"] for u in rows if u["section_id"] == s["id"]}
        explicit |= {uid for part in s["parts"] for uid in part["unresolved_ids"]}
        explicit |= {u["id"] for u in rows if u["code"] == "failed_page"}
        text, marked = _section_text(s, rows, explicit)
        marked_rows = [u for u in rows if u["id"] in marked]
        title = s["title"] or f"Untitled {s['kind'].replace('_', ' ')}"
        unit = unit_of[s["id"]]
        units.append(
            {
                "id": unit,
                "title": title,
                "text": text,
                "locator": {
                    "kind": "scanned-section",
                    "physical_pages": pages,
                    "printed_pages_unverified": s["printed_pages"],
                    "status": "has_unresolved" if marked else "complete_in_book",
                    "unresolved_ids": marked,
                    "references": [
                        {
                            "source_page": r["source_page"],
                            "label": r["label"],
                            "printed_target_unverified": r["printed_target"],
                            "target_section_id": unit_of.get(r["target_section_id"]),
                            "scope": r["scope"],
                        }
                        for r in s["references"]
                    ],
                },
                "provenance": PROVENANCE,
                "kind": s["kind"],
                "images": [],
                "searchable": True,
                "transcription": {
                    "label": label,
                    "check_regions": [
                        _review_region(r)
                        for p in pages
                        for r in reviews_on.get(p, [])
                        if s["id"] in r["section_ids"]
                    ]
                    + [_unresolved_region(u) for u in marked_rows],
                    "corrections": [],
                },
            }
        )
        toc.append(
            {
                "title": title,
                "depth": 0,
                "kind": s["kind"],
                "section_id": unit,
                "physical_page": pages[0],
            }
        )
    coverage = c["coverage"]
    summary = {
        "source_id": source_id,
        "source_sha256": source_sha256,
        "candidate_sha256": candidate_sha256,
        "config_id": c["config_id"],
        "reader": c["reader"]["spec"],
        "samples": c["reader"]["samples"],
        "fallback": c["reader"]["fallback"],
        "assembler": c["assembler"],
        "pages_total": coverage["pages_total"],
        "coverage": {k: coverage[k] for k in PAGE_STATUSES},
        "sections": c["counts"]["sections"],
        "quantity_reviews": c["counts"]["quantity_reviews"],
        "unresolved": c["counts"]["unresolved"],
        "corrections": {"applied": [], "stale": [], "ambiguous": []},
    }
    return {
        "units": units,
        "toc": toc,
        "summary": summary,
        "candidate_sha256": candidate_sha256,
    }


# -- files on disk --------------------------------------------------------------------------


def read_candidate(directory: Path):
    """The contract files from a candidate directory; nothing else in it is read."""
    directory = Path(directory)
    files = {}
    for name in (CANDIDATE, *FILES):
        p = directory / name
        if p.is_symlink() or not p.is_file():
            raise CandidateError(f"candidate file missing: {name}")
        files[name] = p.read_bytes()
    return files


def read_registry(path: Path):
    """scanned-registry.v1: {version, sources: [{source_sha256, physical_pages, candidate}]}.

    Returns {source_sha256: {"physical_pages": int, "candidate": Path}}; relative
    candidate paths resolve against the registry's directory.
    """
    path = Path(path)
    data = _json(path.read_bytes(), str(path))
    _keys(data, "registry", ("version", "sources"))
    if data["version"] != REGISTRY_VERSION or not isinstance(data["sources"], list):
        raise CandidateError("unsupported scanned registry")
    out = {}
    for n, row in enumerate(data["sources"], 1):
        w = f"registry.sources[{n}]"
        _keys(row, w, ("source_sha256", "physical_pages", "candidate"))
        sha = _hex(row["source_sha256"], f"{w}.source_sha256")
        if sha in out:
            raise CandidateError(f"{w}: source registered twice")
        out[sha] = {
            "physical_pages": _int(row["physical_pages"], f"{w}.physical_pages", 1),
            "candidate": (
                path.parent / _str(row["candidate"], f"{w}.candidate")
            ).resolve(),
        }
    return out
