"""Synthetic administrative evidence; no source processing or inference."""

from copy import deepcopy

import pytest
from test_transcription_boundaries import evidence, recipe, region

from cookbook.storage import LocalStore
from cookbook.transcription_review import ReviewStore, source_evidence

ACTOR = {"kind": "human", "id": "owner"}


def fixture():
    snapshot = evidence(
        recipe("Stew") + recipe("Neighbor", x=600),
        [region("list_item", "3. Serve with sauce.")],
        recipe("Sauce")
        + [
            region("passage", "A note", x=600),
            region("reference_entry", "Herbs", x=800, width=100),
            region("passage", "Optional spicy variation", x=600, y=400),
        ],
    )
    scopes = [
        {
            "id": "stew",
            "kind": "recipe",
            "state": "candidate",
            "line_ids": [*[f"p1-l{i}" for i in range(5)], "p2-l0"],
            "formulation": "small",
            "variation": "base",
            "required_content": [
                {
                    "selection_id": "sauce",
                    "formulation": "standard",
                    "variation": "base",
                    "scope": "whole",
                }
            ],
        },
        {
            "id": "neighbor",
            "kind": "recipe",
            "state": "candidate",
            "line_ids": [f"p1-l{i}" for i in range(5, 10)],
        },
        {
            "id": "sauce",
            "kind": "recipe",
            "state": "candidate",
            "line_ids": [f"p3-l{i}" for i in range(5)],
            "formulation": "standard",
            "variation": "base",
        },
        {"id": "note", "kind": "passage", "state": "candidate", "line_ids": ["p3-l5"]},
        {
            "id": "herbs",
            "kind": "reference_entry",
            "state": "candidate",
            "line_ids": ["p3-l6"],
        },
        {
            "id": "optional",
            "kind": "recipe",
            "state": "unresolved",
            "line_ids": ["p3-l7"],
        },
    ]
    return snapshot, scopes


def approve(store, snapshot, scopes, name):
    scope = next(s for s in scopes if s["id"] == name)
    return store.decide(
        name,
        "approve",
        actor=ACTOR,
        reason="Compared complete content and associations",
        complete=True,
        evidence=source_evidence(snapshot, scope["line_ids"]),
    )


def test_complete_recipe_needs_continuation_and_required_sauce(tmp_path):
    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    with pytest.raises(ValueError, match="support"):
        approve(store, snapshot, scopes, "stew")
    approve(store, snapshot, scopes, "sauce")
    with pytest.raises(ValueError, match="evidence"):
        store.decide(
            "stew",
            "approve",
            actor=ACTOR,
            reason="Only first page",
            complete=True,
            evidence=source_evidence(snapshot, scopes[0]["line_ids"][:-1]),
        )
    approval = approve(store, snapshot, scopes, "stew")
    assert store.inspect("stew")["eligible"]
    assert approval["dependency_bindings"][0]["selection_id"] == "sauce"
    assert not store.inspect("optional")["eligible"]


@pytest.mark.parametrize(
    "change",
    [
        "ingredient",
        "geometry",
        "order",
        "ownership",
        "support",
        "formulation",
        "variation",
    ],
)
def test_changed_scope_and_dependents_need_review_but_neighbors_keep_approval(
    tmp_path, change
):
    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    for name in ("sauce", "stew", "neighbor", "note", "herbs"):
        approve(store, snapshot, scopes, name)
    old = store.inspect("sauce")["approval"]
    changed, new_scopes = deepcopy(snapshot), deepcopy(scopes)
    if change == "ingredient":
        changed["pages"][2]["lines"][1]["text"] = "4 cups water"
    elif change == "geometry":
        changed["pages"][2]["lines"][1]["polygon"][0][0] += 1
    elif change == "order":
        new_scopes[2]["line_ids"][1:3] = reversed(new_scopes[2]["line_ids"][1:3])
    elif change == "ownership":
        new_scopes[2]["line_ids"].remove("p3-l1")
        new_scopes[3]["line_ids"].append("p3-l1")
    elif change == "support":
        new_scopes[2]["required_content"] = [{"selection_id": "note", "scope": "whole"}]
    else:
        new_scopes[2][change] = "alternative"
    store.save_candidate(changed, selections=new_scopes)
    assert not store.inspect("sauce")["eligible"]
    assert not store.inspect("stew")["eligible"]
    assert store.inspect("neighbor")["eligible"]
    assert store.inspect("herbs")["eligible"]
    assert store.inspect("note")["eligible"] == (change != "ownership")
    assert old in store.inspect("sauce")["history"]
    assert store.inspect("stew")["reasons"] == (
        ["required_support_selection_mismatch"]
        if change in {"formulation", "variation"}
        else ["required_support_pending:sauce"]
    )
    if change == "ownership":
        approve(store, changed, new_scopes, "note")
    if change in {"formulation", "variation"}:
        new_scopes[0]["required_content"][0][change] = "alternative"
        store.save_candidate(changed, selections=new_scopes)
    approve(store, changed, new_scopes, "sauce")
    assert not store.inspect("stew")["eligible"]
    approve(store, changed, new_scopes, "stew")
    assert store.inspect("stew")["eligible"]


