"""Saved synthetic evidence only: no parser, renderer, OCR or model calls."""

from copy import deepcopy

import pytest
from test_transcription_boundaries import evidence, recipe

from cookbook.transcription_boundaries import propose_boundaries
from cookbook.transcription_review import (
    ReviewStore,
    make_revision,
    source_evidence,
    target_digest,
)


def candidate():
    snapshot = evidence(recipe("Synthetic soup"))
    selections = propose_boundaries(snapshot)["selections"]
    return snapshot, selections


def test_draft_clearance_approval_and_revocation_have_distinct_durable_history(
    tmp_path,
):
    snapshot, selections = candidate()
    store = ReviewStore(tmp_path / "review.json")
    scope = selections[0]["id"]
    original = deepcopy(snapshot)
    store.save_candidate(snapshot, selections=selections)
    assert store.inspect(scope)["eligible"] is False
    change = {
        "kind": "line_text",
        "target_id": "p1-l1",
        "before_sha256": target_digest(
            snapshot, "line_text", "p1-l1", selections=selections
        ),
        "state": "source_reviewed",
        "value": "1/2 cup saffron water",
        "reason": "Compared synthetic original",
        "evidence": source_evidence(snapshot, ["p1-l1"]),
    }
    revision = make_revision(
        snapshot,
        [change],
        selections=selections,
        reviewer={"kind": "agent", "id": "reader"},
    )
    store.save_candidate(snapshot, selections=selections, revisions=[revision])
    actor = {"kind": "human", "id": "owner"}
    draft = store.decide(scope, "apply_draft", actor=actor, reason="Use candidate")
    store.decide(scope, "clear_flag", actor=actor, reason="Bookkeeping")
    assert store.inspect(scope)["eligible"] is False
    with pytest.raises(ValueError, match="agent"):
        store.decide(
            scope,
            "approve",
            actor={"kind": "agent", "id": "reader"},
            reason="Read it",
            complete=True,
        )
    approved = store.decide(
        scope,
        "approve",
        actor=actor,
        reason="Inspected complete standalone recipe",
        complete=True,
        evidence=source_evidence(snapshot, selections[0]["line_ids"]),
    )
    assert ReviewStore(store.path).inspect(scope)["eligible"] is True
    assert approved["predecessor"] != draft["id"]
    store.decide(
        scope, "revoke", actor=actor, reason="Known error", relates_to=approved["id"]
    )
    result = store.inspect(scope)
    assert result["eligible"] is False
    assert approved in result["history"] and draft in result["history"]
    assert result["candidate"]["snapshot"] == original
    assert result["candidate"]["revisions"] == [revision]
    assert snapshot == original


def scan_build(root, snapshot):
    """A saved-evidence build with opaque synthetic original bytes."""
    import hashlib

    from cookbook.build import add_content, create_index
    from cookbook.publication import Entry, Manifest
    from cookbook.quality import QUALITY_PATH, make_report
    from cookbook.storage import atomic_write, canonical, digest_file

    root.mkdir()
    original = root / "original.bin"
    original.write_bytes(b"Synthetic original evidence, never parsed")
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    snapshot["edition"]["source_sha256"] = sha
    db = create_index(root / "index.sqlite", "a" * 32)
    source = "pdf:" + sha
    add_content(db, source, "PDF", sha, "backup/original.pdf", [], [], [])
    db.execute(
        "insert into books values(?,?,?,?,?,?)",
        ("book", 1, "Synthetic soup", "[]", "[]", source),
    )
    db.commit()
    db.close()
    report = root / "ocr-review.json"
    atomic_write(report, canonical(make_report("a" * 32, [])))
    inputs = {
        "runtime/index.sqlite": root / "index.sqlite",
        "backup/original.pdf": original,
        QUALITY_PATH: report,
    }
    manifest = Manifest(
        publication_id="a" * 32,
        created_at="2026-10-28T00:00:00Z",
        files=[
            Entry(
                path=k,
                sha256=digest_file(v)[0],
                size=digest_file(v)[1],
                role="runtime" if k.startswith("runtime") else "backup",
            )
            for k, v in inputs.items()
        ],
    )
    atomic_write(root / "manifest.json", canonical(manifest.model_dump()))
    atomic_write(
        root / "inputs.json", canonical({k: str(v) for k, v in inputs.items()})
    )
    return source, original.read_bytes()


