"""Digest-bound proposals and persistent explicit approval of saved evidence."""

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC
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
        ("kind", "target_id", "before_sha256", "state", "value", "reason", "evidence")
        + (("occurrence",) if "occurrence" in change else ())
        + (("readings",) if "readings" in change else ()),
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
    if "readings" in change:
        readings = change["readings"]
        if not isinstance(readings, list) or not readings:
            raise ValueError("competing readings required")
        identities, selected = set(), []
        for reading in readings:
            _exact(reading, ("id", "value", "state", "reason", "evidence"), "reading")
            if (
                not _nonempty(reading["id"])
                or reading["id"] in identities
                or not _nonempty(reading["value"])
                or not _nonempty(reading["reason"])
                or reading["state"] not in {"selected", "rejected", "tied", "unmatched"}
                or not reading["evidence"]
            ):
                raise ValueError("invalid competing reading identity, state or reason")
            identities.add(reading["id"])
            for item in reading["evidence"]:
                if _digest(item) not in {_digest(e) for e in evidence}:
                    raise ValueError("unmatched reading evidence")
            if reading["state"] == "selected":
                selected.append(reading)
        if len(selected) > 1 or (selected and selected[0]["value"] != value):
            raise ValueError("selected reading and effective text disagree")
        if change["state"] == "source_reviewed" and (
            len(selected) != 1
            or any(r["state"] in {"tied", "unmatched"} for r in readings)
        ):
            raise ValueError("unresolved competing readings require source comparison")
    key = (kind, target)
    current = values.get(key, _initial(context, kind, target))
    if change["before_sha256"] != _digest(
        {"value": current["value"], "state": current["state"]}
    ):
        raise ValueError("stale correction base reading")
    if "occurrence" in change:
        occurrence = change["occurrence"]
        _exact(
            occurrence,
            ("start", "end", "before", "selection_id", "role", "cell_id"),
            "occurrence",
        )
        text = current["value"]
        start, end = occurrence["start"], occurrence["end"]
        if (
            kind != "line_text"
            or not isinstance(text, str)
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(text)
            or not _nonempty(occurrence["before"])
            or text[start:end] != occurrence["before"]
        ):
            raise ValueError("stale or missing exact occurrence; unresolved target")
        if occurrence["selection_id"] not in context["owners"][target] or not _nonempty(
            occurrence["role"]
        ):
            raise ValueError("unresolved occurrence culinary association")
        cell_id = occurrence["cell_id"]
        if cell_id is not None and (
            cell_id not in context["cells"]
            or target not in context["cells"][cell_id][1]["line_ids"]
        ):
            raise ValueError("unmatched occurrence cell")
        if value is not None:
            value = text[:start] + value + text[end:]
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
    if any("readings" in c for r in revisions for c in r["changes"]):
        result["readings"] = [
            {
                "revision_id": r["id"],
                "target_id": c["target_id"],
                "occurrence": deepcopy(c.get("occurrence")),
                "alternatives": deepcopy(c["readings"]),
            }
            for r in revisions
            for c in r["changes"]
            if "readings" in c
        ]
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


def _effective_selections(candidate):
    """Project reviewed ownership while retaining the original boundary evidence."""
    scopes = deepcopy(candidate["selections"])
    for scope in scopes:
        scope["line_ids"] = [
            i
            for i in scope["line_ids"]
            if candidate["view"]["memberships"][i]["state"] != "source_reviewed"
            or candidate["view"]["memberships"][i]["value"] == [scope["id"]]
        ]
        for line in candidate["view"]["lines"]:
            membership = candidate["view"]["memberships"][line["line_id"]]
            if (
                membership["state"] == "source_reviewed"
                and membership["value"] == [scope["id"]]
                and line["line_id"] not in scope["line_ids"]
            ):
                scope["line_ids"].append(line["line_id"])
    return scopes