def test_partial_support_findings_are_reusable_without_approving_complete_sauce(
    tmp_path,
):
    snapshot, scopes = fixture()
    scopes[0]["required_content"][0].update(scope="partial", line_ids=["p3-l1"])
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    finding = store.decide(
        "sauce",
        "review_portion",
        actor=ACTOR,
        reason="Compared required portion",
        evidence=source_evidence(snapshot, ["p3-l1"]),
    )
    approve(store, snapshot, scopes, "stew")
    assert not store.inspect("sauce")["eligible"]
    snapshot["pages"][2]["lines"][2]["text"] = "6 carrots"
    store.save_candidate(snapshot, selections=scopes)
    assert store.inspect("stew")["eligible"]
    assert finding in store.inspect("sauce")["history"]
    snapshot["pages"][2]["lines"][1]["text"] = "4 cups water"
    store.save_candidate(snapshot, selections=scopes)
    assert not store.inspect("stew")["eligible"]


def test_administrative_dependency_review_finalize_publish_and_mcp(
    tmp_path, keys, mint
):
    import json
    from pathlib import Path

    from test_content_approval import check_mcp, scan_build

    from cookbook.library import Library
    from cookbook.publication import Runtime, publish
    from cookbook.quality import finalize
    from cookbook.storage import LocalStore, digest_file

    snapshot, scopes = fixture()
    snapshot["pages"][0]["lines"][1]["text"] = "2 cups water; 1/2 cup saffron water"
    snapshot["pages"][0]["lines"][2]["text"] = "2 cups carrots"
    source, original = scan_build(tmp_path / "build", snapshot)
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    objects = LocalStore(tmp_path / "objects")
    runtime = Runtime(objects, tmp_path / "runtime")
    lib = Library(runtime)

    build_path = tmp_path / "build"

    def finish(name):
        out = tmp_path / name
        manifest = finalize(
            build_path, tmp_path / "cache", out, transcription_review=store.path
        )
        inputs = {
            k: Path(v)
            for k, v in json.loads((out / "inputs.json").read_bytes()).items()
        }
        _, version = objects.read_version("control/active.json")
        assert (
            publish(
                objects,
                manifest,
                inputs,
                expected_version=version,
                activate=runtime.activate,
            )["status"]
            == "active"
        )
        return manifest, inputs

    for name in ("sauce", "stew", "neighbor", "note", "herbs"):
        approve(store, snapshot, scopes, name)
    accepted, inputs = finish("accepted")
    old_index = digest_file(inputs["runtime/index.sqlite"])
    assert lib.search("saffron")["results"]
    snapshot["pages"][2]["lines"][1]["text"] = "4 cups water"
    store.save_candidate(snapshot, selections=scopes)
    # An alternative draft leaves the existing publication available.
    assert lib.search("saffron")["results"]
    pending, _ = finish("pending")
    assert not lib.search("saffron")["results"]
    assert lib.search("Neighbor")["results"]
    assert lib.search("Herbs")["results"]
    assert (
        lib.read_section(pending.publication_id, "book", source, "stew")["text"] == ""
    )
    approve(store, snapshot, scopes, "sauce")
    assert not store.inspect("stew")["eligible"]
    approve(store, snapshot, scopes, "stew")
    restored, _ = finish("restored")
    check_mcp(
        lib, keys, mint, restored.publication_id, pending.publication_id, source, "stew"
    )
    assert lib.read_section(restored.publication_id, "book", source, "stew")[
        "citation"
    ]["locator"]["physical_pages"] == [1, 2]
    assert digest_file(inputs["runtime/index.sqlite"]) == old_index
    assert inputs["backup/original.pdf"].read_bytes() == original
    assert accepted.publication_id != restored.publication_id

    # Display preferences leave source approval and the working publication valid.
    store.save_candidate(snapshot, selections=scopes, display={"theme": "large-type"})
    assert store.inspect("stew")["eligible"]
    assert lib.search("saffron")["results"]

    # Identical extraction bytes belong to a fresh run, requiring explicit review.
    store.save_candidate(snapshot, selections=scopes, extraction_run="synthetic-run-2")
    assert not store.inspect("stew")["eligible"]
    assert lib.search("saffron")["results"]
    extraction_pending, _ = finish("extraction-pending")
    assert not lib.search("saffron")["results"]
    for name in ("sauce", "stew", "neighbor", "note", "herbs"):
        approve(store, snapshot, scopes, name)
    extracted, _ = finish("extraction-approved")
    check_mcp(
        lib,
        keys,
        mint,
        extracted.publication_id,
        extraction_pending.publication_id,
        source,
        "stew",
    )

    # A replacement has distinct opaque source bytes, but equal candidate text.
    old_candidate = store.inspect("stew")["candidate"]["id"]
    old_source = source
    replacement = deepcopy(snapshot)
    replacement["edition"]["id"] = "synthetic-replacement"
    build_path = tmp_path / "replacement-build"
    source, _ = scan_build(
        build_path,
        replacement,
        original_bytes=b"Distinct synthetic replacement, never parsed",
    )
    store.save_candidate(
        replacement,
        selections=scopes,
        page_correspondences=[
            {
                "candidate_id": old_candidate,
                "old_page_id": "page-1",
                "new_page_id": "page-1",
            }
        ],
    )
    assert not store.inspect("stew")["eligible"]
    assert lib.search("saffron")["results"]
    replacement_pending, _ = finish("replacement-pending")
    assert not lib.search("saffron")["results"]
    assert lib.read_section(extracted.publication_id, "book", old_source, "stew")[
        "text"
    ]
    for name in ("sauce", "stew", "neighbor", "note", "herbs"):
        approve(store, replacement, scopes, name)
    replaced, _ = finish("replacement-approved")
    check_mcp(
        lib,
        keys,
        mint,
        replaced.publication_id,
        replacement_pending.publication_id,
        source,
        "stew",
    )
    citation = lib.read_section(replaced.publication_id, "book", source, "stew")[
        "citation"
    ]
    assert (
        citation["locator"]["content_review"]["edition_id"] == "synthetic-replacement"
    )

    # Restore earlier text via a checked undo, retaining the revoked decision.
    original_approval = store.inspect("stew")["approval"]
    changed = deepcopy(replacement)
    changed["pages"][0]["lines"][1]["text"] = "4 cups water; 1/2 cup saffron water"
    store.save_candidate(changed, selections=scopes)
    store.decide(
        "stew",
        "revoke",
        withdrawal_store=LocalStore(tmp_path / "objects"),
        actor=ACTOR,
        reason="Synthetic known defect",
        relates_to=original_approval["id"],
    )
    store.save_candidate(replacement, selections=scopes)
    store.decide(
        "stew",
        "undo",
        actor=ACTOR,
        reason="Compared restored source",
        relates_to=original_approval["id"],
        evidence=source_evidence(replacement, scopes[0]["line_ids"]),
    )
    undo_pending, _ = finish("undo-pending")
    assert not lib.search("saffron")["results"]
    request = {
        "actor": ACTOR,
        "reason": "Synthetic re-review",
        "complete": True,
        "reviewer_config": "human/model-2",
        "policy": "policy-2",
        "evidence": source_evidence(replacement, scopes[0]["line_ids"]),
    }
    with pytest.raises(ValueError, match="workflow validation"):
        store.decide("stew", "approve", **request)
    store.decide(
        "stew",
        "validate_workflow",
        actor=ACTOR,
        reason="Synthetic workflow validated",
        reviewer_config="human/model-2",
        policy="policy-2",
        evidence=[{"validation": "synthetic-record"}],
    )
    store.decide("stew", "approve", **request)
    undo_approved, _ = finish("undo-approved")
    check_mcp(
        lib,
        keys,
        mint,
        undo_approved.publication_id,
        undo_pending.publication_id,
        source,
        "stew",
    )
    review = lib.read_section(undo_approved.publication_id, "book", source, "stew")[
        "citation"
    ]["locator"]["content_review"]
    assert review["reviewer_config"] == "human/model-2"
    assert review["policy"] == "policy-2"
    assert store.inspect("sauce")["approval"]["policy"] == "standalone-content.v1"