def test_review_finalize_publish_search_read_and_citations_preserve_evidence(
    tmp_path, keys, mint
):
    import json
    from pathlib import Path

    from cookbook.library import Library
    from cookbook.publication import Runtime, publish
    from cookbook.quality import finalize
    from cookbook.storage import LocalStore, digest_file

    snapshot, selections = candidate()
    source, original = scan_build(tmp_path / "build", snapshot)
    scope = selections[0]["id"]
    store = ReviewStore(tmp_path / "review.json")
    correction = make_revision(
        snapshot,
        [
            {
                "kind": "line_text",
                "target_id": "p1-l1",
                "before_sha256": target_digest(
                    snapshot, "line_text", "p1-l1", selections=selections
                ),
                "state": "source_reviewed",
                "value": "1/2 cup saffron water",
                "reason": "Synthetic source comparison",
                "evidence": source_evidence(snapshot, ["p1-l1"]),
            }
        ],
        selections=selections,
        reviewer={"kind": "agent", "id": "reader"},
    )
    store.save_candidate(snapshot, selections=selections, revisions=[correction])
    objects = LocalStore(tmp_path / "objects")
    runtime = Runtime(objects, tmp_path / "runtime")
    lib = Library(runtime)

    def finish(name, version):
        out = tmp_path / name
        m = finalize(
            tmp_path / "build", tmp_path / "cache", out, transcription_review=store.path
        )
        inputs = {
            k: Path(v)
            for k, v in json.loads((out / "inputs.json").read_bytes()).items()
        }
        assert (
            publish(
                objects, m, inputs, expected_version=version, activate=runtime.activate
            )["status"]
            == "active"
        )
        return m, inputs

    pending, _ = finish("pending", None)
    assert lib.search("saffron")["results"] == []
    response = lib.read_section(pending.publication_id, "book", source, scope)
    assert response["text"] == "" and response["eligibility"]["eligible"] is False
    store.decide(
        scope,
        "apply_draft",
        actor={"kind": "human", "id": "owner"},
        reason="Apply inspected correction",
    )
    approval = store.decide(
        scope,
        "approve",
        actor={"kind": "human", "id": "owner"},
        reason="Compared entire standalone recipe",
        complete=True,
        evidence=source_evidence(snapshot, selections[0]["line_ids"]),
    )
    _, version = objects.read_version("control/active.json")
    final, inputs = finish("approved", version)
    before = digest_file(inputs["runtime/index.sqlite"])
    hit = lib.search("saffron")["results"][0]
    assert hit["eligibility"]["eligible"] is True
    assert hit["citation"]["locator"]["physical_page"] == 1
    assert hit["citation"]["locator"]["content_review"]["decision_id"] == approval["id"]
    assert "1/2 cup" not in json.dumps(hit["citation"])
    assert (
        "1/2 cup saffron water"
        in lib.read_section(final.publication_id, "book", source, scope)["text"]
    )
    history = json.loads(inputs["quality/content-review.json"].read_bytes())
    assert history["candidates"][0]["snapshot"] == snapshot
    assert history["candidates"][0]["revisions"] == [correction]
    assert inputs["backup/original.pdf"].read_bytes() == original
    store.save_candidate(snapshot, selections=selections)
    assert store.inspect(scope)["eligible"] is False
    assert (
        lib.search("saffron")["results"]
        and digest_file(inputs["runtime/index.sqlite"]) == before
    )
    assert lib.read_section(pending.publication_id, "book", source, scope)["text"] == ""
    check_mcp(
        lib, keys, mint, final.publication_id, pending.publication_id, source, scope
    )


def test_administrative_cli_records_and_inspects_saved_candidate(
    tmp_path, monkeypatch, capsys
):
    import json

    from cookbook.cli import main

    snapshot, selections = candidate()
    request = tmp_path / "candidate.json"
    request.write_text(
        json.dumps({"snapshot": snapshot, "selections": selections, "revisions": []})
    )
    path = tmp_path / "review.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "cookbook",
            "review-transcription",
            "--review-store",
            str(path),
            "--candidate-file",
            str(request),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["candidate_id"]
    monkeypatch.setattr(
        "sys.argv",
        [
            "cookbook",
            "review-transcription",
            "--review-store",
            str(path),
            "--selection-id",
            selections[0]["id"],
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["reasons"] == [
        "exact_complete_content_approval_required"
    ]


def test_supporting_content_and_metadata_cannot_approve_a_standalone_scope(tmp_path):
    snapshot, selections = candidate()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=selections)
    scope = selections[0]["id"]
    actor = {"kind": "human", "id": "owner"}
    store.decide(scope, "metadata_amendment", actor=actor, reason="Repair status label")
    with pytest.raises(ValueError, match="supporting content"):
        store.decide(
            scope,
            "approve",
            actor=actor,
            reason="Requires sauce",
            complete=True,
            required_content=["sauce"],
            evidence=source_evidence(snapshot, selections[0]["line_ids"]),
        )
    assert store.inspect(scope)["eligible"] is False


def test_recomputed_metadata_cannot_disagree_with_effective_reading(tmp_path):
    import hashlib
    import json

    from cookbook.storage import canonical

    snapshot, selections = candidate()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=selections)
    data = store.export()
    row = data["candidates"][0]
    row["view"]["lines"][1]["text"] = "Invented correction"
    row["id"] = hashlib.sha256(
        canonical({k: v for k, v in row.items() if k != "id"})
    ).hexdigest()
    store.path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="metadata disagree"):
        store.inspect(selections[0]["id"])


