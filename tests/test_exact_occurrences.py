"""Synthetic public revision/admin workflows; no source processing."""

from copy import deepcopy

import pytest
from test_content_approval import candidate

from cookbook.transcription_review import (
    ReviewStore,
    make_revision,
    reviewed_view,
    source_evidence,
    target_digest,
)

ACTOR = {"kind": "human", "id": "owner"}


def repeated():
    snapshot, selections = candidate()
    snapshot["pages"][0]["lines"][1]["text"] = "2 cups water; 2 cups stock"
    snapshot["pages"][0]["lines"][2]["text"] = "2 cups carrots"
    return snapshot, selections


def occurrence(
    snapshot,
    selections,
    *,
    revisions=(),
    start=14,
    before="2",
    after="1",
    target="p1-l1",
):
    return {
        "kind": "line_text",
        "target_id": target,
        "before_sha256": target_digest(
            snapshot, "line_text", target, revisions=revisions, selections=selections
        ),
        "state": "source_reviewed",
        "value": after,
        "reason": "Compared synthetic source stock quantity",
        "evidence": source_evidence(snapshot, [target]),
        "occurrence": {
            "start": start,
            "end": start + len(before),
            "before": before,
            "selection_id": selections[0]["id"],
            "role": "ingredient:stock",
            "cell_id": None,
        },
    }


def revise(snapshot, selections, change, revisions=()):
    return make_revision(
        snapshot, [change], reviewer=ACTOR, revisions=revisions, selections=selections
    )


def test_exact_span_changes_only_second_equal_quantity_and_retains_source():
    snapshot, selections = repeated()
    original = deepcopy(snapshot)
    revision = revise(snapshot, selections, occurrence(snapshot, selections, start=14))
    view = reviewed_view(snapshot, selections=selections, revisions=[revision])
    assert view["lines"][1]["text"] == "2 cups water; 1 cups stock"
    assert view["lines"][2]["text"] == "2 cups carrots"
    assert snapshot == original
    assert revision["changes"][0]["occurrence"]["role"] == "ingredient:stock"


def readings(snapshot, statuses=("rejected", "selected")):
    return [
        {
            "id": "engine-a",
            "value": "2",
            "state": statuses[0],
            "reason": "Synthetic source disagrees",
            "evidence": source_evidence(snapshot, ["p1-l1"]),
        },
        {
            "id": "engine-b",
            "value": "1",
            "state": statuses[1],
            "reason": "Synthetic source supports",
            "evidence": source_evidence(snapshot, ["p1-l1"]),
        },
    ]


def test_competing_readings_and_selection_reasons_survive_administrative_restart(
    tmp_path,
):
    snapshot, selections = repeated()
    change = occurrence(snapshot, selections)
    change["readings"] = readings(snapshot)
    revision = revise(snapshot, selections, change)
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=selections, revisions=[revision])
    state = ReviewStore(store.path).inspect(selections[0]["id"])
    assert state["candidate"]["view"]["readings"][0]["alternatives"] == readings(
        snapshot
    )
    assert (
        state["candidate"]["view"]["lines"][1]["text"] == "2 cups water; 1 cups stock"
    )
    assert state["eligible"] is False


def test_quantity_metadata_cannot_clear_source_uncertainty(tmp_path):
    from test_transcription_review import change, snapshot
    from test_transcription_review import selections as selected

    base, scopes = snapshot(), selected()
    correction = change(base, "quantity", "cell", "1/2 cup", selected=scopes)
    revision = make_revision(base, [correction], reviewer=ACTOR, selections=scopes)
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(base, selections=scopes, revisions=[revision])
    with pytest.raises(ValueError, match="quantity.*effective text"):
        store.decide("main", "clear_flag", actor=ACTOR, reason="Metadata agrees")
    assert store.inspect("main")["history"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "stale",
        "missing_span",
        "ambiguous",
        "owner",
        "cell",
        "selected",
        "tie",
        "evidence",
    ],
)
def test_unmatched_or_inconsistent_targets_are_refused_without_a_draft(tmp_path, fault):
    snapshot, selections = repeated()
    change = occurrence(snapshot, selections)
    if fault == "stale":
        change["before_sha256"] = "f" * 64
    elif fault == "missing_span":
        change["occurrence"]["start"] = 100
    elif fault == "ambiguous":
        del change["occurrence"]["start"]
    elif fault == "owner":
        change["occurrence"]["selection_id"] = "other-recipe"
    elif fault == "cell":
        change["occurrence"]["cell_id"] = "other-cell"
    else:
        change["readings"] = readings(snapshot)
        if fault == "selected":
            change["readings"][1]["value"] = "3"
        elif fault == "tie":
            change["readings"][0]["state"] = "tied"
        else:
            change["readings"][1]["evidence"][0]["recognition_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        revise(snapshot, selections, change)
    assert (
        reviewed_view(snapshot, selections=selections)["lines"][1]["text"]
        == "2 cups water; 2 cups stock"
    )


def test_chained_spans_use_current_context_and_never_relocate_stale_offsets():
    snapshot, selections = repeated()
    first = revise(
        snapshot, selections, occurrence(snapshot, selections, start=0, after="1/2")
    )
    stale = occurrence(snapshot, selections, revisions=[first])
    with pytest.raises(ValueError, match="occurrence"):
        revise(snapshot, selections, stale, [first])
    second = revise(
        snapshot,
        selections,
        occurrence(snapshot, selections, revisions=[first], start=16),
        [first],
    )
    assert (
        reviewed_view(snapshot, selections=selections, revisions=[first, second])[
            "lines"
        ][1]["text"]
        == "1/2 cups water; 1 cups stock"
    )
    assert second["predecessor"] == first["id"]


def test_tied_and_unmatched_readings_remain_unresolved_despite_metadata_amendment(
    tmp_path,
):
    snapshot, selections = repeated()
    change = occurrence(snapshot, selections, after=None)
    change["state"] = "unresolved"
    change["readings"] = readings(snapshot, ("tied", "unmatched"))
    revision = revise(snapshot, selections, change)
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=selections, revisions=[revision])
    scope = selections[0]["id"]
    store.decide(
        scope,
        "metadata_amendment",
        actor=ACTOR,
        reason="Candidate agreement is not source review",
    )
    with pytest.raises(ValueError, match="unresolved"):
        store.decide(scope, "clear_flag", actor=ACTOR, reason="Clear label")
    store.decide(scope, "apply_draft", actor=ACTOR, reason="Retain unresolved draft")
    with pytest.raises(ValueError, match="unresolved"):
        store.decide(
            scope,
            "approve",
            actor=ACTOR,
            reason="Attempt approval",
            complete=True,
            evidence=source_evidence(snapshot, selections[0]["line_ids"]),
        )
    state = store.inspect(scope)
    assert (
        state["candidate"]["view"]["readings"][0]["alternatives"] == change["readings"]
    )
    assert store.publication_sections()[0]["text"] == ""


