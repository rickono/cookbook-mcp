"""Synthetic revision/evidence tests; no file ingestion, images, or OCR."""

import hashlib
import json
from copy import deepcopy

import pytest

from cookbook.transcription import snapshot_digest
from cookbook.transcription_review import (
    make_revision,
    render_review_report,
    review_queue,
    reviewed_view,
    source_evidence,
    target_digest,
)


def snapshot():
    lines = []
    for n, text in enumerate(
        ("1? cup", "<script>alert('source')</script>", "Sidebar soup")
    ):
        top = 10 + n * 20
        lines.append(
            {
                "id": f"l{n}",
                "text": text,
                "polygon": [[10, top], [90, top], [90, top + 10], [10, top + 10]],
                "confidence": 0.4 if n == 0 else 0.99,
            }
        )
    return {
        "version": "scanned-transcription.v1",
        "edition": {"id": "synthetic", "source_sha256": "a" * 64, "format": "pdf"},
        "pages": [
            {
                "id": "p",
                "physical_page": 1,
                "source_page_sha256": "b" * 64,
                "render_sha256": "c" * 64,
                "render_size": [100, 100],
                "source_size": [50, 50],
                "render_to_source": [0.5, 0, 0, 0.5, 0, 0],
                "recognition": {"method": "synthetic", "artifact_sha256": "d" * 64},
                "lines": lines,
            }
        ],
        "blocks": [
            {
                "id": "table-block",
                "page_id": "p",
                "kind": "table",
                "line_ids": ["l0"],
                "children": [],
                "marker": None,
            },
            {
                "id": "prose",
                "page_id": "p",
                "kind": "unclassified",
                "line_ids": ["l1", "l2"],
                "children": [],
                "marker": None,
            },
        ],
        "tables": [
            {
                "id": "table",
                "block_id": "table-block",
                "page_id": "p",
                "rows": 1,
                "columns": 1,
                "cells": [
                    {
                        "id": "cell",
                        "row_start": 0,
                        "row_end": 1,
                        "column_start": 0,
                        "column_end": 1,
                        "line_ids": ["l0"],
                        "column_header": True,
                        "row_header": False,
                    }
                ],
            }
        ],
        "diagnostics": [],
    }


def selections():
    return [
        {
            "id": "main",
            "kind": "recipe",
            "line_ids": ["l0", "l1", "l2"],
            "state": "candidate",
            "reasons": ["heuristic"],
        },
        {
            "id": "sidebar",
            "kind": "recipe",
            "line_ids": [],
            "state": "candidate",
            "reasons": ["independent heading"],
        },
    ]


def change(
    base,
    kind="line_text",
    target="l0",
    value="1/2 cup",
    state="source_reviewed",
    *,
    revisions=(),
    selected=(),
):
    line_ids = ["l0"] if kind == "quantity" else [target]
    return {
        "kind": kind,
        "target_id": target,
        "before_sha256": target_digest(
            base, kind, target, revisions=revisions, selections=selected
        ),
        "state": state,
        "value": value,
        "reason": "Visible source supports this reading",
        "evidence": source_evidence(base, line_ids),
    }


def revision(base, changes, *, revisions=(), selected=()):
    return make_revision(
        base,
        changes,
        reviewer={"kind": "agent", "id": "synthetic-reviewer"},
        revisions=revisions,
        selections=selected,
    )


def test_review_overlay_preserves_raw_bytes_and_caller_inputs():
    base = snapshot()
    raw = json.dumps(base, ensure_ascii=False).encode()
    proposal = change(base)
    first = revision(base, [proposal])
    proposal["value"] = "tampered later"
    proposal["evidence"][0]["polygon"][0][0] = 50
    view = reviewed_view(base, revisions=[first])
    assert view["lines"][0]["raw_text"] == "1? cup"
    assert view["lines"][0]["text"] == "1/2 cup"
    assert view["lines"][0]["state"] == "source_reviewed"
    view["lines"][0]["evidence"][0]["polygon"][0][0] = 70
    assert json.dumps(base, ensure_ascii=False).encode() == raw
    assert first["changes"][0]["value"] == "1/2 cup"
    assert first["changes"][0]["evidence"][0]["polygon"][0][0] == 10