def test_independent_passage_and_reference_keep_their_content_kind(tmp_path):
    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    for name in ("note", "herbs"):
        approve(store, snapshot, scopes, name)
    sections = {s["id"]: s for s in store.publication_sections()}
    assert sections["note"]["kind"] == "passage"
    assert sections["herbs"]["kind"] == "reference_entry"
    assert not sections["sauce"]["eligible"]


def test_partial_review_cannot_bypass_required_dependencies(tmp_path):
    snapshot, scopes = fixture()
    scopes[0]["required_content"][0].update(scope="partial", line_ids=["p3-l1"])
    scopes[2]["required_content"] = [{"selection_id": "note", "scope": "whole"}]
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    with pytest.raises(ValueError, match="support"):
        store.decide(
            "sauce",
            "review_portion",
            actor=ACTOR,
            reason="Partial review",
            evidence=source_evidence(snapshot, ["p3-l1"]),
        )


def test_revision_on_shared_page_preserves_unrelated_approval_and_findings(tmp_path):
    from cookbook.transcription_review import make_revision, target_digest

    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    for name in ("sauce", "stew", "neighbor"):
        approve(store, snapshot, scopes, name)
    finding = store.decide(
        "stew",
        "review_portion",
        actor=ACTOR,
        reason="Continuation inspected",
        evidence=source_evidence(snapshot, ["p2-l0"]),
    )
    revision = make_revision(
        snapshot,
        [
            {
                "kind": "line_text",
                "target_id": "p1-l1",
                "before_sha256": target_digest(
                    snapshot, "line_text", "p1-l1", selections=scopes
                ),
                "state": "source_reviewed",
                "value": "4 cups water",
                "reason": "Source comparison",
                "evidence": source_evidence(snapshot, ["p1-l1"]),
            }
        ],
        selections=scopes,
        reviewer=ACTOR,
    )
    store.save_candidate(snapshot, selections=scopes, revisions=[revision])
    assert not store.inspect("stew")["eligible"]
    assert store.inspect("neighbor")["eligible"]
    assert store.inspect("sauce")["eligible"]
    assert finding in store.inspect("stew")["history"]
    with pytest.raises(ValueError, match="apply_draft"):
        approve(store, snapshot, scopes, "stew")
    store.decide("stew", "apply_draft", actor=ACTOR, reason="Apply source correction")
    approve(store, snapshot, scopes, "stew")
    sections = {s["id"]: s for s in store.publication_sections()}
    assert "4 cups water" in sections["stew"]["text"]
    assert "2 cups water" in sections["neighbor"]["text"]


