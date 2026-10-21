"""A registered scanned candidate builds, passes the gate, publishes and reads back labelled."""

import json
import sqlite3

import pytest
from conftest import fixture_build
from synthetic_scanned import RECIPE, pack, pdf_sha256, registry, rows, snapshot

import cookbook.build as build_module
from cookbook.build import build_snapshot
from cookbook.library import Library
from cookbook.ocr import ReviewRequired
from cookbook.publication import Entry, Runtime, publish
from cookbook.quality import check_publish_quality
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


def test_candidate_and_legacy_ocr_for_one_book_is_refused(tmp_path):
    with pytest.raises(IntegrityError, match="legacy OCR"):
        build(tmp_path, registry(tmp_path), legacy_ocr_ids=[1])


def test_legacy_ocr_opt_in_still_goes_through_admission_checked_paged(tmp_path):
    with pytest.raises(AssertionError, match="must not render"):
        build(tmp_path, None, legacy_ocr_ids=[1])


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


@pytest.fixture
def mcp(tmp_path, monkeypatch, keys, mint):
    from PIL import Image
    from starlette.testclient import TestClient

    import cookbook.library as library_module
    from cookbook.server import JWTVerifier, create_app

    def fake_render(path, fmt, page, destination, edge=1600):
        Image.new("RGB", (round(edge * 0.75), edge), "white").save(destination, "PNG")

    monkeypatch.setattr(library_module, "render_page", fake_render)
    lib = publish_build(tmp_path, *build(tmp_path, registry(tmp_path))[:2])
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://service.example",
        subjects=["user-1"],
        public_key=keys[1],
    )
    headers = {"Authorization": "Bearer " + mint(aud="https://service.example")}
    with TestClient(create_app(lib, verifier), base_url="https://service.example") as c:
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
                        {
                            **ids,
                            "section_id": citation["section_id"],
                            "physical_pages": [1, 2],
                        }
                    ],
                },
            }
        },
    )
    assert card["recipe"]["source"]["citations"][0]["physical_pages"] == [1, 2]