def _scope_binding(candidate, scope, line_ids=None):
    """Bind local source interpretation without unrelated candidate content."""
    ids = scope["line_ids"] if line_ids is None else line_ids
    selected = set(ids)
    lines = {l["line_id"]: l for l in candidate["view"]["lines"]}
    return _digest(
        {
            **(
                {"extraction_run": candidate["extraction_run"]}
                if "extraction_run" in candidate
                else {}
            ),
            "edition": candidate["snapshot"]["edition"],
            "scope": scope
            if line_ids is None
            else {
                "id": scope["id"],
                "line_ids": ids,
                "reading_order": [i for i in scope["line_ids"] if i in selected],
                "formulation": scope.get("formulation"),
                "variation": scope.get("variation"),
            },
            "pages": [
                {k: v for k, v in p.items() if k != "lines"}
                for p in candidate["snapshot"]["pages"]
                if any(l["id"] in selected for l in p["lines"])
            ],
            "lines": [
                {
                    k: v
                    for k, v in lines[i].items()
                    if k not in {"revision_id", "reason"}
                }
                for i in ids
            ],
            "memberships": {
                i: {
                    k: v
                    for k, v in candidate["view"]["memberships"][i].items()
                    if k not in {"revision_id", "reason"}
                }
                for i in ids
            },
            "blocks": [
                b
                for b in candidate["snapshot"]["blocks"]
                if selected.intersection(b["line_ids"])
            ],
            "quantities": {
                cell["id"]: candidate["view"]["quantities"][cell["id"]]
                for table in candidate["snapshot"]["tables"]
                for cell in table["cells"]
                if selected.intersection(cell["line_ids"])
            },
        }
    )


def _continuous_binding(data, candidate, event, scope, ids=None):
    """An intervening interpretation change permanently ends old eligibility."""
    candidates = data["candidates"]
    start = next(
        i for i, c in enumerate(candidates) if c["id"] == event["candidate_id"]
    )
    end = next(i for i, c in enumerate(candidates) if c["id"] == candidate["id"])
    expected = _scope_binding(candidate, scope, ids)
    for previous in candidates[start : end + 1]:
        old_scope = next(
            (s for s in _effective_selections(previous) if s["id"] == scope["id"]), None
        )
        if old_scope is None or (ids and not set(ids) <= set(old_scope["line_ids"])):
            return False
        if _scope_binding(previous, old_scope, ids) != expected:
            return False
    return start <= end


def _revoked_decisions(history):
    from .withdrawal import withdrawn_decisions

    revoked = withdrawn_decisions(history)
    prior = []
    for event in history:
        if event["action"] == "revoke":
            revoked.update(event.get("affected_decisions", []))
            if event["relates_to"] is not None:
                revoked.add(event["relates_to"])
            else:
                revoked.update(e["id"] for e in prior if e["scope"] == event["scope"])
        prior.append(event)
    return revoked


def _workflow_validation(history, actor, config, policy):
    # The original manual owner workflow remains compatible. New configurations
    # record validation explicitly; this never enables agent approval authority.
    if config == "human-source-review.v1" and policy == "standalone-content.v1":
        original = next(
            (
                e["actor"]
                for e in history
                if e["action"] in {"approve", "review_portion"}
                and e["reviewer_config"] == config
                and e["policy"] == policy
            ),
            None,
        )
        if original is None or original == actor:
            return None
    revoked = _revoked_decisions(history)
    matches = [
        e
        for e in history
        if e["action"] == "validate_workflow"
        and e["actor"] == actor
        and e["reviewer_config"] == config
        and e["policy"] == policy
        and e["id"] not in revoked
    ]
    if not matches:
        raise ValueError("fresh workflow validation required for reviewer/model/policy")
    return matches[-1]["id"]


def _support_scopes(candidate, scope):
    scopes = {s["id"]: s for s in _effective_selections(candidate)}
    result = []
    for use in scope.get("required_content", []):
        if not isinstance(use, dict) or use.get("scope") not in {"whole", "partial"}:
            raise ValueError("required supporting content needs explicit scope")
        target = scopes.get(use.get("selection_id"))
        if target is None or any(
            use.get(k) != target.get(k) for k in ("formulation", "variation")
        ):
            raise ValueError("required supporting content selection mismatch")
        ids = use.get("line_ids") if use["scope"] == "partial" else None
        if use["scope"] == "partial" and (
            not ids
            or len(set(ids)) != len(ids)
            or not set(ids) <= set(target["line_ids"])
        ):
            raise ValueError("invalid partial supporting content")
        result.append((use, target, ids))
    return result


