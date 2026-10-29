"""A registered scanned candidate builds, passes the gate, publishes and reads back labelled."""

import json
import sqlite3

import pytest
from conftest import fixture_build
from synthetic_scanned import (
    RECIPE,
    SIDEBAR,
    SIDEBAR_TEXT,
    correction,
    pack,
    pdf_sha256,
    registry,
    rows,
    snapshot,
)

import cookbook.build as build_module
from cookbook.build import build_snapshot
from cookbook.library import Library
from cookbook.ocr import ReviewRequired
from cookbook.publication import Entry, Runtime, publish
from cookbook.quality import check_publish_quality
from cookbook.scanned import section_unit_id
from cookbook.storage import IntegrityError, LocalStore, digest_file

SUMMARY = "quality/transcription-summary.json"


@pytest.fixture(autouse=True)
def no_paged(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("scanned import must not render or OCR")

    monkeypatch.setattr(build_module, "paged", refuse)


def build(tmp_path, scanned, **kwargs):
    return build_snapshot(
        snapshot(tmp_path),
        [1],
        tmp_path / "build",
        tmp_path / "cache",
        progress=lambda event: None,
        scanned=scanned,
        **kwargs,
    )


def publish_build(tmp_path, m, inputs):
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    publish(store, m, inputs, expected_version=None, activate=runtime.activate)
    return Library(runtime)


def recipe_hit(lib, query):
    hits = lib.search(query)["results"]
    return next(h for h in hits if h["citation"]["section_title"] == "LENTIL SOUP")


def test_registered_candidate_publishes_and_reads_back_with_unapproved_label(tmp_path):
    m, inputs, stats = build(tmp_path, registry(tmp_path))
    assert stats[0]["ocr_mode"] == "scanned_candidate"
    lib = publish_build(tmp_path, m, inputs)
    hit = recipe_hit(lib, "plain soup")
    citation = hit["citation"]
    assert citation["source_id"] == "pdf:" + pdf_sha256()
    assert citation["locator"]["kind"] == "scanned-section"
    assert citation["locator"]["physical_pages"] == [1, 2]
    assert "page_id" not in citation
    label = citation["extraction"]["label"]
    assert label["approval"] == "unapproved"
    assert label["description"] == "agent transcription, unapproved"
    assert citation["extraction"]["provenance"] == "transcription"
    section = lib.read_section(
        None, citation["book_id"], citation["source_id"], citation["section_id"]
    )
    assert "Cumin | [unresolved u1: amount]" in section["text"]
    assert "5 tsp" not in section["text"] and "3 tsp" not in section["text"]
    assert section["citation"]["extraction"]["label"] == label


def test_section_covered_pages_do_not_duplicate_search_hits(tmp_path):
    lib = publish_build(tmp_path, *build(tmp_path, registry(tmp_path))[:2])
    titles = [
        h["citation"]["section_title"] for h in lib.search("plain soup")["results"]
    ]
    assert titles == ["LENTIL SOUP"]
    colophon = lib.search("colophon")["results"]
    assert [h["citation"]["section_title"] for h in colophon] == ["Page 4"]
    assert colophon[0]["citation"]["page_id"]


def test_book_lists_sections_and_scanned_coverage(tmp_path):
    lib = publish_build(tmp_path, *build(tmp_path, registry(tmp_path))[:2])
    book_id = lib.search("plain soup")["results"][0]["citation"]["book_id"]
    book = lib.get_book(None, book_id)
    assert [t["title"] for t in book["toc"]] == ["LENTIL SOUP", "ON LENTILS"]
    assert book["coverage"]["transcription"] == {
        "label": "agent transcription, unapproved",
        "pages_total": 4,
        "transcribed": 3,
        "blank": 1,
        "failed": 0,
        "unresolved": 1,
    }


def test_candidate_files_and_summary_are_backed_up_in_the_inventory(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    paths = {e.path: e.role for e in m.files}
    prefix = f"quality/scanned/{pdf_sha256()}/"
    assert paths[prefix + "candidate.json"] == "backup"
    assert paths[prefix + "pages.jsonl"] == "backup"
    assert paths["quality/transcription-summary.json"] == "backup"
    summary = json.loads(inputs["quality/transcription-summary.json"].read_bytes())
    assert summary["version"] == "transcription-summary.v1"
    assert [s["source_id"] for s in summary["sources"]] == ["pdf:" + pdf_sha256()]


def test_pdf_without_a_registered_candidate_is_refused(tmp_path):
    with pytest.raises(IntegrityError, match="scanned candidate"):
        build(tmp_path, None)
    assert not (tmp_path / "build").exists()


def test_candidate_for_a_different_page_count_is_refused_before_output(tmp_path):
    with pytest.raises(IntegrityError, match="page count"):
        build(tmp_path, registry(tmp_path, physical_pages=5))
    assert not (tmp_path / "build").exists()


def test_candidate_and_forced_ocr_for_one_book_is_refused(tmp_path):
    with pytest.raises(IntegrityError, match="forced OCR"):
        build(tmp_path, registry(tmp_path), force_ocr_ids=[1])


def test_forced_ocr_still_goes_through_admission_checked_paged(tmp_path):
    with pytest.raises(AssertionError, match="must not render"):
        build(tmp_path, None, force_ocr_ids=[1])


def test_build_has_no_legacy_ocr_opt_in(tmp_path, monkeypatch, capsys):
    import sys

    from cookbook import cli

    argv = ["cookbook", "build", "--snapshot", str(snapshot(tmp_path)), "--books", "1"]
    argv += ["--output", str(tmp_path / "build"), "--ocr-cache", str(tmp_path / "c")]
    argv += ["--legacy-ocr-books", "1"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        cli.main()
    assert "unrecognized arguments: --legacy-ocr-books" in capsys.readouterr().err
    with pytest.raises(TypeError):
        build(tmp_path / "direct", None, legacy_ocr_ids=[1])


def test_unregistered_change_to_candidate_rows_is_refused(tmp_path):
    data = rows()
    data["unresolved"][0]["section_id"] = RECIPE + "-missing"
    with pytest.raises(IntegrityError):
        build(tmp_path, registry(tmp_path, data))


# -- the publish gate accepts transcription text only through the transcription summary ----


def reseal(m, inputs):
    """Re-digest every inventory file, as a tamperer with write access to the build would."""
    entries = []
    for logical, path in sorted(inputs.items()):
        sha, size = digest_file(path)
        role = next((e.role for e in m.files if e.path == logical), "backup")
        entries.append(Entry(path=logical, sha256=sha, size=size, role=role))
    return m.model_copy(update={"files": entries})


def edit_index(inputs, sql, *args):
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        db.execute(sql, args)


def test_gate_accepts_an_untampered_scanned_build(tmp_path):
    check_publish_quality(*build(tmp_path, registry(tmp_path))[:2])


def test_gate_refuses_transcription_text_without_a_summary(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    del inputs[SUMMARY]
    with pytest.raises(ReviewRequired, match="transcription summary"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_a_changed_summary_file(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    path = inputs[SUMMARY]
    path.write_bytes(path.read_bytes().replace(b'"unresolved":1', b'"unresolved":0'))
    with pytest.raises(IntegrityError, match="summary changed"):
        check_publish_quality(m, inputs)
    with pytest.raises(IntegrityError, match="summary mismatch"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_index_text_that_differs_from_the_candidate(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    edit_index(
        inputs,
        "update sections set text=replace(text,'[unresolved u1: amount]','5 tsp')",
    )
    with pytest.raises(IntegrityError, match="scanned index"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_a_dropped_label(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    edit_index(inputs, "delete from transcription_units where rowid=1")
    with pytest.raises(IntegrityError, match="scanned index"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_a_missing_page_unit(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    edit_index(inputs, "delete from sections where ordinal=2")
    with pytest.raises(IntegrityError, match="scanned index"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_a_changed_backed_up_candidate(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    key = f"quality/scanned/{pdf_sha256()}/pages.jsonl"
    inputs[key].write_bytes(inputs[key].read_bytes().replace(b"3 tsp", b"5 tsp"))
    with pytest.raises(IntegrityError):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_a_consistently_replaced_candidate(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    data = rows()
    data["unresolved"][0]["reason"] = "a different freeze"
    for name, raw in pack(data, pdf_sha256()).items():
        inputs[f"quality/scanned/{pdf_sha256()}/{name}"].write_bytes(raw)
    with pytest.raises(IntegrityError, match="candidate changed"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_transcription_provenance_outside_a_summarised_source(tmp_path):
    m, inputs = fixture_build(tmp_path / "epub")
    edit_index(inputs, "update sections set provenance='transcription'")
    with pytest.raises(ReviewRequired, match="transcription summary"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_a_wrong_source_digest(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    original = next(k for k in inputs if k.endswith("scan.pdf"))
    other = tmp_path / "other.pdf"
    other.write_bytes(b"%PDF-another synthetic placeholder")
    inputs[original] = other
    with pytest.raises(IntegrityError, match="source digest"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_a_repeated_page_unit(tmp_path):
    m, inputs, _ = build(tmp_path, registry(tmp_path))
    edit_index(
        inputs,
        "insert into sections select id||'-again',source_id,ordinal+4,title,text,"
        "locator,provenance,kind,images from sections where ordinal=0",
    )
    with pytest.raises(IntegrityError, match="scanned index"):
        check_publish_quality(reseal(m, inputs), inputs)


# -- corrections from the ledger ---------------------------------------------------------

LEDGER = f"quality/scanned/{pdf_sha256()}/ledger.jsonl"


def corrected_build(tmp_path, *rows_):
    ledger = list(rows_) or [correction(1, "Salt | 2 tsp", "Salt | 2 tbsp")]
    return build(tmp_path, registry(tmp_path), ledger=ledger)


def test_build_applies_and_backs_up_the_ledger_and_reports_counts(tmp_path):
    applied = correction(1, "Salt | 2 tsp", "Salt | 2 tbsp")
    stale = correction(2, "Salt | 9 tsp", "Salt | 9 tbsp")
    ambiguous = correction(3, "lentils", "beans", page=2)
    other_book = correction(4, "Salt", "Pepper", source="e" * 64)
    m, inputs, stats = corrected_build(tmp_path, applied, stale, ambiguous, other_book)
    assert {e.path: e.role for e in m.files}[LEDGER] == "backup"
    stored = [json.loads(x) for x in inputs[LEDGER].read_bytes().splitlines()]
    assert [r["id"] for r in stored] == [applied["id"], stale["id"], ambiguous["id"]]
    assert stats[0]["corrections"] == {"applied": 1, "stale": 1, "ambiguous": 1}
    report = json.loads((tmp_path / "build" / "build-report.json").read_bytes())
    assert report["corrections"] == {"applied": 1, "stale": 1, "ambiguous": 1}
    assert [i["correction_id"] for i in report["owner_queue"]] == [ambiguous["id"]]
    check_publish_quality(m, inputs)


def test_build_report_gives_each_books_page_section_and_unresolved_counts(tmp_path):
    from cookbook.scanned import read_build_report

    build(tmp_path, registry(tmp_path))
    [source] = read_build_report(tmp_path / "build")["sources"]
    assert source["calibre_ids"] == [1]
    assert source["pages"] == {"total": 4, "transcribed": 3, "blank": 1, "failed": 0}
    assert source["sections"] == 2
    assert source["unresolved"] == 1


def test_a_build_without_corrections_stores_an_empty_ledger(tmp_path):
    _, inputs, stats = build(tmp_path, registry(tmp_path))
    assert inputs[LEDGER].read_bytes() == b""
    assert stats[0]["corrections"] == {"applied": 0, "stale": 0, "ambiguous": 0}


def test_build_command_reads_the_triage_ledger_and_prints_the_counts(
    tmp_path, monkeypatch, capsys
):
    import sys

    from cookbook import cli, ledger
    from cookbook.scanned import read_build_report

    entry = registry(tmp_path)[pdf_sha256()]
    reg = tmp_path / "registry.json"
    reg.write_text(
        json.dumps(
            {
                "version": "scanned-registry.v1",
                "sources": [
                    {
                        "source_sha256": pdf_sha256(),
                        "physical_pages": entry["physical_pages"],
                        "candidate": str(entry["candidate"]),
                    }
                ],
            }
        )
    )
    triaged = tmp_path / "ledger.jsonl"
    triaged.write_bytes(
        ledger.dump(
            [
                correction(1, "Salt | 2 tsp", "Salt | 2 tbsp"),
                correction(2, "lentils", "beans", page=2),
            ]
        )
    )
    out = tmp_path / "build"
    argv = ["cookbook", "build", "--snapshot", str(snapshot(tmp_path)), "--books", "1"]
    argv += ["--output", str(out), "--ocr-cache", str(tmp_path / "cache")]
    argv += ["--scanned-registry", str(reg), "--ledger", str(triaged)]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    printed = json.loads(capsys.readouterr().out.splitlines()[-1])
    counts = {"applied": 1, "stale": 0, "ambiguous": 1}
    assert printed["corrections"] == counts
    assert read_build_report(out)["corrections"] == counts


def rewrite_ledger(inputs, **changes):
    [row] = [json.loads(x) for x in inputs[LEDGER].read_bytes().splitlines()]
    inputs[LEDGER].write_bytes(json.dumps(row | changes).encode() + b"\n")


def test_gate_refuses_an_applied_correction_for_another_source(tmp_path):
    m, inputs, _ = corrected_build(tmp_path)
    other = "e" * 64
    rewrite_ledger(inputs, source_sha256=other, source_id="pdf:" + other)
    with pytest.raises(IntegrityError, match="does not bind to its source"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_an_applied_correction_moved_to_another_page(tmp_path):
    m, inputs, _ = corrected_build(tmp_path)
    rewrite_ledger(inputs, physical_page=2)
    with pytest.raises(IntegrityError, match="does not bind to its page"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_a_dropped_ledger(tmp_path):
    m, inputs, _ = corrected_build(tmp_path)
    del inputs[LEDGER]
    with pytest.raises(ReviewRequired, match="ledger"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_gate_refuses_corrected_text_the_ledger_does_not_explain(tmp_path):
    m, inputs, _ = corrected_build(tmp_path)
    edit_index(inputs, "update sections set text=replace(text,'2 tbsp','3 tbsp')")
    with pytest.raises(IntegrityError, match="scanned index"):
        check_publish_quality(reseal(m, inputs), inputs)


def sidebar_reworded():
    """The sidebar's text part reads differently from its page row (the page lacks it)."""
    data = rows()
    sidebar = next(s for s in data["sections"] if s["id"] == SIDEBAR)
    sidebar["parts"][1]["text"] = SIDEBAR_TEXT.replace("shape.", "shape well.")
    return data


def test_gate_accepts_a_correction_applied_only_to_its_cited_section(tmp_path):
    sidebar = section_unit_id("pdf:" + pdf_sha256(), SIDEBAR)
    c = correction(1, "shape well", "form well", page=2, section_id=sidebar)
    m, inputs, stats = build(
        tmp_path, registry(tmp_path, sidebar_reworded()), ledger=[c]
    )
    assert stats[0]["corrections"] == {"applied": 1, "stale": 0, "ambiguous": 0}
    check_publish_quality(m, inputs)


def test_gate_refuses_a_section_only_correction_moved_to_another_section(tmp_path):
    sidebar = section_unit_id("pdf:" + pdf_sha256(), SIDEBAR)
    c = correction(1, "shape well", "form well", page=2, section_id=sidebar)
    m, inputs, _ = build(tmp_path, registry(tmp_path, sidebar_reworded()), ledger=[c])
    rewrite_ledger(inputs, section_id=section_unit_id("pdf:" + pdf_sha256(), RECIPE))
    with pytest.raises(IntegrityError, match="does not bind to its page"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_legacy_ocr_sections_still_need_their_assessments(tmp_path):
    m, inputs = fixture_build(tmp_path / "epub")
    edit_index(inputs, "update sections set provenance='ocr'")
    with pytest.raises(ReviewRequired, match="missing OCR assessment"):
        check_publish_quality(reseal(m, inputs), inputs)


def test_epub_still_wins_over_a_registered_candidate(tmp_path):
    from test_extract import make_epub

    _, _, stats = build_snapshot(
        snapshot(tmp_path, epub=make_epub),
        [1],
        tmp_path / "build",
        tmp_path / "cache",
        progress=lambda event: None,
        scanned=registry(tmp_path),
    )
    assert stats[0]["format"] == "EPUB"
    assert not (tmp_path / "build" / "transcription-summary.json").exists()


def test_registry_file_names_candidates_relative_to_itself(tmp_path):
    from cookbook.scanned import read_registry

    mapping = registry(tmp_path)
    entry = mapping[pdf_sha256()]
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "version": "scanned-registry.v1",
                "sources": [
                    {
                        "source_sha256": pdf_sha256(),
                        "physical_pages": entry["physical_pages"],
                        "candidate": entry["candidate"].name,
                    }
                ],
            }
        )
    )
    assert read_registry(path) == mapping
    m, inputs, _ = build(tmp_path, read_registry(path))
    check_publish_quality(m, inputs)


# -- served through the MCP app ----------------------------------------------------------


def rpc(client, headers, method, params):
    return client.post(
        "/mcp",
        headers={**headers, "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    ).json()["result"]


def tool(client, headers, name, arguments):
    r = rpc(client, headers, "tools/call", {"name": name, "arguments": arguments})
    assert not r.get("isError"), r
    return r["structuredContent"]


def serve(lib, keys, mint):
    from starlette.testclient import TestClient

    from cookbook.server import JWTVerifier, create_app

    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://service.example",
        subjects=["user-1"],
        public_key=keys[1],
    )
    headers = {"Authorization": "Bearer " + mint(aud="https://service.example")}
    client = TestClient(create_app(lib, verifier), base_url="https://service.example")
    return client, headers


def scanned_library(tmp_path, monkeypatch, **kwargs):
    from PIL import Image

    import cookbook.library as library_module

    def fake_render(path, fmt, page, destination, edge=1600):
        Image.new("RGB", (round(edge * 0.75), edge), "white").save(destination, "PNG")

    monkeypatch.setattr(library_module, "render_page", fake_render)
    return publish_build(tmp_path, *build(tmp_path, registry(tmp_path), **kwargs)[:2])


@pytest.fixture
def mcp(tmp_path, monkeypatch, keys, mint):
    client, headers = serve(scanned_library(tmp_path, monkeypatch), keys, mint)
    with client as c:
        yield c, headers


@pytest.fixture
def epub_mcp(tmp_path, keys, mint):
    lib = publish_build(tmp_path, *fixture_build(tmp_path / "epub"))
    client, headers = serve(lib, keys, mint)
    with client as c:
        yield c, headers


SALT_FIX = correction(1, "Salt | 2 tsp", "Salt | 2 tbsp")


@pytest.fixture
def corrected_mcp(tmp_path, monkeypatch, keys, mint):
    lib = scanned_library(tmp_path, monkeypatch, ledger=[SALT_FIX])
    client, headers = serve(lib, keys, mint)
    with client as c:
        yield c, headers


def test_instructions_explain_the_unapproved_label_and_markers(mcp):
    client, headers = mcp
    init = rpc(
        client,
        headers,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    text = init["instructions"]
    assert "agent transcription, unapproved" in text
    assert "[unresolved" in text and "get_page" in text
    assert "check_regions" in text and "crop_confirmed" in text


def test_agent_reads_a_scanned_recipe_through_the_mcp(mcp):
    client, headers = mcp
    found = tool(client, headers, "search_library", {"query": "plain soup"})
    citation = found["results"][0]["citation"]
    assert citation["extraction"]["label"]["approval"] == "unapproved"
    ids = {k: citation[k] for k in ("publication_id", "book_id", "source_id")}
    book = tool(
        client,
        headers,
        "get_book",
        {"publication_id": ids["publication_id"], "book_id": ids["book_id"]},
    )
    assert [t["title"] for t in book["toc"]][:1] == ["LENTIL SOUP"]
    section = tool(
        client, headers, "read_section", {**ids, "section_id": citation["section_id"]}
    )
    text = section["text"]
    assert text.index("LENTIL SOUP") < text.index("A plain soup") < text.index("Simmer")
    assert "Cumin | [unresolved u1: amount]" in text and "5 tsp" not in text
    assert section["citation"]["locator"]["physical_pages"] == [1, 2]
    assert section["citation"]["locator"]["printed_pages_unverified"] == ["12", "13"]
    assert section["citation"]["extraction"]["label"]["samples"] == 3
    page = tool(
        client,
        headers,
        "get_page",
        {**ids, "physical_page": 1, "region": [0.1, 0.4, 0.9, 0.7]},
    )
    assert page["region"] == [0.1, 0.4, 0.9, 0.7]
    assert "Cumin | [unresolved u1: amount]" in page["text"]
    assert page["citation"]["extraction"]["label"]["description"] == (
        "agent transcription, unapproved"
    )
    card = tool(
        client,
        headers,
        "show_recipe",
        {
            "recipe": {
                "title": "Lentil soup",
                "steps": [
                    {
                        "title": "Simmer",
                        "ingredients": ["1½ cups lentils"],
                        "method": "Simmer for 30 minutes.",
                    }
                ],
                "source": {
                    "kind": "book",
                    "label": "Synthetic Lentils, Test Author",
                    "citations": [
                        # A wrong page list from the agent is replaced by the locator's.
                        {
                            **ids,
                            "section_id": citation["section_id"],
                            "physical_pages": [7],
                        },
                        {**ids, "section_id": citation["section_id"]},
                    ],
                },
            }
        },
    )
    cited = card["recipe"]["source"]["citations"]
    assert [c["physical_pages"] for c in cited] == [[1, 2], [1, 2]]


def test_a_ledger_correction_is_served_through_the_mcp(corrected_mcp):
    client, headers = corrected_mcp
    found = tool(client, headers, "search_library", {"query": "tbsp"})
    [hit] = found["results"]
    citation = hit["citation"]
    assert citation["section_title"] == "LENTIL SOUP"
    # Reported against an earlier publication; it binds by source digest and page.
    assert citation["publication_id"] != SALT_FIX["publication_id"]
    applied = [{"id": SALT_FIX["id"], "reviewer": SALT_FIX["reviewer"]}]
    assert citation["extraction"]["corrections"] == applied
    assert tool(client, headers, "search_library", {"query": "2 tsp"})["results"] == []
    ids = {k: citation[k] for k in ("publication_id", "book_id", "source_id")}
    section = tool(
        client, headers, "read_section", {**ids, "section_id": citation["section_id"]}
    )
    assert "Salt | 2 tbsp" in section["text"] and "2 tsp" not in section["text"]
    assert "Cumin | [unresolved u1: amount]" in section["text"]
    assert section["citation"]["extraction"]["corrections"] == applied
    page = tool(client, headers, "get_page", {**ids, "physical_page": 1})
    assert "Salt | 2 tbsp" in page["text"] and "2 tsp" not in page["text"]
    assert page["citation"]["extraction"]["corrections"] == applied
    other = tool(client, headers, "get_page", {**ids, "physical_page": 2})
    assert "corrections" not in other["citation"]["extraction"]
    info = tool(client, headers, "get_publication_info", {})
    assert info["counts"]["applied_corrections"] == 1


# -- check regions and publication counts (#50) ------------------------------------------


def ids_of(citation):
    return {k: citation[k] for k in ("publication_id", "book_id", "source_id")}


def find(client, headers, query):
    return tool(client, headers, "search_library", {"query": query})["results"][0][
        "citation"
    ]


def read(client, headers, citation):
    return tool(
        client,
        headers,
        "read_section",
        {**ids_of(citation), "section_id": citation["section_id"]},
    )


def test_read_section_returns_a_check_region_per_review_box_and_unresolved_item(mcp):
    client, headers = mcp
    regions = read(client, headers, find(client, headers, "plain soup"))[
        "check_regions"
    ]
    assert sorted((r["state"], r["physical_page"], r["box"]) for r in regions) == [
        ("crop_confirmed", 1, [0.1, 0.4, 0.9, 0.7]),
        ("unresolved", 1, [0.1, 0.4, 0.9, 0.7]),
    ]
    unresolved = next(r for r in regions if r["state"] == "unresolved")
    assert unresolved["unresolved_id"] == "u1" and unresolved["code"] == "amount"


def test_each_check_region_zooms_through_get_page_unchanged(mcp):
    client, headers = mcp
    citation = find(client, headers, "plain soup")
    for region in read(client, headers, citation)["check_regions"]:
        page = tool(
            client,
            headers,
            "get_page",
            {
                **ids_of(citation),
                "physical_page": region["physical_page"],
                "region": region["box"],
            },
        )
        assert page["region"] == region["box"]
        assert page["citation"]["locator"]["physical_page"] == region["physical_page"]


def test_a_scanned_section_without_quantities_has_no_check_regions(mcp):
    client, headers = mcp
    citation = find(client, headers, "green lentils")
    assert citation["section_title"] == "ON LENTILS"
    assert read(client, headers, citation)["check_regions"] == []


def test_epub_read_section_retains_content_with_explicit_eligibility(epub_mcp):
    client, headers = epub_mcp
    section = read(client, headers, find(client, headers, "bean"))
    assert set(section) == {
        "citation",
        "text",
        "text_offset",
        "next_offset",
        "kind",
        "image_ids",
        "eligibility",
    }
    assert set(section["citation"]["extraction"]) == {"provenance", "version"}


def test_recipe_card_drops_physical_pages_for_a_section_that_is_not_scanned(epub_mcp):
    client, headers = epub_mcp
    c = find(client, headers, "bean")
    ids = {k: c[k] for k in ("publication_id", "book_id", "source_id", "section_id")}
    recipe = {
        "title": "Beans",
        "steps": [{"title": "Warm", "ingredients": ["beans"], "method": "Warm."}],
        "source": {
            "kind": "book",
            "label": "Synthetic beans",
            "citations": [{**ids, "physical_pages": [3]}],
        },
    }
    card = tool(client, headers, "show_recipe", {"recipe": recipe})
    assert card["recipe"]["source"]["citations"] == [ids]


def test_publication_info_counts_scanned_books_corrections_and_unresolved_items(mcp):
    client, headers = mcp
    info = tool(client, headers, "get_publication_info", {})
    assert info["counts"] == {
        "scanned_books": 1,
        "applied_corrections": 0,
        "unresolved_items": 1,
    }


def test_publication_info_counts_are_zero_without_scanned_books(epub_mcp):
    client, headers = epub_mcp
    info = tool(client, headers, "get_publication_info", {})
    assert info["counts"] == {
        "scanned_books": 0,
        "applied_corrections": 0,
        "unresolved_items": 0,
    }
