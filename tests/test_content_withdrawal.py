"""Saved synthetic evidence only: no parser, rendering, OCR or inference."""

import json
from pathlib import Path

from test_content_approval import scan_build
from test_content_dependencies import ACTOR, approve, fixture

from cookbook.library import Library
from cookbook.publication import Runtime, publish
from cookbook.quality import finalize
from cookbook.storage import LocalStore
from cookbook.transcription_review import ReviewStore, source_evidence


def test_confirmed_error_withdraws_published_content_and_required_dependents(
    tmp_path, keys, mint, monkeypatch
):
    snapshot, scopes = fixture()
    pages = [
        {
            "id": f"page-{n}",
            "title": f"Page {n}",
            "text": "Historical Sauce transcription",
            "locator": {"kind": "page", "physical_page": n},
            "provenance": "transcription",
            "kind": "page",
            "images": [],
        }
        for n in (1, 2, 3)
    ]
    pages.append({**pages[-1], "id": "legacy-sauce", "kind": "recipe"})
    source, original = scan_build(tmp_path / "build", snapshot, pages=pages)
    reviews = ReviewStore(tmp_path / "review.json")
    reviews.save_candidate(snapshot, selections=scopes)
    for name in ("sauce", "stew", "neighbor"):
        approve(reviews, snapshot, scopes, name)
    objects = LocalStore(tmp_path / "objects")
    runtime = Runtime(objects, tmp_path / "runtime")
    lib = Library(runtime)
    out = tmp_path / "accepted"
    manifest = finalize(
        tmp_path / "build", tmp_path / "cache", out, transcription_review=reviews.path
    )
    inputs = {
        k: Path(v) for k, v in json.loads((out / "inputs.json").read_bytes()).items()
    }
    publish(objects, manifest, inputs, expected_version=None, activate=runtime.activate)
    accepted_pointer = runtime.active()
    hit = lib.search("Stew")["results"][0]
    assert (
        lib.read_section(manifest.publication_id, "book", source, "stew", limit=10)[
            "next_offset"
        ]
        == 10
    )
    from PIL import Image
    from starlette.testclient import TestClient
    from test_reports import rpc

    from cookbook.reports import ReportSink
    from cookbook.server import JWTVerifier, create_app

    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://service.example",
        subjects=["user-1"],
        public_key=keys[1],
    )
    app = create_app(lib, verifier, ReportSink(LocalStore(tmp_path / "reports")))
    headers = {"Authorization": "Bearer " + mint(aud="https://service.example")}
    with TestClient(app, base_url="https://service.example") as client:
        reported = rpc(
            client,
            headers,
            "report_transcription_issue",
            {
                "publication_id": manifest.publication_id,
                "book_id": "book",
                "source_id": source,
                "physical_page": 3,
                "quoted_text": "Historical Sauce transcription",
                "proposed_text": "Possible alternative",
                "kind": "quantity",
            },
        )
        assert not reported["isError"]
        assert lib.search("Stew")["results"]
    # Opening a competing candidate has no effect on the accepted publication.
    from copy import deepcopy

    draft = deepcopy(snapshot)
    draft["pages"][2]["lines"][1]["text"] = "4 cups water"
    accepted_candidate = reviews.inspect("sauce")["candidate"]["id"]
    reviews.save_candidate(draft, selections=scopes)
    assert lib.search("Stew")["results"]
    # Administrative action, separate from the read-only content/report interface.
    event = reviews.decide(
        "sauce",
        "confirm_error",
        actor=ACTOR,
        reason="Confirmed wrong quantity",
        withdrawal_store=objects,
        candidate_id=accepted_candidate,
        evidence=source_evidence(snapshot, scopes[2]["line_ids"]),
    )
    from cookbook.withdrawal import record_withdrawal

    record_withdrawal(objects, event)
    assert not ReviewStore(reviews.path).inspect("sauce")["eligible"]
    assert not reviews.inspect("stew")["eligible"]
    assert reviews.inspect("neighbor")["eligible"]
    assert not lib.search("Sauce")["results"]
    assert (
        lib.read_section(manifest.publication_id, "book", source, "page-3")["text"]
        == ""
    )
    assert not lib.search("Stew", publication_id=manifest.publication_id)["results"]
    assert lib.search("Neighbor")["results"]
    for offset in (0, 10):
        read = lib.read_section(
            hit["citation"]["publication_id"], "book", source, "stew", offset=offset
        )
        assert read["text"] == ""
        assert read["next_offset"] is None
        assert not read["eligibility"]["eligible"]
        assert (
            read["eligibility"]["withdrawals"][0]["reason"]
            == "Confirmed wrong quantity"
        )
        assert read["citation"]["locator"]["physical_pages"] == [1, 2]
    assert (
        lib.get_artifact(manifest.publication_id, "book", source, "stew")["text"] == ""
    )
    assert lib.get_artifact(manifest.publication_id, "book", source, "original")[
        "bytes"
    ] == len(original)
    assert event in reviews.export()["decisions"]
    assert runtime.active()["publication_id"] == manifest.publication_id

    def fake_render(path, fmt, page, destination, edge=1600):
        Image.new("RGB", (10, 10), "white").save(destination, "PNG")

    monkeypatch.setattr("cookbook.library.render_page", fake_render)
    app = create_app(lib, verifier)
    with TestClient(app, base_url="https://service.example") as client:
        for pub in (None, manifest.publication_id):
            found = rpc(
                client,
                headers,
                "search_library",
                {"query": "Stew", "publication_id": pub},
            )
            assert not found["isError"] and found["structuredContent"]["results"] == []
        for name, offset in (("stew", 0), ("stew", 10), ("sauce", 0), ("page-3", 0)):
            read = rpc(
                client,
                headers,
                "read_section",
                {
                    "publication_id": manifest.publication_id,
                    "book_id": "book",
                    "source_id": source,
                    "section_id": name,
                    "offset": offset,
                },
            )
            assert not read["isError"]
            assert read["structuredContent"]["text"] == ""
            assert not read["structuredContent"]["eligibility"]["eligible"]
        found = rpc(client, headers, "search_library", {"query": "Neighbor"})
        assert found["structuredContent"]["results"]
        page = rpc(
            client,
            headers,
            "get_page",
            {
                "publication_id": manifest.publication_id,
                "book_id": "book",
                "source_id": source,
                "physical_page": 3,
            },
        )
        assert not page["isError"]
        assert page["structuredContent"]["citation"]["locator"]["physical_page"] == 3
    # A new approval for the repaired sauce alone cannot restore the stew.
    approve(reviews, draft, scopes, "sauce")
    assert not reviews.inspect("stew")["eligible"]
    approve(reviews, draft, scopes, "stew")
    assert reviews.inspect("stew")["eligible"]
    assert not lib.search("Stew")["results"]  # Approval still needs finalization.
    repaired_out = tmp_path / "repaired"
    repaired = finalize(
        tmp_path / "build",
        tmp_path / "cache",
        repaired_out,
        transcription_review=reviews.path,
    )
    repaired_inputs = {
        k: Path(v)
        for k, v in json.loads((repaired_out / "inputs.json").read_bytes()).items()
    }
    _, version = objects.read_version("control/active.json")
    publish(
        objects,
        repaired,
        repaired_inputs,
        expected_version=version,
        activate=runtime.activate,
    )
    assert lib.search("Stew")["results"]
    assert (
        "4 cups water"
        in lib.read_section(repaired.publication_id, "book", source, "sauce")["text"]
    )
    # Rollback and a new reader process both retain the current withdrawal.
    runtime.activate(accepted_pointer)
    assert not Library(Runtime(objects, runtime.root)).search("Stew")["results"]
    assert inputs["backup/original.pdf"].read_bytes() == original
    import pytest

    from cookbook.storage import IntegrityError, canonical
    from cookbook.withdrawal import KEY

    _, version = objects.read_version(KEY)
    objects.put_bytes(
        KEY, canonical([dict(event, reason="Corrupted decision")]), expected=version
    )
    with pytest.raises(IntegrityError, match="invalid"):
        lib.read_section(manifest.publication_id, "book", source, "stew")

    def unavailable(key):
        raise OSError("Injected control-store outage")

    monkeypatch.setattr(objects, "read_version", unavailable)
    with pytest.raises(OSError, match="outage"):
        lib.search("Stew")


