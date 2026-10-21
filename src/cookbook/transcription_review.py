"""Digest-bound review proposals; no IO, OCR, approval, or raw-evidence mutation."""

import hashlib
import json
import re
from copy import deepcopy
from html import escape

from .transcription import snapshot_digest

VERSION = "scanned-review.v1"
_KINDS = {"line_text", "quantity", "membership"}
_STATES = {"proposed", "source_reviewed", "unresolved"}


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _exact(record, keys, label):
    if not isinstance(record, dict) or set(record) != set(keys):
        raise ValueError(f"invalid {label} fields")


def _context(snapshot, selections):
    if not isinstance(selections, (list, tuple)):
        raise ValueError("selections must be a replayable list or tuple")  # noqa: TRY004
    identity = snapshot_digest(snapshot)
    lines, cells, owners, unresolved_owners = {}, {}, {}, set()
    for page in snapshot["pages"]:
        for line in page["lines"]:
            lines[line["id"]] = (page, line)
            owners[line["id"]] = []
    for table in snapshot["tables"]:
        for cell in table["cells"]:
            if cell["id"] in cells:
                raise ValueError("review requires globally unique table cell IDs")
            cells[cell["id"]] = (table, cell)
    selection_ids = set()
    for selection in selections:
        if not isinstance(selection, dict) or not _nonempty(selection.get("id")):
            raise ValueError("invalid selection identity")
        if selection["id"] in selection_ids:
            raise ValueError("duplicate selection identity")
        selection_ids.add(selection["id"])
        selected = selection.get("line_ids")
        if (
            not isinstance(selected, list)
            or any(not isinstance(i, str) for i in selected)
            or len(set(selected)) != len(selected)
        ):
            raise ValueError("invalid selection line IDs")
        for line_id in selected:
            if line_id not in lines:
                raise ValueError("selection references unknown line")
            owners[line_id].append(selection["id"])
            if selection.get("state") == "unresolved":
                unresolved_owners.add(line_id)
    return {
        "snapshot": identity,
        "boundary": _digest(list(selections)),
        "lines": lines,
        "cells": cells,
        "owners": owners,
        "unresolved_owners": unresolved_owners,
        "selection_ids": selection_ids,
        "edition": snapshot["edition"],
    }


def _evidence(context, line_id):
    if line_id not in context["lines"]:
        raise ValueError("evidence references unknown line")
    page, line = context["lines"][line_id]
    return {
        "edition_id": context["edition"]["id"],
        "source_sha256": context["edition"]["source_sha256"],
        "page_id": page["id"],
        "physical_page": page["physical_page"],
        "source_page_sha256": page["source_page_sha256"],
        "render_sha256": page["render_sha256"],
        "recognition_sha256": page["recognition"]["artifact_sha256"],
        "line_id": line_id,
        "text_sha256": _text_digest(line["text"]),
        "polygon": deepcopy(line["polygon"]),
    }


def source_evidence(snapshot, line_ids):
    """Return exact immutable-source bindings for explicitly inspected lines."""
    context = _context(snapshot, ())
    if not isinstance(line_ids, (list, tuple)) or not line_ids:
        raise ValueError("evidence needs at least one line")
    if any(not isinstance(i, str) for i in line_ids) or len(set(line_ids)) != len(
        line_ids
    ):
        raise ValueError("duplicate evidence line")
    return [_evidence(context, line_id) for line_id in line_ids]


def _target_lines(context, kind, target_id):
    if not isinstance(kind, str) or kind not in _KINDS or not _nonempty(target_id):
        raise ValueError("invalid correction target")
    if kind == "quantity":
        if target_id not in context["cells"]:
            raise ValueError("unknown quantity cell")
        result = context["cells"][target_id][1]["line_ids"]
        if not result:
            raise ValueError("quantity cell lacks canonical line evidence")
        return result
    if target_id not in context["lines"]:
        raise ValueError("unknown correction line")
    return [target_id]


def _initial(context, kind, target_id):
    selected = _target_lines(context, kind, target_id)
    if kind == "line_text":
        return {"value": context["lines"][target_id][1]["text"], "state": "original"}
    if kind == "quantity":
        return {
            "value": "\n".join(context["lines"][i][1]["text"] for i in selected),
            "state": "unparsed",
        }
    owners = context["owners"][target_id]
    if target_id in context["unresolved_owners"]:
        return {"value": None, "state": "unresolved"}
    return {"value": owners or None, "state": "candidate" if owners else "unresolved"}