def _consistency_reasons(candidate):
    view = candidate["view"]
    lines = {l["line_id"]: l for l in view["lines"]}
    reasons = []
    for table in candidate["snapshot"]["tables"]:
        for cell in table["cells"]:
            quantity = view["quantities"][cell["id"]]
            effective = "\n".join(lines[i]["text"] or "" for i in cell["line_ids"])
            if (
                quantity["state"] == "source_reviewed"
                and quantity["value"] != effective
            ):
                reasons.append("quantity and effective text disagree: " + cell["id"])
    return reasons


def _check_clearance(candidate):
    reasons = _consistency_reasons(candidate)
    if reasons:
        raise ValueError("; ".join(reasons))
    view = candidate["view"]
    if any(l["state"] in {"proposed", "unresolved"} for l in view["lines"]):
        raise ValueError("unresolved or proposed content requires source comparison")
    if any(
        q["state"] in {"unparsed", "proposed", "unresolved"}
        for q in view["quantities"].values()
    ):
        raise ValueError("unresolved quantity requires source comparison")


class ReviewStore:
    """Persistent administrative decisions over saved evidence, never inference.

    Candidate and decision history is append-only under a process lock. Legacy
    revisions are retained verbatim; their reviewer is not an approval actor.
    """

    def __init__(self, path):
        from pathlib import Path

        self.path = Path(path)

    def _load(self):
        if not self.path.exists():
            return {"version": "content-review.v1", "candidates": [], "decisions": []}
        data = json.loads(self.path.read_bytes())
        if data["version"] != "content-review.v1":
            raise ValueError("unsupported content review version")
        predecessor = None
        for event in data["decisions"]:
            if event["predecessor"] != predecessor or event["id"] != _digest(
                {k: v for k, v in event.items() if k != "id"}
            ):
                raise ValueError("invalid decision history")
            predecessor = event["id"]
        for candidate in data["candidates"]:
            if candidate["id"] != _digest(
                {k: v for k, v in candidate.items() if k != "id"}
            ):
                raise ValueError("invalid candidate identity")
            actual = reviewed_view(
                candidate["snapshot"],
                selections=candidate["selections"],
                revisions=candidate["revisions"],
            )
            if actual != candidate["view"]:
                raise ValueError("effective text and review metadata disagree")
        for index, candidate in enumerate(data["candidates"]):
            self._validate_lineage(data["candidates"][:index], candidate)
        candidates = {c["id"]: c for c in data["candidates"]}
        applied = set()
        for event in data["decisions"]:
            candidate = candidates.get(event["candidate_id"])
            if (
                candidate is None
                or event["snapshot_sha256"] != candidate["view"]["snapshot_sha256"]
                or event["effective_text_sha256"] != _digest(candidate["view"])
            ):
                raise ValueError("decision evidence or effective text mismatch")
            if event["action"] in {"clear_flag", "approve"}:
                if _consistency_reasons(candidate):
                    raise ValueError("quantity and effective text disagree")
                if event["action"] == "clear_flag":
                    _check_clearance(candidate)
            if event["action"] == "apply_draft":
                applied.add((event["candidate_id"], event["scope"]))
            if event["action"] == "approve":
                if (
                    candidate["revisions"]
                    and (candidate["id"], event["scope"]) not in applied
                ):
                    raise ValueError("approval requires prior apply_draft")
                scope = next(
                    (
                        s
                        for s in _effective_selections(candidate)
                        if s["id"] == event["scope"]
                    ),
                    None,
                )
                if (
                    not event["complete"]
                    or event["required_content"]
                    != (
                        scope.get("required_content", [])
                        if scope and "scope_sha256" in event
                        else []
                    )
                    or event["actor"]["kind"] != "human"
                    or scope is None
                    or scope["kind"] not in {"recipe", "passage", "reference_entry"}
                    or scope["state"] == "unresolved"
                    or event["evidence"]
                    != source_evidence(candidate["snapshot"], scope["line_ids"])
                ):
                    raise ValueError("invalid complete-content approval")
                if "scope_sha256" in event and event["scope_sha256"] != _scope_binding(
                    candidate, scope
                ):
                    raise ValueError("approval scope mismatch")
                ids = set(scope["line_ids"])
                if any(
                    l["state"] in {"proposed", "unresolved"}
                    for l in candidate["view"]["lines"]
                    if l["line_id"] in ids
                ):
                    raise ValueError("approval covers unresolved or proposed text")
                if any(
                    candidate["view"]["memberships"][i]["value"] != [event["scope"]]
                    for i in ids
                ):
                    raise ValueError("approval ownership mismatch")
                self._validate_portion(
                    candidate,
                    scope,
                    event["actor"],
                    event["evidence"],
                    scope["line_ids"],
                )
        prior = {**data, "decisions": []}
        for event in data["decisions"]:
            candidate = candidates[event["candidate_id"]]
            scope = next(
                (
                    s
                    for s in _effective_selections(candidate)
                    if s["id"] == event["scope"]
                ),
                None,
            )
            if event["action"] == "confirm_error":
                from .withdrawal import affected_decisions, affected_pages, validate

                validate(event)
                if (
                    scope is None
                    or event["evidence"]
                    != source_evidence(candidate["snapshot"], scope["line_ids"])
                    or event["affected_decisions"]
                    != affected_decisions(
                        prior["decisions"],
                        candidate,
                        scope,
                        _scope_binding(candidate, scope),
                        prior["candidates"],
                    )
                    or event["affected_pages"]
                    != affected_pages(prior["decisions"], event["affected_decisions"])
                ):
                    raise ValueError("substantive-error evidence mismatch")
            if event["action"] == "revoke" and "affected_decisions" in event:
                from .withdrawal import affected_pages, revoked_approvals, validate

                validate(event)
                if event["affected_decisions"] != revoked_approvals(
                    prior["decisions"], event["scope"], event["relates_to"]
                ) or event["affected_pages"] != affected_pages(
                    prior["decisions"], event["affected_decisions"]
                ):
                    raise ValueError("revocation evidence mismatch")
            if event["action"] == "review_portion":
                if candidate["revisions"] and (candidate["id"], event["scope"]) not in {
                    (e["candidate_id"], e["scope"])
                    for e in prior["decisions"]
                    if e["action"] == "apply_draft"
                }:
                    raise ValueError("regional review requires prior apply_draft")
                if scope is None:
                    raise ValueError("unknown regional scope")
                ids = [e["line_id"] for e in event["evidence"]]
                self._validate_portion(
                    candidate, scope, event["actor"], event["evidence"], ids
                )
                if event.get("scope_sha256") != _scope_binding(candidate, scope, ids):
                    raise ValueError("regional evidence mismatch")
            if (
                event["action"] in {"approve", "review_portion", "undo"}
                and "scope_sha256" in event
            ):
                bindings, reasons = self._support_bindings(
                    prior, candidate, scope, {scope["id"]}
                )
                if reasons:
                    raise ValueError("approval requires eligible supporting content")
                if bindings != event.get("dependency_bindings"):
                    raise ValueError("approval dependency mismatch")
            if event["action"] == "validate_workflow" and (
                event["actor"]["kind"] != "human" or not event["evidence"]
            ):
                raise ValueError("invalid workflow validation")
            if event["action"] in {"approve", "review_portion", "undo"}:
                validation = _workflow_validation(
                    prior["decisions"],
                    event["actor"],
                    event["reviewer_config"],
                    event["policy"],
                )
                if validation != event.get("workflow_validation_id"):
                    raise ValueError("workflow validation mismatch")
            if event["action"] == "approve":
                self._require_undo(prior, candidate, scope)
            if event["action"] == "undo":
                checks = self._check_undo(
                    prior,
                    candidate,
                    scope,
                    event["actor"],
                    event["evidence"],
                    event["relates_to"],
                )
                if checks != event.get("undo_checks"):
                    raise ValueError("undo checks mismatch")
            prior["decisions"].append(event)
        return data

    def _require_undo(self, data, candidate, scope):
        matches = [
            e
            for e in data["decisions"]
            if e["scope"] == scope["id"]
            and e["action"] in {"approve", "undo"}
            and e.get("scope_sha256") == _scope_binding(candidate, scope)
        ]
        if matches and not any(
            _continuous_binding(data, candidate, e, scope) for e in matches
        ):
            raise ValueError(
                "restored interpretation requires explicit undo before approval"
            )

    def _check_undo(self, data, candidate, scope, actor, evidence, relates_to):
        target = next(
            (
                e
                for e in data["decisions"]
                if e["id"] == relates_to
                and e["scope"] == scope["id"]
                and e["action"] in {"approve", "apply_draft", "undo"}
            ),
            None,
        )
        if target is None:
            raise ValueError("undo requires an explicit prior content decision")
        if target.get("scope_sha256") != _scope_binding(candidate, scope):
            raise ValueError("undo source, extraction or scope mismatch")
        self._validate_portion(candidate, scope, actor, evidence, scope["line_ids"])
        return {
            "target_revoked": target["id"] in _revoked_decisions(data["decisions"]),
            "eligible_before": bool(
                self._eligibility(data, candidate, scope, set())[0]
            ),
            "source_sha256": candidate["snapshot"]["edition"]["source_sha256"],
            "scope_sha256": _scope_binding(candidate, scope),
        }

    def _validate_lineage(self, previous, candidate):
        edition = candidate["snapshot"]["edition"]
        for old in previous:
            old_edition = old["snapshot"]["edition"]
            if (
                old_edition["id"] == edition["id"]
                and old_edition["source_sha256"] != edition["source_sha256"]
            ):
                raise ValueError("replacement needs distinct book-edition identity")
        for link in candidate.get("page_correspondences", []):
            _exact(
                link,
                ("candidate_id", "old_page_id", "new_page_id"),
                "page correspondence",
            )
            old = next((c for c in previous if c["id"] == link["candidate_id"]), None)
            if (
                old is None
                or old["snapshot"]["edition"]["source_sha256"]
                == edition["source_sha256"]
                or link["old_page_id"]
                not in {p["id"] for p in old["snapshot"]["pages"]}
                or link["new_page_id"]
                not in {p["id"] for p in candidate["snapshot"]["pages"]}
            ):
                raise ValueError("invalid replacement page correspondence")

    def export(self):
        """Inspectable complete history, suitable for immutable publication backup."""
        return self._load()

    def save_candidate(
        self,
        snapshot,
        *,
        selections=(),
        revisions=(),
        page_correspondences=(),
        extraction_run=None,
        display=None,
    ):
        from .storage import atomic_write, canonical, file_lock

        view = reviewed_view(snapshot, selections=selections, revisions=revisions)
        candidate = {
            "snapshot": deepcopy(snapshot),
            "selections": deepcopy(list(selections)),
            "revisions": deepcopy(list(revisions)),
            "view": view,
        }
        if extraction_run is not None:
            if not _nonempty(extraction_run):
                raise ValueError("explicit extraction run identity required")
            candidate["extraction_run"] = extraction_run
        if display is not None:
            candidate["display"] = deepcopy(display)
        if page_correspondences:
            candidate["page_correspondences"] = deepcopy(list(page_correspondences))
        with file_lock(self.path.with_suffix(".lock")):
            data = self._load()
            self._validate_lineage(data["candidates"], candidate)
            candidate["sequence"] = len(data["candidates"]) + 1
            candidate["id"] = _digest({k: v for k, v in candidate.items() if k != "id"})
            data["candidates"].append(candidate)
            atomic_write(self.path, canonical(data))
        return candidate["id"]

    def inspect(self, selection_id, *, candidate_id=None):
        data = self._load()
        if not data["candidates"]:
            raise ValueError("missing candidate")
        candidate = (
            next(c for c in data["candidates"] if c["id"] == candidate_id)
            if candidate_id
            else data["candidates"][-1]
        )
        scope = next(
            (s for s in _effective_selections(candidate) if s["id"] == selection_id),
            None,
        )
        if scope is None:
            raise ValueError("unknown selection")
        history = [e for e in data["decisions"] if e["scope"] == selection_id]
        approval, reasons = self._eligibility(data, candidate, scope, set())
        return {
            "eligible": bool(approval),
            "reasons": _consistency_reasons(candidate) + reasons,
            "approval": approval,
            "history": history,
            "candidate": candidate,
            "scope": scope,
        }

    def _validate_portion(self, candidate, scope, actor, evidence, ids):
        if actor["kind"] != "human":
            raise ValueError("agent approval authority is not validated")
        if (
            not ids
            or len(ids) != len(set(ids))
            or not set(ids) <= set(scope["line_ids"])
        ):
            raise ValueError("invalid regional source evidence")
        if list(evidence) != source_evidence(candidate["snapshot"], ids):
            raise ValueError("exact inspected source evidence required")
        if any(
            l["state"] in {"proposed", "unresolved"}
            for l in candidate["view"]["lines"]
            if l["line_id"] in ids
        ):
            raise ValueError("unresolved regional content")
        if any(
            candidate["view"]["memberships"][i]["value"] != [scope["id"]] for i in ids
        ):
            raise ValueError("unresolved regional ownership")
        for i in ids:
            if candidate["view"]["memberships"][i]["state"] in {
                "proposed",
                "unresolved",
            }:
                raise ValueError("unresolved regional ownership")
        for table in candidate["snapshot"]["tables"]:
            for cell in table["cells"]:
                if set(cell["line_ids"]).intersection(ids) and candidate["view"][
                    "quantities"
                ][cell["id"]]["state"] in {"proposed", "unresolved"}:
                    raise ValueError("unresolved regional quantity")
                if set(cell["line_ids"]).intersection(ids):
                    quantity = candidate["view"]["quantities"][cell["id"]]
                    effective = "\n".join(
                        l["text"] or ""
                        for i in cell["line_ids"]
                        for l in candidate["view"]["lines"]
                        if l["line_id"] == i
                    )
                    if (
                        quantity["state"] == "source_reviewed"
                        and quantity["value"] != effective
                    ):
                        raise ValueError("quantity and effective text disagree")

    def _support_bindings(self, data, candidate, scope, visiting):
        """Resolve exact whole/partial dependencies identically at write and replay."""
        try:
            uses = _support_scopes(candidate, scope)
        except ValueError:
            return [], ["required_support_selection_mismatch"]
        bindings = []
        for use, target, ids in uses:
            support = self._support_decision(data, candidate, target, ids, visiting)
            if not support:
                return [], ["required_support_pending:" + target["id"]]
            bindings.append(
                {
                    **use,
                    "decision_id": support["id"],
                    "scope_sha256": _scope_binding(candidate, target, ids),
                }
            )
        return bindings, []

    def _support_decision(self, data, candidate, target, ids, visiting):
        if ids is None:
            return self._eligibility(data, candidate, target, visiting)[0]
        revoked = _revoked_decisions(data["decisions"])
        findings = [
            e
            for e in data["decisions"]
            if e["scope"] == target["id"]
            and e["action"] == "review_portion"
            and e["id"] not in revoked
            and e.get("scope_sha256") == _scope_binding(candidate, target, ids)
            and _continuous_binding(data, candidate, e, target, ids)
        ]
        if not findings or target["id"] in visiting:
            return None
        finding = findings[-1]
        bindings, reasons = self._support_bindings(
            data, candidate, target, visiting | {target["id"]}
        )
        if reasons:
            return None
        return finding if bindings == finding.get("dependency_bindings", []) else None

    def _eligibility(self, data, candidate, scope, visiting):
        if scope["id"] in visiting:
            return None, ["required_support_cycle"]
        visiting = visiting | {scope["id"]}
        history = [e for e in data["decisions"] if e["scope"] == scope["id"]]
        revoked = _revoked_decisions(data["decisions"])
        matches = [
            e
            for e in history
            if e["action"] == "approve"
            and _continuous_binding(data, candidate, e, scope)
            and (
                e.get("scope_sha256") == _scope_binding(candidate, scope)
                if "scope_sha256" in e
                else e["candidate_id"] == candidate["id"]
            )
        ]
        approval = matches[-1] if matches else None
        if not approval or approval["id"] in revoked:
            return None, ["exact_complete_content_approval_required"]
        bindings, reasons = self._support_bindings(data, candidate, scope, visiting)
        if reasons:
            return None, reasons
        if bindings != approval.get("dependency_bindings", []):
            return None, ["required_support_changed"]
        return approval, []

    def decide(
        self,
        selection_id,
        action,
        *,
        actor,
        reason,
        complete=False,
        evidence=(),
        required_content=(),
        relates_to=None,
        reviewer_config="human-source-review.v1",
        policy="standalone-content.v1",
        candidate_id=None,
        withdrawal_store=None,
    ):
        from datetime import datetime

        from .storage import atomic_write, canonical, file_lock

        if action in {"confirm_error", "revoke"} and withdrawal_store is None:
            raise ValueError("withdrawal requires shared publication store")
        if action not in {
            "apply_draft",
            "clear_flag",
            "approve",
            "revoke",
            "metadata_amendment",
            "review_portion",
            "validate_workflow",
            "undo",
            "confirm_error",
        }:
            raise ValueError("invalid decision action")
        if (
            not isinstance(actor, dict)
            or actor.get("kind") not in {"human", "agent"}
            or not _nonempty(actor.get("id"))
        ):
            raise ValueError("explicit actor identity and role required")
        if not all(_nonempty(v) for v in (reason, reviewer_config, policy)):
            raise ValueError("reason, reviewer configuration and policy required")
        with file_lock(self.path.with_suffix(".lock")):
            state = self.inspect(selection_id, candidate_id=candidate_id)
            candidate, scope = state["candidate"], state["scope"]
            if action == "confirm_error" and (
                actor["kind"] != "human"
                or list(evidence)
                != source_evidence(candidate["snapshot"], scope["line_ids"])
            ):
                raise ValueError(
                    "confirmed error requires human and exact source evidence"
                )
            dependency_bindings = []
            portion_ids = None
            workflow_validation_id = None
            undo_checks = None
            if action == "validate_workflow":
                if actor["kind"] != "human":
                    raise ValueError("agent approval authority is not validated")
                if not evidence:
                    raise ValueError("workflow validation evidence required")
            if action in {"approve", "review_portion", "undo"}:
                workflow_validation_id = _workflow_validation(
                    self._load()["decisions"], actor, reviewer_config, policy
                )
            if action == "undo":
                undo_checks = self._check_undo(
                    self._load(), candidate, scope, actor, evidence, relates_to
                )
            if action == "review_portion":
                portion_ids = [e["line_id"] for e in evidence]
                self._validate_portion(candidate, scope, actor, evidence, portion_ids)
                if candidate["revisions"] and not any(
                    e["action"] == "apply_draft"
                    and e["candidate_id"] == candidate["id"]
                    for e in state["history"]
                ):
                    raise ValueError("apply_draft separately before regional review")
            if action in {"approve", "review_portion", "undo"}:
                dependency_bindings, reasons = self._support_bindings(
                    self._load(), candidate, scope, {selection_id}
                )
                if reasons:
                    raise ValueError(
                        "required supporting content remains pending: "
                        + "; ".join(reasons)
                    )

            if action == "clear_flag":
                _check_clearance(candidate)
            if action == "approve":
                self._require_undo(self._load(), candidate, scope)
                if _consistency_reasons(candidate):
                    raise ValueError("quantity and effective text disagree")
                if candidate["revisions"] and not any(
                    e["action"] == "apply_draft"
                    and e["candidate_id"] == candidate["id"]
                    for e in state["history"]
                ):
                    raise ValueError("apply_draft separately before approval")
                if actor["kind"] != "human":
                    raise ValueError("agent approval authority is not validated")
                if (
                    not complete
                    or required_content
                    or scope["kind"] not in {"recipe", "passage", "reference_entry"}
                    or scope["state"] == "unresolved"
                ):
                    raise ValueError(
                        "complete standalone recipe required; supporting content remains pending"
                    )
                expected = source_evidence(candidate["snapshot"], scope["line_ids"])
                if _digest(list(evidence)) != _digest(expected):
                    raise ValueError("exact inspected source evidence required")
                ids = set(scope["line_ids"])
                view = candidate["view"]
                if any(
                    l["state"] in {"proposed", "unresolved"}
                    for l in view["lines"]
                    if l["line_id"] in ids
                ):
                    raise ValueError("unresolved or proposed content")
                self._validate_portion(
                    candidate, scope, actor, evidence, scope["line_ids"]
                )
                if any(view["memberships"][i]["value"] != [selection_id] for i in ids):
                    raise ValueError("unresolved recipe ownership")
            data = self._load()
            if relates_to is not None and not any(
                e["id"] == relates_to and e["scope"] == selection_id
                for e in data["decisions"]
            ):
                raise ValueError("unknown related decision")
            event = {
                "version": "content-decision.v1",
                "workflow_validation_id": workflow_validation_id,
                **({"undo_checks": undo_checks} if action == "undo" else {}),
                "scope_sha256": _scope_binding(candidate, scope, portion_ids),
                "dependency_bindings": dependency_bindings,
                "timestamp": datetime.now(UTC).isoformat(),
                "actor": deepcopy(actor),
                "action": action,
                "scope": selection_id,
                "candidate_id": candidate["id"],
                "snapshot_sha256": candidate["view"]["snapshot_sha256"],
                "effective_text_sha256": _digest(candidate["view"]),
                "evidence": deepcopy(list(evidence)),
                "complete": complete,
                "required_content": deepcopy(scope.get("required_content", [])),
                "reason": reason,
                "reviewer_config": reviewer_config,
                "policy": policy,
                "relates_to": relates_to,
                "predecessor": data["decisions"][-1]["id"]
                if data["decisions"]
                else None,
            }
            if action == "confirm_error":
                from .withdrawal import affected_decisions, affected_pages

                event["affected_decisions"] = affected_decisions(
                    data["decisions"],
                    candidate,
                    scope,
                    _scope_binding(candidate, scope),
                    data["candidates"],
                )
                if not event["affected_decisions"]:
                    raise ValueError(
                        "confirmed error has no enforceable approval target"
                    )
                event["affected_pages"] = affected_pages(
                    data["decisions"], event["affected_decisions"]
                )
            if action == "revoke":
                from .withdrawal import affected_pages, revoked_approvals

                if actor["kind"] != "human":
                    raise ValueError("revocation requires human authority")
                event["affected_decisions"] = revoked_approvals(
                    data["decisions"], selection_id, relates_to
                )
                event["affected_pages"] = affected_pages(
                    data["decisions"], event["affected_decisions"]
                )
            event["id"] = _digest(event)
            data["decisions"].append(event)
            atomic_write(self.path, canonical(data))
            if action in {"confirm_error", "revoke"}:
                from .withdrawal import record_withdrawal

                record_withdrawal(withdrawal_store, event)
        return event

    def publication_sections(self):
        """Project exact approvals into immutable recipe text and page citations."""
        data = self._load()
        if not data["candidates"]:
            raise ValueError("missing candidate")
        candidate = data["candidates"][-1]
        if _consistency_reasons(candidate):
            raise ValueError("quantity and effective text disagree")
        lines = {l["line_id"]: l for l in candidate["view"]["lines"]}
        result = []
        for ordinal, scope in enumerate(_effective_selections(candidate)):
            state = self.inspect(scope["id"])
            selected = [lines[i] for i in scope["line_ids"]]
            if not selected:
                raise ValueError("empty content scope")
            approval = state["approval"]
            locator = {
                "kind": "page",
                "physical_page": selected[0]["physical_page"],
                "physical_pages": list(
                    dict.fromkeys(l["physical_page"] for l in selected)
                ),
                "content_review": {
                    "path": "quality/content-review.json",
                    "candidate_id": candidate["id"],
                    "source_sha256": candidate["snapshot"]["edition"]["source_sha256"],
                    "edition_id": candidate["snapshot"]["edition"]["id"],
                    "extraction_run": candidate.get("extraction_run"),
                    "reviewer_config": approval["reviewer_config"]
                    if approval
                    else None,
                    "policy": approval["policy"] if approval else None,
                    "page_correspondences": candidate.get("page_correspondences", []),
                    "decision_id": approval["id"] if approval else None,
                    "approval_candidate_id": approval["candidate_id"]
                    if approval
                    else None,
                    "scope_sha256": _scope_binding(candidate, scope),
                    "eligible": state["eligible"],
                    "reasons": state["reasons"],
                },
            }
            result.append(
                {
                    "id": scope["id"],
                    "ordinal": ordinal,
                    "kind": scope["kind"],
                    "title": selected[0]["text"] or scope["id"],
                    "text": "\n".join(l["text"] for l in selected) if approval else "",
                    "source_sha256": candidate["snapshot"]["edition"]["source_sha256"],
                    "locator": locator,
                    "eligible": state["eligible"],
                }
            )
        return result