def test_cli_requires_shared_enforcement_and_can_retry_recorded_withdrawal(
    tmp_path, monkeypatch, capsys
):
    from cookbook.cli import main
    from cookbook.withdrawal import current_withdrawals

    snapshot, scopes = fixture()
    reviews = ReviewStore(tmp_path / "review.json")
    reviews.save_candidate(snapshot, selections=scopes)
    approve(reviews, snapshot, scopes, "sauce")
    request = tmp_path / "decision.json"
    request.write_text(
        json.dumps(
            {
                "selection_id": "sauce",
                "action": "confirm_error",
                "actor": ACTOR,
                "reason": "Confirmed wrong quantity",
                "evidence": source_evidence(snapshot, scopes[2]["line_ids"]),
            }
        )
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "cookbook",
            "review-transcription",
            "--review-store",
            str(reviews.path),
            "--decision-file",
            str(request),
            "--withdrawal-store",
            str(tmp_path / "objects"),
        ],
    )
    main()
    event = json.loads(capsys.readouterr().out)
    assert current_withdrawals(LocalStore(tmp_path / "objects")) == [event]
    monkeypatch.setattr(
        "sys.argv",
        [
            "cookbook",
            "review-transcription",
            "--review-store",
            str(reviews.path),
            "--withdrawal-id",
            event["id"],
            "--withdrawal-store",
            str(tmp_path / "objects"),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out) == event
    assert current_withdrawals(LocalStore(tmp_path / "objects")) == [event]


def test_confirmed_error_cannot_succeed_without_shared_enforcement(tmp_path):
    import pytest

    snapshot, scopes = fixture()
    reviews = ReviewStore(tmp_path / "review.json")
    reviews.save_candidate(snapshot, selections=scopes)
    with pytest.raises(ValueError, match="shared publication store"):
        reviews.decide(
            "sauce",
            "confirm_error",
            actor=ACTOR,
            reason="Error",
            evidence=source_evidence(snapshot, scopes[2]["line_ids"]),
        )
    assert reviews.export()["decisions"] == []


def test_failed_enforcement_is_retryable_and_corrupt_decisions_are_refused(tmp_path):
    import pytest

    from cookbook.storage import IntegrityError
    from cookbook.withdrawal import current_withdrawals, record_withdrawal

    class UnavailableStore(LocalStore):
        def put_bytes(self, *args, **kwargs):
            raise OSError("Injected control-store outage")

    snapshot, scopes = fixture()
    reviews = ReviewStore(tmp_path / "review.json")
    reviews.save_candidate(snapshot, selections=scopes)
    approve(reviews, snapshot, scopes, "sauce")
    objects = UnavailableStore(tmp_path / "objects")
    with pytest.raises(OSError, match="outage"):
        reviews.decide(
            "sauce",
            "confirm_error",
            actor=ACTOR,
            reason="Confirmed error",
            evidence=source_evidence(snapshot, scopes[2]["line_ids"]),
            withdrawal_store=objects,
        )
    saved = ReviewStore(reviews.path).inspect("sauce")
    assert not saved["eligible"]
    event = saved["history"][-1]
    working = LocalStore(tmp_path / "objects")
    record_withdrawal(working, event)
    record_withdrawal(working, event)
    assert current_withdrawals(working) == [event]
    corrupted = dict(event, reason="Changed after signing")
    with pytest.raises(IntegrityError, match="invalid"):
        record_withdrawal(working, corrupted)


def test_partial_required_support_and_transitive_dependents_are_withdrawn(tmp_path):
    snapshot, scopes = fixture()
    scopes[0]["required_content"][0].update(scope="partial", line_ids=["p3-l1"])
    scopes[2]["required_content"] = [{"selection_id": "note", "scope": "whole"}]
    reviews = ReviewStore(tmp_path / "review.json")
    reviews.save_candidate(snapshot, selections=scopes)
    approve(reviews, snapshot, scopes, "note")
    finding = reviews.decide(
        "sauce",
        "review_portion",
        actor=ACTOR,
        reason="Compared source",
        evidence=source_evidence(snapshot, ["p3-l1"]),
    )
    dependent = approve(reviews, snapshot, scopes, "stew")
    approve(reviews, snapshot, scopes, "neighbor")
    event = reviews.decide(
        "note",
        "confirm_error",
        actor=ACTOR,
        reason="Confirmed error",
        evidence=source_evidence(snapshot, scopes[3]["line_ids"]),
        withdrawal_store=LocalStore(tmp_path / "objects"),
    )
    assert finding["id"] in event["affected_decisions"]
    assert dependent["id"] in event["affected_decisions"]
    assert not reviews.inspect("stew")["eligible"]
    assert reviews.inspect("neighbor")["eligible"]