def check_mcp(lib, keys, mint, approved, pending, source, scope):
    """Exercise the supported authenticated MCP transport, never rendering a page."""
    import asyncio
    import socket
    import threading
    import time

    import httpx2
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from cookbook.server import JWTVerifier, create_app

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/mcp"
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience=url,
        subjects=["user-1"],
        public_key=keys[1],
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(lib, verifier),
            host="127.0.0.1",
            port=port,
            log_level="critical",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started

        async def exercise():
            async with (
                httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + mint(aud=url)}
                ) as http,
                streamable_http_client(url, http_client=http) as transport,
                ClientSession(*transport) as session,
            ):
                await session.initialize()
                found = await session.call_tool("search_library", {"query": "saffron"})
                assert not found.is_error
                hit = found.structured_content["results"][0]
                assert hit["eligibility"]["eligible"] is True
                assert hit["citation"]["locator"]["physical_page"] == 1
                read = await session.call_tool(
                    "read_section",
                    {
                        "publication_id": approved,
                        "book_id": "book",
                        "source_id": source,
                        "section_id": scope,
                    },
                )
                assert not read.is_error
                assert "1/2 cup saffron water" in read.structured_content["text"]
                draft = await session.call_tool(
                    "read_section",
                    {
                        "publication_id": pending,
                        "book_id": "book",
                        "source_id": source,
                        "section_id": scope,
                    },
                )
                assert not draft.is_error
                assert draft.structured_content["text"] == ""
                assert draft.structured_content["eligibility"]["eligible"] is False

        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_recomputed_decision_hash_cannot_turn_partial_review_into_approval(tmp_path):
    import hashlib
    import json

    from cookbook.storage import canonical

    snapshot, selections = candidate()
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=selections)
    scope = selections[0]["id"]
    store.decide(
        scope,
        "approve",
        actor={"kind": "human", "id": "owner"},
        reason="Source inspection",
        complete=True,
        evidence=source_evidence(snapshot, selections[0]["line_ids"]),
    )
    data = store.export()
    event = data["decisions"][0]
    event["complete"] = False
    event["id"] = hashlib.sha256(
        canonical({k: v for k, v in event.items() if k != "id"})
    ).hexdigest()
    store.path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="approval"):
        store.inspect(scope)


def test_source_reviewed_proposal_needs_separate_draft_application(tmp_path):
    snapshot, selections = candidate()
    revision = make_revision(
        snapshot,
        [
            {
                "kind": "line_text",
                "target_id": "p1-l1",
                "before_sha256": target_digest(
                    snapshot, "line_text", "p1-l1", selections=selections
                ),
                "state": "source_reviewed",
                "value": "1 cup water",
                "reason": "Compared source",
                "evidence": source_evidence(snapshot, ["p1-l1"]),
            }
        ],
        selections=selections,
        reviewer={"kind": "human", "id": "owner"},
    )
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=selections, revisions=[revision])
    with pytest.raises(ValueError, match="apply_draft"):
        store.decide(
            selections[0]["id"],
            "approve",
            actor={"kind": "human", "id": "owner"},
            reason="Compared source",
            complete=True,
            evidence=source_evidence(snapshot, selections[0]["line_ids"]),
        )


def test_unsupported_relationship_correction_remains_pending(tmp_path):
    snapshot, selections = candidate()
    scope = selections[0]["id"]
    revision = make_revision(
        snapshot,
        [
            {
                "kind": "membership",
                "target_id": "p1-l1",
                "before_sha256": target_digest(
                    snapshot, "membership", "p1-l1", selections=selections
                ),
                "state": "source_reviewed",
                "value": [scope],
                "reason": "Ownership review",
                "evidence": source_evidence(snapshot, ["p1-l1"]),
            }
        ],
        selections=selections,
        reviewer={"kind": "human", "id": "owner"},
    )
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=selections, revisions=[revision])
    store.decide(
        scope,
        "apply_draft",
        actor={"kind": "human", "id": "owner"},
        reason="Apply ownership review",
    )
    with pytest.raises(ValueError, match="unsupported correction scope"):
        store.decide(
            scope,
            "approve",
            actor={"kind": "human", "id": "owner"},
            reason="Complete",
            complete=True,
            evidence=source_evidence(snapshot, selections[0]["line_ids"]),
        )
    assert store.inspect(scope)["eligible"] is False