def _validate_change(context, change, values):
    _exact(
        change,
        ("kind", "target_id", "before_sha256", "state", "value", "reason", "evidence"),
        "change",
    )
    kind, target = change["kind"], change["target_id"]
    required = set(_target_lines(context, kind, target))
    if (
        not isinstance(change["state"], str)
        or change["state"] not in _STATES
        or not _nonempty(change["reason"])
    ):
        raise ValueError("invalid review state or missing reason")
    value = change["value"]
    if change["state"] == "unresolved":
        if value is not None:
            raise ValueError("unresolved content must have null value")
    elif kind == "membership":
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], str)
            or value[0] not in context["selection_ids"]
        ):
            raise ValueError("membership must reference one existing selection")
    elif not _nonempty(value):
        raise ValueError("resolved text or quantity needs a reading")
    evidence = change["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("missing source evidence")
    seen = set()
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("line_id"), str):
            raise ValueError("invalid source evidence")  # noqa: TRY004 - public validation contract
        line_id = item["line_id"]
        if line_id in seen:
            raise ValueError("duplicate source evidence")
        seen.add(line_id)
        if _digest(item) != _digest(_evidence(context, line_id)):
            raise ValueError("stale source, text, render or geometry evidence")
    if not required <= seen:
        raise ValueError("evidence omits correction target lines")
    key = (kind, target)
    current = values.get(key, _initial(context, kind, target))
    if change["before_sha256"] != _digest(
        {"value": current["value"], "state": current["state"]}
    ):
        raise ValueError("stale correction base reading")
    values[key] = {"value": deepcopy(value), "state": change["state"]}


def _replay(context, revisions):
    if not isinstance(revisions, (list, tuple)):
        raise ValueError("revisions must be a replayable list or tuple")  # noqa: TRY004
    values, predecessor = {}, None
    for revision in revisions:
        _exact(
            revision,
            (
                "version",
                "snapshot_sha256",
                "boundary_sha256",
                "predecessor",
                "reviewer",
                "changes",
                "id",
            ),
            "revision",
        )
        if (
            revision["version"] != VERSION
            or revision["snapshot_sha256"] != context["snapshot"]
            or revision["boundary_sha256"] != context["boundary"]
            or revision["predecessor"] != predecessor
        ):
            raise ValueError(
                "stale snapshot, selection context or revision predecessor"
            )
        _exact(revision["reviewer"], ("kind", "id"), "reviewer")
        if (
            not isinstance(revision["reviewer"]["kind"], str)
            or revision["reviewer"]["kind"] not in {"agent", "human"}
            or not _nonempty(revision["reviewer"]["id"])
        ):
            raise ValueError("invalid reviewer identity")
        payload = {key: value for key, value in revision.items() if key != "id"}
        if revision["id"] != _digest(payload):
            raise ValueError("tampered revision identity")
        changes = revision["changes"]
        if not isinstance(changes, list) or not changes:
            raise ValueError("revision needs changes")
        seen = set()
        for change in changes:
            _validate_change(context, change, values)
            key = (change["kind"], change["target_id"])
            if key in seen:
                raise ValueError("duplicate or conflicting correction target")
            seen.add(key)
            values[key].update(reason=change["reason"], revision_id=revision["id"])
        predecessor = revision["id"]
    return values, predecessor


def target_digest(snapshot, kind, target_id, *, revisions=(), selections=()):
    """Bind a change to the current value/state, not just the original OCR."""
    context = _context(snapshot, selections)
    values, _ = _replay(context, revisions)
    current = values.get((kind, target_id), _initial(context, kind, target_id))
    return _digest({"value": current["value"], "state": current["state"]})


def make_revision(snapshot, changes, *, reviewer, revisions=(), selections=()):
    """Create a new checked revision; predecessor records remain byte-identical."""
    context = _context(snapshot, selections)
    _, predecessor = _replay(context, revisions)
    revision = {
        "version": VERSION,
        "snapshot_sha256": context["snapshot"],
        "boundary_sha256": context["boundary"],
        "predecessor": predecessor,
        "reviewer": deepcopy(reviewer),
        "changes": deepcopy(list(changes)),
    }
    revision["id"] = _digest(revision)
    _replay(context, [*revisions, revision])
    return revision


def reviewed_view(snapshot, *, revisions=(), selections=()):
    """Return a separate reading overlay with raw OCR and uncertainty exposed."""
    context = _context(snapshot, selections)
    values, predecessor = _replay(context, revisions)
    result = {
        "snapshot_sha256": context["snapshot"],
        "boundary_sha256": context["boundary"],
        "revision_id": predecessor,
        "lines": [],
        "quantities": {},
        "memberships": {},
    }
    for line_id, (page, line) in context["lines"].items():
        current = values.get(
            ("line_text", line_id), _initial(context, "line_text", line_id)
        )
        result["lines"].append(
            {
                "line_id": line_id,
                "page_id": page["id"],
                "physical_page": page["physical_page"],
                "raw_text": line["text"],
                "text": current["value"],
                "state": current["state"],
                "reason": current.get("reason"),
                "revision_id": current.get("revision_id"),
                "evidence": [_evidence(context, line_id)],
            }
        )
        result["memberships"][line_id] = deepcopy(
            values.get(
                ("membership", line_id), _initial(context, "membership", line_id)
            )
        )
    for cell_id in context["cells"]:
        result["quantities"][cell_id] = deepcopy(
            values.get(("quantity", cell_id), _initial(context, "quantity", cell_id))
        )
    return result


