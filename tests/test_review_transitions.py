"""Synthetic saved-evidence transitions through the administrative review boundary."""

import pytest
from test_content_dependencies import ACTOR, approve, fixture

from cookbook.transcription_review import ReviewStore, source_evidence


def test_new_workflow_requires_validation_without_erasing_earlier_policy(tmp_path):
    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    old = approve(store, snapshot, scopes, "neighbor")
    request = {
        "actor": ACTOR,
        "reason": "Synthetic comparison",
        "complete": True,
        "evidence": source_evidence(snapshot, scopes[2]["line_ids"]),
        "reviewer_config": "human/model-v2",
        "policy": "policy-v2",
    }
    with pytest.raises(ValueError, match="workflow validation"):
        store.decide("sauce", "approve", **request)
    assert store.inspect("neighbor")["approval"] == old
    validation = store.decide(
        "sauce",
        "validate_workflow",
        actor=ACTOR,
        reason="Synthetic workflow checks",
        reviewer_config="human/model-v2",
        policy="policy-v2",
        evidence=[{"validation": "synthetic-check-record"}],
    )
    approval = store.decide("sauce", "approve", **request)
    assert approval["workflow_validation_id"] == validation["id"]
    assert ReviewStore(store.path).inspect("sauce")["eligible"]
    assert store.inspect("neighbor")["approval"]["policy"] == "standalone-content.v1"
    with pytest.raises(ValueError, match="workflow validation"):
        store.decide("sauce", "approve", **{**request, "policy": "policy-v3"})
    with pytest.raises(ValueError, match="agent"):
        store.decide(
            "sauce",
            "validate_workflow",
            actor={"kind": "agent", "id": "model"},
            reason="Cannot self authorize",
            evidence=[{"validation": "x"}],
        )


def test_replacement_scan_links_pages_but_requires_fresh_comparison(tmp_path):
    from copy import deepcopy

    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    old_id = store.save_candidate(snapshot, selections=scopes)
    old = approve(store, snapshot, scopes, "neighbor")
    replacement = deepcopy(snapshot)
    replacement["edition"]["source_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="distinct book-edition"):
        store.save_candidate(replacement, selections=scopes)
    replacement["edition"]["id"] = "replacement-scan"
    links = [{"candidate_id": old_id, "old_page_id": "page-1", "new_page_id": "page-1"}]
    store.save_candidate(replacement, selections=scopes, page_correspondences=links)
    state = store.inspect("neighbor")
    assert not state["eligible"]
    assert state["candidate"]["page_correspondences"] == links
    assert old in state["history"]
    with pytest.raises(ValueError, match="source evidence"):
        store.decide(
            "neighbor",
            "approve",
            actor=ACTOR,
            reason="Old evidence",
            complete=True,
            evidence=source_evidence(snapshot, scopes[1]["line_ids"]),
        )
    new = approve(store, replacement, scopes, "neighbor")
    assert new["candidate_id"] != old["candidate_id"]
    assert store.inspect("neighbor")["eligible"]


def test_identical_text_new_run_needs_explicit_review_display_does_not(tmp_path):
    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes, extraction_run="run-1")
    old = approve(store, snapshot, scopes, "neighbor")
    store.save_candidate(
        snapshot,
        selections=scopes,
        extraction_run="run-1",
        display={"theme": "large-type", "label": "Readable title"},
    )
    assert store.inspect("neighbor")["approval"] == old
    store.save_candidate(snapshot, selections=scopes, extraction_run="run-2")
    assert not store.inspect("neighbor")["eligible"]
    new = approve(store, snapshot, scopes, "neighbor")
    assert store.inspect("neighbor")["eligible"]
    citation = next(s for s in store.publication_sections() if s["id"] == "neighbor")[
        "locator"
    ]["content_review"]
    assert citation["extraction_run"] == "run-2"
    assert citation["source_sha256"] == snapshot["edition"]["source_sha256"]
    assert citation["reviewer_config"] == new["reviewer_config"]
    assert citation["policy"] == new["policy"]


def test_undo_records_source_scope_dependencies_and_cannot_revive_approval(tmp_path):
    from copy import deepcopy

    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    approve(store, snapshot, scopes, "sauce")
    original = approve(store, snapshot, scopes, "stew")
    changed = deepcopy(snapshot)
    changed["pages"][0]["lines"][1]["text"] = "4 cups water"
    store.save_candidate(changed, selections=scopes)
    store.decide(
        "stew",
        "revoke",
        actor=ACTOR,
        reason="Defect in original approval",
        relates_to=original["id"],
    )
    store.save_candidate(snapshot, selections=scopes)
    assert not store.inspect("stew")["eligible"]
    undo = store.decide(
        "stew",
        "undo",
        actor=ACTOR,
        reason="Restore inspected original",
        relates_to=original["id"],
        evidence=source_evidence(snapshot, scopes[0]["line_ids"]),
    )
    assert undo["relates_to"] == original["id"]
    assert undo["dependency_bindings"][0]["selection_id"] == "sauce"
    assert undo["undo_checks"]["target_revoked"] is True
    assert not ReviewStore(store.path).inspect("stew")["eligible"]
    assert approve(store, snapshot, scopes, "stew")["id"] != original["id"]
    assert store.inspect("stew")["eligible"]


def test_restoring_bytes_without_undo_cannot_resurrect_stale_approval(tmp_path):
    from copy import deepcopy

    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    approve(store, snapshot, scopes, "neighbor")
    changed = deepcopy(snapshot)
    changed["pages"][0]["lines"][6]["text"] = "4 cups water"
    store.save_candidate(changed, selections=scopes)
    store.save_candidate(snapshot, selections=scopes)
    assert not store.inspect("neighbor")["eligible"]
    with pytest.raises(ValueError, match="undo"):
        approve(store, snapshot, scopes, "neighbor")


def test_new_reviewer_cannot_inherit_manual_workflow_identity(tmp_path):
    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    approve(store, snapshot, scopes, "neighbor")
    with pytest.raises(ValueError, match="workflow validation"):
        store.decide(
            "sauce",
            "approve",
            actor={"kind": "human", "id": "second-reviewer"},
            reason="Different reviewer",
            complete=True,
            evidence=source_evidence(snapshot, scopes[2]["line_ids"]),
        )