def test_recomputed_dependency_metadata_does_not_bypass_complete_check(tmp_path):
    import hashlib
    import json

    from cookbook.storage import canonical

    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    approve(store, snapshot, scopes, "sauce")
    approve(store, snapshot, scopes, "stew")
    data = store.export()
    event = data["decisions"][-1]
    event["dependency_bindings"] = []
    event["id"] = hashlib.sha256(
        canonical({k: v for k, v in event.items() if k != "id"})
    ).hexdigest()
    store.path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="dependency mismatch"):
        store.inspect("stew")


def test_approval_records_declared_required_content(tmp_path):
    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    approve(store, snapshot, scopes, "sauce")
    decision = approve(store, snapshot, scopes, "stew")
    assert decision["required_content"] == scopes[0]["required_content"]


def test_partial_support_rechecks_changed_reading_order(tmp_path):
    snapshot, scopes = fixture()
    scopes[0]["required_content"][0].update(
        scope="partial", line_ids=["p3-l1", "p3-l2"]
    )
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    store.decide(
        "sauce",
        "review_portion",
        actor=ACTOR,
        reason="Compared portion and order",
        evidence=source_evidence(snapshot, ["p3-l1", "p3-l2"]),
    )
    approve(store, snapshot, scopes, "stew")
    scopes[2]["line_ids"][1:3] = reversed(scopes[2]["line_ids"][1:3])
    store.save_candidate(snapshot, selections=scopes)
    assert not store.inspect("stew")["eligible"]


def test_revoking_current_support_invalidates_dependents(tmp_path):
    snapshot, scopes = fixture()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    for name in ("sauce", "stew", "neighbor"):
        approve(store, snapshot, scopes, name)
    store.decide(
        "sauce",
        "revoke",
        withdrawal_store=LocalStore(tmp_path / "objects"),
        actor=ACTOR,
        reason="Source review revoked",
    )
    assert not store.inspect("sauce")["eligible"]
    assert not store.inspect("stew")["eligible"]
    assert store.inspect("neighbor")["eligible"]


def test_invalidation_propagates_through_multiple_required_uses(tmp_path):
    snapshot, scopes = fixture()
    scopes[2]["required_content"] = [{"selection_id": "note", "scope": "whole"}]
    scopes[3]["required_content"] = [{"selection_id": "herbs", "scope": "whole"}]
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    for name in ("herbs", "note", "sauce", "stew", "neighbor"):
        approve(store, snapshot, scopes, name)
    snapshot["pages"][2]["lines"][6]["text"] = "Corrected herb reference"
    store.save_candidate(snapshot, selections=scopes)
    for name in ("herbs", "note", "sauce", "stew"):
        assert not store.inspect(name)["eligible"]
    assert store.inspect("neighbor")["eligible"]
    for name in ("herbs", "note", "sauce", "stew"):
        approve(store, snapshot, scopes, name)
    assert store.inspect("stew")["eligible"]