def review_queue(snapshot, *, revisions=(), selections=()):
    """Deterministic source-inspection queue; confidence is triage only."""
    context = _context(snapshot, selections)
    view = reviewed_view(snapshot, revisions=revisions, selections=selections)
    queue = []
    for cell_id, (_, cell) in context["cells"].items():
        if not cell["line_ids"]:
            continue
        current = view["quantities"][cell_id]
        raw = "\n".join(context["lines"][i][1]["text"] for i in cell["line_ids"])
        scores = [context["lines"][i][1]["confidence"] for i in cell["line_ids"]]
        confidence = min((score for score in scores if score is not None), default=None)
        numeric = bool(re.search(r"\d|[¼½¾⅐-⅞]", raw))
        reasons = []
        if current["state"] == "unresolved":
            reasons.append("unresolved_quantity")
        if current["state"] in {"unparsed", "proposed"}:
            reasons.append("unreviewed_cell_reading")
        if numeric and (cell["column_header"] or cell["row_header"]):
            reasons.append("suspicious_numeric_header")
        if numeric and (
            confidence is None or confidence < 0.85 or re.search(r"[/¼½¾⅐-⅞]", raw)
        ):
            reasons.append("uncertain_quantity")
        if reasons:
            queue.append(
                {
                    "kind": "quantity",
                    "target_id": cell_id,
                    "reasons": reasons,
                    "state": current["state"],
                    "value": deepcopy(current["value"]),
                    "confidence": confidence,
                    "evidence": [_evidence(context, i) for i in cell["line_ids"]],
                }
            )
    for line_id, current in view["memberships"].items():
        if current["state"] == "unresolved" or (
            current["value"] and len(current["value"]) != 1
        ):
            queue.append(
                {
                    "kind": "membership",
                    "target_id": line_id,
                    "reasons": ["unresolved_membership"],
                    "state": current["state"],
                    "value": deepcopy(current["value"]),
                    "confidence": context["lines"][line_id][1]["confidence"],
                    "evidence": [_evidence(context, line_id)],
                }
            )
    for line in view["lines"]:
        if line["state"] == "unresolved":
            queue.append(
                {
                    "kind": "line_text",
                    "target_id": line["line_id"],
                    "reasons": ["unresolved_text"],
                    "state": "unresolved",
                    "value": None,
                    "confidence": context["lines"][line["line_id"]][1]["confidence"],
                    "evidence": deepcopy(line["evidence"]),
                }
            )
    order = {line_id: n for n, line_id in enumerate(context["lines"])}
    return sorted(
        queue,
        key=lambda item: (
            0 if item["state"] == "unresolved" else 1,
            -1 if item["confidence"] is None else item["confidence"],
            min(order[e["line_id"]] for e in item["evidence"]),
            item["kind"],
            item["target_id"],
        ),
    )


def render_review_report(snapshot, *, revisions=(), selections=()):
    """Script-free report; all book/reviewer text remains escaped plain text."""
    view = reviewed_view(snapshot, revisions=revisions, selections=selections)
    queue = review_queue(snapshot, revisions=revisions, selections=selections)
    rows = []
    for line in view["lines"]:
        rows.append(
            "<tr><td>"
            + escape(
                f"{line['page_id']} / physical {line['physical_page']} / {line['line_id']}"
            )
            + "</td><td><pre>"
            + escape(line["raw_text"])
            + "</pre></td><td><pre>"
            + escape(line["text"] if line["text"] is not None else "[unresolved]")
            + "</pre></td><td>"
            + escape(line["state"])
            + "</td></tr>"
        )
    audit = {"view": view, "queue": queue, "revisions": list(revisions)}
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Source-backed review</title>'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">'
        "<style>body{font:16px system-ui;margin:2rem;max-width:100rem}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #999;padding:.5rem;text-align:left;vertical-align:top}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere}th{background:#eee}</style><body><h1>Source-backed review</h1>"
        "<p>Proposals and source inspection remain separate from owner acceptance and publication. "
        "Raw recognized text is preserved. Null values remain unresolved.</p><p>Snapshot: "
        + escape(view["snapshot_sha256"])
        + "</p><table><thead><tr><th>Source</th><th>Raw OCR</th>"
        "<th>Reading view</th><th>State</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table><h2>Exact evidence, revision chain and queue</h2><pre>"
        + escape(
            json.dumps(
                audit, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
            )
        )
        + "</pre></body></html>"
    )
