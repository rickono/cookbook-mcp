"""Saved synthetic evidence only: no parser, renderer, OCR or model calls."""

from copy import deepcopy

import pytest
from test_transcription_boundaries import evidence, recipe

from cookbook.storage import LocalStore
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
        scope,
        "revoke",
        withdrawal_store=LocalStore(tmp_path / "objects"),
        actor=actor,
        reason="Known error",
        relates_to=approved["id"],
    )
    result = store.inspect(scope)
    assert result["eligible"] is False
    assert approved in result["history"] and draft in result["history"]
    assert result["candidate"]["snapshot"] == original
    assert result["candidate"]["revisions"] == [revision]
    assert snapshot == original


def scan_build(
    root,
    snapshot,
    *,
    original_bytes=b"Synthetic original evidence, never parsed",
    pages=(),
):
    """A saved-evidence build with opaque synthetic original bytes."""
    import hashlib

    from cookbook.build import add_content, create_index
    from cookbook.publication import Entry, Manifest
    from cookbook.quality import QUALITY_PATH, make_report
    from cookbook.storage import atomic_write, canonical, digest_file

    root.mkdir()
    original = root / "original.bin"
    original.write_bytes(original_bytes)
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    snapshot["edition"]["source_sha256"] = sha
    db = create_index(root / "index.sqlite", "a" * 32)
    source = "pdf:" + sha
    add_content(db, source, "PDF", sha, "backup/original.pdf", list(pages), [], [])
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
    tmp_path, keys, mint, monkeypatch, capsys
):
    import json
    from pathlib import Path

    from cookbook.library import Library
    from cookbook.publication import Runtime, publish
    from cookbook.quality import finalize
    from cookbook.storage import LocalStore, digest_file

    snapshot, selections = candidate()
    snapshot["pages"][0]["lines"][1]["text"] = "2 cups water; 2 cup saffron water"
    snapshot["pages"][0]["lines"][2]["text"] = "2 cups carrots"
    source, original = scan_build(
        tmp_path / "build",
        snapshot,
        pages=[
            {
                "id": "page1",
                "title": "Page 1",
                "text": "\n".join(l["text"] for l in snapshot["pages"][0]["lines"]),
                "locator": {"kind": "page", "physical_page": 1},
                "provenance": "legacy-transcription",
                "kind": "page",
                "images": [],
            }
        ],
    )
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
                "value": "1/2",
                "occurrence": {
                    "start": 14,
                    "end": 15,
                    "before": "2",
                    "selection_id": scope,
                    "role": "ingredient:saffron-water",
                    "cell_id": None,
                },
                "readings": [
                    {
                        "id": "synthetic-engine-a",
                        "value": "2",
                        "state": "rejected",
                        "reason": "Source disagrees",
                        "evidence": source_evidence(snapshot, ["p1-l1"]),
                    },
                    {
                        "id": "synthetic-engine-b",
                        "value": "1/2",
                        "state": "selected",
                        "reason": "Compared source",
                        "evidence": source_evidence(snapshot, ["p1-l1"]),
                    },
                ],
                "reason": "Synthetic source comparison",
                "evidence": source_evidence(snapshot, ["p1-l1"]),
            }
        ],
        selections=selections,
        reviewer={"kind": "agent", "id": "reader"},
    )
    from cookbook.cli import main

    request = tmp_path / "candidate-request.json"
    request.write_text(
        json.dumps(
            {"snapshot": snapshot, "selections": selections, "revisions": [correction]}
        )
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "cookbook",
            "review-transcription",
            "--review-store",
            str(store.path),
            "--candidate-file",
            str(request),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["candidate_id"]
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
    store.decide(
        scope,
        "clear_flag",
        actor={"kind": "human", "id": "owner"},
        reason="Source-reviewed occurrence is consistent",
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
    assert "2 cups water; 1/2 cup saffron water" in hit["snippet"]
    assert hit["citation"]["locator"]["physical_page"] == 1
    assert hit["citation"]["locator"]["content_review"]["decision_id"] == approval["id"]
    assert "1/2 cup" not in json.dumps(hit["citation"])
    assert (
        "1/2 cup saffron water"
        in lib.read_section(final.publication_id, "book", source, scope)["text"]
    )
    page = lib.read_section(final.publication_id, "book", source, "page1")
    assert page["text"] == ""
    assert (
        page["citation"]["locator"]["superseded_transcription"]["path"]
        == "quality/content-review.json"
    )
    assert all(
        r["citation"]["section_id"] != "page1" for r in lib.search("water")["results"]
    )
    history = json.loads(inputs["quality/content-review.json"].read_bytes())
    assert history["candidates"][0]["snapshot"] == snapshot
    assert history["candidates"][0]["revisions"] == [correction]
    assert (
        "2 cups water; 1/2 cup saffron water\n2 cups carrots"
        in lib.read_section(final.publication_id, "book", source, scope)["text"]
    )
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
                assert "2 cups water; 1/2 cup saffron water" in hit["snippet"]
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
                assert (
                    "2 cups water; 1/2 cup saffron water\n2 cups carrots"
                    in read.structured_content["text"]
                )
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


def test_source_reviewed_membership_can_complete_approval(tmp_path):
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
    store.decide(
        scope,
        "approve",
        actor={"kind": "human", "id": "owner"},
        reason="Complete",
        complete=True,
        evidence=source_evidence(snapshot, selections[0]["line_ids"]),
    )
    assert store.inspect(scope)["eligible"] is True


@pytest.mark.parametrize(
    "field", ["fts_source", "fts_title", "title", "kind", "ordinal", "provenance"]
)
def test_quality_gate_rejects_changed_projection_metadata(tmp_path, field):
    import json
    import sqlite3
    from pathlib import Path

    from cookbook.quality import check_publish_quality, finalize
    from cookbook.storage import IntegrityError, digest_file

    snapshot, scopes = candidate()
    scan_build(tmp_path / "build", snapshot)
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes)
    scope = scopes[0]["id"]
    store.decide(
        scope,
        "approve",
        actor={"kind": "human", "id": "owner"},
        reason="Reviewed",
        complete=True,
        evidence=source_evidence(snapshot, scopes[0]["line_ids"]),
    )
    out = tmp_path / "final"
    manifest = finalize(
        tmp_path / "build", tmp_path / "cache", out, transcription_review=store.path
    )
    inputs = {
        k: Path(v) for k, v in json.loads((out / "inputs.json").read_bytes()).items()
    }
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        if field.startswith("fts_"):
            column = {"fts_source": "source_id", "fts_title": "title"}[field]
            db.execute(
                f"update search set {column}=? where section_id=?", ("unrelated", scope)
            )
        else:
            db.execute(
                f"update sections set {field}=? where id=?",
                (42 if field == "ordinal" else "unrelated", scope),
            )
    sha, size = digest_file(inputs["runtime/index.sqlite"])
    manifest = manifest.model_copy(
        update={
            "files": [
                e.model_copy(update={"sha256": sha, "size": size})
                if e.path == "runtime/index.sqlite"
                else e
                for e in manifest.files
            ]
        }
    )
    with pytest.raises(IntegrityError, match="content approval"):
        check_publish_quality(manifest, inputs)


@pytest.mark.parametrize("consistent", [True, False])
def test_quantity_revision_requires_matching_effective_text(tmp_path, consistent):
    from test_transcription_review import snapshot as table_snapshot

    snapshot = table_snapshot()
    scopes = [
        {
            "id": "recipe",
            "kind": "recipe",
            "state": "candidate",
            "line_ids": ["l0", "l1", "l2"],
        }
    ]
    revision = make_revision(
        snapshot,
        [
            {
                "kind": "quantity",
                "target_id": "cell",
                "before_sha256": target_digest(
                    snapshot, "quantity", "cell", selections=scopes
                ),
                "state": "source_reviewed",
                "value": "1 cup" if consistent else "9 cups",
                "reason": "Compared source",
                "evidence": source_evidence(snapshot, ["l0"]),
            },
            {
                "kind": "line_text",
                "target_id": "l0",
                "before_sha256": target_digest(
                    snapshot, "line_text", "l0", selections=scopes
                ),
                "state": "source_reviewed",
                "value": "1 cup",
                "reason": "Compared source",
                "evidence": source_evidence(snapshot, ["l0"]),
            },
        ],
        selections=scopes,
        reviewer={"kind": "human", "id": "owner"},
    )
    store = ReviewStore(tmp_path / "review.json")
    store.save_candidate(snapshot, selections=scopes, revisions=[revision])
    store.decide(
        "recipe", "apply_draft", actor={"kind": "human", "id": "owner"}, reason="Apply"
    )

    def approve():
        return store.decide(
            "recipe",
            "approve",
            actor={"kind": "human", "id": "owner"},
            reason="Inspected",
            complete=True,
            evidence=source_evidence(snapshot, scopes[0]["line_ids"]),
        )

    if consistent:
        approve()
        assert (
            ReviewStore(store.path)
            .publication_sections()[0]["text"]
            .startswith("1 cup\n")
        )
    else:
        with pytest.raises(ValueError, match="quantity and effective text disagree"):
            approve()


def test_reviewed_correction_finalizes_over_registered_production_candidate(tmp_path):
    """Exact-import validation and reviewed overlays must coexist for one source."""
    from synthetic_scanned import pdf_sha256, registry
    from synthetic_scanned import snapshot as scanned_snapshot

    from cookbook.build import build_snapshot
    from cookbook.library import Library
    from cookbook.publication import Runtime, publish_build
    from cookbook.quality import finalize

    build = tmp_path / "build"
    build_snapshot(
        scanned_snapshot(tmp_path),
        [1],
        build,
        tmp_path / "cache",
        scanned=registry(tmp_path),
        progress=lambda event: None,
    )
    snapshot, selections = candidate()
    snapshot["edition"]["source_sha256"] = pdf_sha256()
    scope = selections[0]["id"]
    reviews = ReviewStore(tmp_path / "review.json")
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
                "value": "1/2 cup saffron water",
                "reason": "Synthetic source comparison",
                "evidence": source_evidence(snapshot, ["p1-l1"]),
            }
        ],
        selections=selections,
        reviewer={"kind": "human", "id": "owner"},
    )
    reviews.save_candidate(snapshot, selections=selections, revisions=[revision])
    reviews.decide(
        scope,
        "apply_draft",
        actor={"kind": "human", "id": "owner"},
        reason="Apply correction",
    )
    reviews.decide(
        scope,
        "approve",
        actor={"kind": "human", "id": "owner"},
        reason="Complete synthetic review",
        complete=True,
        evidence=source_evidence(snapshot, selections[0]["line_ids"]),
    )
    out = tmp_path / "finalized"
    finalize(build, tmp_path / "cache", out, transcription_review=reviews.path)
    objects = LocalStore(tmp_path / "objects")
    runtime = Runtime(objects, tmp_path / "runtime")
    assert publish_build(objects, out, activate=runtime.activate)["status"] == "active"
    lib = Library(runtime)
    hit = lib.search("saffron")["results"][0]
    assert hit["eligibility"]["eligible"]
    assert (
        "1/2 cup saffron water"
        in lib.read_section(
            None, hit["citation"]["book_id"], hit["citation"]["source_id"], scope
        )["text"]
    )
    assert not lib.search("plain soup")["results"]
    assert lib.search("colophon")["results"]