def test_null_quantity_and_text_remain_explicit_and_queued():
    base = snapshot()
    first = revision(
        base,
        [
            change(base, "quantity", "cell", None, "unresolved"),
            change(base, "line_text", "l0", None, "unresolved"),
        ],
    )
    view = reviewed_view(base, revisions=[first])
    assert view["quantities"]["cell"]["value"] is None
    assert view["lines"][0]["text"] is None
    assert view["lines"][0]["raw_text"] == "1? cup"
    assert {i["kind"] for i in review_queue(base, revisions=[first])} >= {
        "quantity",
        "line_text",
    }


def test_membership_correction_does_not_mutate_boundary_or_source():
    base, selected = snapshot(), selections()
    original = deepcopy((base, selected))
    first = revision(
        base,
        [change(base, "membership", "l2", ["sidebar"], selected=selected)],
        selected=selected,
    )
    view = reviewed_view(base, revisions=[first], selections=selected)
    assert view["memberships"]["l2"]["value"] == ["sidebar"]
    assert view["memberships"]["l0"]["value"] == ["main"]
    assert (base, selected) == original


def test_unresolved_membership_retains_null_and_source_reference():
    base, selected = snapshot(), selections()
    first = revision(
        base,
        [change(base, "membership", "l2", None, "unresolved", selected=selected)],
        selected=selected,
    )
    queued = review_queue(base, revisions=[first], selections=selected)
    membership = next(i for i in queued if i["kind"] == "membership")
    assert membership["target_id"] == "l2"
    assert membership["value"] is None
    assert membership["evidence"][0]["source_sha256"] == "a" * 64
    assert membership["evidence"][0]["physical_page"] == 1


def test_revision_chain_retains_predecessor_and_rejects_stale_change():
    base = snapshot()
    first = revision(base, [change(base)])
    old = deepcopy(first)
    second = revision(
        base, [change(base, value="½ cup", revisions=[first])], revisions=[first]
    )
    assert second["predecessor"] == first["id"]
    assert first == old
    assert reviewed_view(base, revisions=[first, second])["lines"][0]["text"] == "½ cup"
    with pytest.raises(ValueError, match="predecessor"):
        reviewed_view(base, revisions=[second])
    with pytest.raises(ValueError, match="stale correction"):
        revision(base, [change(base, value="¾ cup")], revisions=[first])


@pytest.mark.parametrize(
    "field",
    [
        "source_sha256",
        "source_page_sha256",
        "render_sha256",
        "recognition_sha256",
        "text_sha256",
        "page_id",
        "physical_page",
        "edition_id",
        "polygon",
    ],
)
def test_tampered_source_bindings_fail_even_with_valid_base_digest(field):
    base = snapshot()
    proposal = change(base)
    evidence = proposal["evidence"][0]
    evidence[field] = (
        [[11, 10], [90, 10], [90, 20], [10, 20]]
        if field == "polygon"
        else 2
        if field == "physical_page"
        else "wrong"
    )
    with pytest.raises(ValueError, match="stale source"):
        revision(base, [proposal])


@pytest.mark.parametrize("mutation", ["source", "line", "geometry", "selection"])
def test_revision_is_bound_to_entire_base_snapshot_and_selection_context(mutation):
    base, selected = snapshot(), selections()
    first = revision(base, [change(base, selected=selected)], selected=selected)
    if mutation == "source":
        base["edition"]["source_sha256"] = "e" * 64
    elif mutation == "line":
        base["pages"][0]["lines"][1]["text"] = "different raw bytes"
    elif mutation == "geometry":
        base["pages"][0]["lines"][0]["polygon"][0][0] = 11
    else:
        selected[0]["reasons"] = ["changed strategy"]
    with pytest.raises(ValueError, match="stale snapshot"):
        reviewed_view(base, revisions=[first], selections=selected)


def test_duplicate_or_conflicting_changes_fail_and_modified_revision_fails():
    base = snapshot()
    proposal = change(base)
    with pytest.raises(ValueError):
        revision(base, [proposal, deepcopy(proposal)])
    first = revision(base, [proposal])
    first["changes"][0]["value"] = "guessed value"
    with pytest.raises(ValueError, match="tampered revision"):
        reviewed_view(base, revisions=[first])


def test_recomputed_revision_identity_cannot_bypass_evidence_validation():
    base = snapshot()
    first = revision(base, [change(base)])
    first["changes"][0]["evidence"][0]["text_sha256"] = "f" * 64
    payload = {k: v for k, v in first.items() if k != "id"}
    first["id"] = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="stale source"):
        reviewed_view(base, revisions=[first])