def test_repeated_occurrences_in_one_cell_have_distinct_source_positions():
    from test_transcription_review import selections as selected
    from test_transcription_review import snapshot

    base, scopes = snapshot(), selected()
    base["pages"][0]["lines"][0]["text"] = "2 cups water; 2 cups stock"
    change = occurrence(base, scopes, target="l0")
    change["target_id"] = "l0"
    change["before_sha256"] = target_digest(base, "line_text", "l0", selections=scopes)
    change["evidence"] = source_evidence(base, ["l0"])
    change["occurrence"]["cell_id"] = "cell"
    revision = revise(base, scopes, change)
    assert (
        reviewed_view(base, selections=scopes, revisions=[revision])["lines"][0]["text"]
        == "2 cups water; 1 cups stock"
    )


def test_recomputed_reading_and_revision_hashes_cannot_hide_selection_conflict():
    import hashlib

    from cookbook.storage import canonical

    snapshot, selections = repeated()
    change = occurrence(snapshot, selections)
    change["readings"] = readings(snapshot)
    revision = revise(snapshot, selections, change)
    revision["changes"][0]["readings"][1]["value"] = "3"
    revision["id"] = hashlib.sha256(
        canonical({k: v for k, v in revision.items() if k != "id"})
    ).hexdigest()
    with pytest.raises(ValueError, match="selected reading"):
        reviewed_view(snapshot, selections=selections, revisions=[revision])


def test_finalization_refuses_contradictory_quantity_even_when_pending(tmp_path):
    from test_content_approval import scan_build
    from test_transcription_review import change, snapshot
    from test_transcription_review import selections as selected

    from cookbook.quality import finalize

    base, scopes = snapshot(), selected()
    scan_build(tmp_path / "build", base)
    correction = change(base, "quantity", "cell", "1/2 cup", selected=scopes)
    revision = make_revision(base, [correction], reviewer=ACTOR, selections=scopes)
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(base, selections=scopes, revisions=[revision])
    assert (
        "quantity and effective text disagree: cell" in store.inspect("main")["reasons"]
    )
    with pytest.raises(ValueError, match="quantity.*effective text"):
        finalize(
            tmp_path / "build",
            tmp_path / "cache",
            tmp_path / "out",
            transcription_review=store.path,
        )


def test_reading_evidence_keeps_exact_identity_even_for_json_boolean_page():
    snapshot, selections = repeated()
    change = occurrence(snapshot, selections)
    change["readings"] = readings(snapshot)
    change["readings"][1]["evidence"][0]["physical_page"] = True
    with pytest.raises(ValueError, match="reading evidence"):
        revise(snapshot, selections, change)


def test_candidate_agreement_without_source_comparison_cannot_clear_or_approve(
    tmp_path,
):
    snapshot, selections = repeated()
    change = occurrence(snapshot, selections)
    change["state"] = "proposed"
    change["readings"] = readings(snapshot, ("rejected", "selected"))
    change["readings"][0]["value"] = "1"
    revision = revise(snapshot, selections, change)
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=selections, revisions=[revision])
    scope = selections[0]["id"]
    store.decide(scope, "apply_draft", actor=ACTOR, reason="Apply proposal")
    with pytest.raises(ValueError, match="proposed"):
        store.decide(scope, "clear_flag", actor=ACTOR, reason="Both candidates agree")
    with pytest.raises(ValueError, match="proposed"):
        store.decide(
            scope,
            "approve",
            actor=ACTOR,
            reason="Both candidates agree",
            complete=True,
            evidence=source_evidence(snapshot, selections[0]["line_ids"]),
        )