def test_evidence_rejects_json_type_changes_and_single_use_iterators():
    base = snapshot()
    proposal = change(base)
    proposal["evidence"][0]["physical_page"] = True
    with pytest.raises(ValueError, match="stale source"):
        revision(base, [proposal])
    with pytest.raises(ValueError, match="replayable"):
        reviewed_view(base, revisions=iter([]))
    with pytest.raises(ValueError, match="replayable"):
        reviewed_view(base, selections=iter(selections()))


@pytest.mark.parametrize(
    "invalid",
    [
        "approval",
        "null",
        "unresolved_value",
        "unknown_member",
        "multi_member",
        "unknown_line",
        "missing_target_evidence",
        "duplicate_evidence",
    ],
)
def test_invalid_proposals_cannot_enter_ledger(invalid):
    base, selected = snapshot(), selections()
    proposal = change(base, selected=selected)
    if invalid == "approval":
        proposal["state"] = "accepted"
    elif invalid == "null":
        proposal["value"] = None
    elif invalid == "unresolved_value":
        proposal["state"] = "unresolved"
    elif invalid in {"unknown_member", "multi_member"}:
        proposal = change(
            base,
            "membership",
            "l0",
            ["missing"] if invalid == "unknown_member" else ["main", "sidebar"],
            selected=selected,
        )
    elif invalid == "unknown_line":
        proposal["target_id"] = "missing"
    elif invalid == "missing_target_evidence":
        proposal["evidence"] = source_evidence(base, ["l1"])
    else:
        proposal["evidence"] *= 2
    with pytest.raises(ValueError):
        revision(base, [proposal], selected=selected)


def test_uncertain_boundary_state_and_header_queue_are_deterministic():
    base, selected = snapshot(), selections()
    selected[0]["state"] = "unresolved"
    queue = review_queue(base, selections=selected)
    assert queue == review_queue(deepcopy(base), selections=deepcopy(selected))
    assert len([q for q in queue if q["kind"] == "membership"]) == 3
    quantity = next(q for q in queue if q["kind"] == "quantity")
    assert quantity["reasons"] == [
        "unreviewed_cell_reading",
        "suspicious_numeric_header",
        "uncertain_quantity",
    ]
    base["pages"][0]["lines"][0]["confidence"] = 0.99
    assert (
        "suspicious_numeric_header"
        in next(
            q
            for q in review_queue(base, selections=selected)
            if q["kind"] == "quantity"
        )["reasons"]
    )


@pytest.mark.parametrize("raw", ["100 g", "cups", "grams"])
def test_high_confidence_unparsed_cells_stay_queued_without_numeric_flags(raw):
    base = snapshot()
    base["pages"][0]["lines"][0].update(text=raw, confidence=0.99)
    base["tables"][0]["cells"][0]["column_header"] = False
    selected = selections()
    queue = review_queue(base, selections=selected)
    quantity = next(item for item in queue if item["kind"] == "quantity")
    assert quantity["target_id"] == "cell"
    assert quantity["state"] == "unparsed"
    assert quantity["value"] == raw
    assert quantity["reasons"] == ["unreviewed_cell_reading"]
    assert quantity["confidence"] == 0.99


def test_merely_proposed_cell_reading_stays_queued_until_source_inspection():
    base = snapshot()
    base["pages"][0]["lines"][0].update(text="cups", confidence=0.99)
    base["tables"][0]["cells"][0]["column_header"] = False
    selected = selections()
    first = revision(
        base,
        [change(base, "quantity", "cell", "2 cups", "proposed", selected=selected)],
        selected=selected,
    )
    quantity = next(
        item
        for item in review_queue(base, revisions=[first], selections=selected)
        if item["kind"] == "quantity"
    )
    assert quantity["state"] == "proposed"
    assert quantity["value"] == "2 cups"
    assert quantity["reasons"] == ["unreviewed_cell_reading"]
    assert quantity["evidence"][0]["text_sha256"] == hashlib.sha256(b"cups").hexdigest()


def test_report_escapes_source_proposals_reasons_and_reviewer_without_scripts():
    base = snapshot()
    proposal = change(base, value='<img src="remote" onerror="alert(1)">')
    proposal["reason"] = "</pre><script>reason</script>"
    first = make_revision(
        base, [proposal], reviewer={"kind": "human", "id": "<script>reviewer</script>"}
    )
    report = render_review_report(base, revisions=[first])
    assert "<script>" not in report and "<img " not in report
    assert "&lt;script&gt;" in report and "&lt;img" in report
    assert "default-src &#39;none&#39;" in report
    assert snapshot_digest(base) in report
    assert "source_page_sha256" in report and "polygon" in report
    assert "owner acceptance" in report
