"""Synthetic native EPUB publish/read checks; never invoke PDF, OCR or models."""

import json
import sqlite3
import uuid
import zipfile
from pathlib import Path

import pytest

from cookbook.book_build import structure_build, validate_model
from cookbook.book_model import MODEL_PATH, REPORT_PATH, BookModel
from cookbook.build import add_content, create_index
from cookbook.extract import epub
from cookbook.publication import Entry, Manifest, Runtime, publish
from cookbook.quality import QUALITY_PATH, make_report
from cookbook.recipe import RecipeCitation
from cookbook.storage import (
    IntegrityError,
    LocalStore,
    atomic_write,
    canonical,
    digest_file,
)


def native_build(root):
    root.mkdir()
    pub, book = uuid.uuid4().hex, uuid.uuid4().hex
    original = root / "book.epub"
    body = "Ingredients and method " + ("αβ🍲 &amp; beans " * 3000)
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "book.opf",
            '<package><manifest><item id="one" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/><itemref idref="one"/></spine></package>',
        )
        archive.writestr(
            "chapter.xhtml",
            f'<html><body><h1 id="beans">Beans</h1><p>Serve with <em>cold</em> glass water.</p><p>{body}</p><table><tr><td rowspan="2">2 tbsp</td><td>Beans</td></tr><tr><td>Salt</td></tr></table></body></html>',
        )
    sha = digest_file(original)[0]
    source = "epub:" + sha
    index_path = root / "index.sqlite"
    db = create_index(index_path, pub)
    sections, images, toc = epub(original, source, lambda data: "unused")
    add_content(db, source, "EPUB", sha, "backup/book.epub", sections, images, toc)
    db.execute(
        "insert into books values(?,?,?,?,?,?)",
        (book, 1, "Synthetic Beans", '["Fixture"]', "[]", source),
    )
    db.commit()
    db.close()
    atomic_write(root / "ocr-review.json", canonical(make_report(pub, [])))
    inputs = {
        "runtime/index.sqlite": index_path,
        "backup/book.epub": original,
        QUALITY_PATH: root / "ocr-review.json",
    }
    entries = [
        Entry(
            path=k,
            sha256=digest_file(v)[0],
            size=v.stat().st_size,
            role="runtime" if k.startswith("runtime/") else "backup",
        )
        for k, v in inputs.items()
    ]
    manifest = Manifest(publication_id=pub, created_at="2026-10-11", files=entries)
    atomic_write(root / "manifest.json", canonical(manifest.model_dump()))
    atomic_write(
        root / "inputs.json", canonical({k: str(v) for k, v in inputs.items()})
    )
    return manifest, inputs, book


@pytest.fixture
def structured(tmp_path):
    base, _, book = native_build(tmp_path / "base")
    manifest, report = structure_build(
        tmp_path / "base", tmp_path / "structured", progress=lambda event: None
    )
    return base, manifest, report, book, tmp_path / "structured"


def test_whole_book_capture_and_bounded_utf8_continuation(structured):
    base, manifest, report, book, root = structured
    model = BookModel(root / "whole-books.sqlite", manifest.publication_id)
    described = model.describe(book)
    assert len(described["reading_order"]) == 2
    assert (
        described["reading_order"][0]["document_id"]
        == described["reading_order"][1]["document_id"]
    )
    assert described["coverage"]["semantic_state"] == "not_assessed"
    with sqlite3.connect(root / "whole-books.sqlite") as db:
        expected = "".join(
            r[0]
            for r in db.execute(
                "select text from nodes where node_kind='text' order by preorder"
            )
        )
        assert any(
            "cold glass" in r[0] for r in db.execute("select text from search_units")
        )
    for occurrence in described["reading_order"]:
        texts = []
        cursor = None
        pages = 0
        while True:
            response = model.read(
                book, occurrence["id"], cursor, byte_budget=4096, node_budget=3
            )
            assert len(canonical(response)) <= 4096
            assert response["citations"][0]["reading_occurrence_id"] == occurrence["id"]
            assert len(response["nodes"]) <= 3
            texts.extend(
                x["node"]["text"]
                for x in response["nodes"]
                if x["node"]["kind"] == "text"
            )
            pages += 1
            cursor = response["next_cursor"]
            if cursor is None:
                break
            assert pages < 200
        assert "".join(texts) == expected and pages > 10
    assert base.publication_id != manifest.publication_id
    assert report["validation"]["editions"] == 1


def test_reader_rejects_foreign_book_target_and_continuation(structured):
    _, manifest, _, book, root = structured
    model = BookModel(root / "whole-books.sqlite", manifest.publication_id)
    targets = model.describe(book)["reading_order"]
    first = model.read(book, targets[0]["id"], node_budget=1)
    with pytest.raises(IntegrityError, match="continuation"):
        model.read(book, targets[1]["id"], first["next_cursor"])
    with pytest.raises(IntegrityError):
        model.read(uuid.uuid4().hex, targets[0]["id"])
    with pytest.raises(IntegrityError):
        model.read(book, "../../private")


def test_publication_activation_requires_complete_model_and_index_preparation(
    structured, tmp_path
):
    _, manifest, _, book, root = structured
    inputs = {
        k: Path(v) for k, v in json.loads((root / "inputs.json").read_bytes()).items()
    }
    store, runtime = (
        LocalStore(tmp_path / "store"),
        Runtime(LocalStore(tmp_path / "store"), tmp_path / "runtime"),
    )
    pointer = publish(
        store, manifest, inputs, expected_version=None, activate=runtime.activate
    )
    model = BookModel(
        runtime.root / "versions" / manifest.publication_id / MODEL_PATH,
        manifest.publication_id,
    )
    assert model.describe(book)["citation"]["publication_id"] == manifest.publication_id
    active = runtime.active()

    def unavailable(*args):
        raise IntegrityError("derived index unavailable")

    runtime.prepare = unavailable
    with pytest.raises(IntegrityError, match="derived index"):
        runtime.resume_cached()
    assert runtime.active() == active
    assert not list(runtime.root.glob("invalid-*"))
    with pytest.raises(IntegrityError):
        runtime.activate(
            {"publication_id": manifest.publication_id, "manifest_sha256": "0" * 64}
        )
    assert runtime.active() == active
    assert pointer["publication_id"] == manifest.publication_id


def test_corrupt_source_tree_and_missing_model_report_are_rejected(
    structured, tmp_path
):
    _, manifest, _, _, root = structured
    with sqlite3.connect(root / "whole-books.sqlite") as db:
        row = db.execute(
            "select id,payload from nodes where node_kind='text' limit 1"
        ).fetchone()
        node = json.loads(row[1])
        node["text"] += "corrupted"
        db.execute("update nodes set payload=? where id=?", (json.dumps(node), row[0]))
    with pytest.raises(IntegrityError, match="text differs"):
        validate_model(root / "whole-books.sqlite", manifest.publication_id)
    assert MODEL_PATH in {e.path for e in manifest.files}
    assert REPORT_PATH in {e.path for e in manifest.files}


def test_recipe_citation_accepts_exact_whole_book_target():
    assert (
        RecipeCitation(
            publication_id="p",
            book_id="b",
            source_id="s",
            model_snapshot_id="m",
            target_id="t",
        ).target_id
        == "t"
    )
    with pytest.raises(ValueError):
        RecipeCitation(publication_id="p", book_id="b", source_id="s", target_id="t")


def test_supporting_work_scope_cycles_and_budgets(structured):
    _, manifest, _, book, root = structured
    model = BookModel(root / "whole-books.sqlite", manifest.publication_id)
    with sqlite3.connect(model.path) as db:
        span = db.execute("select id from spans limit 1").fetchone()[0]
        evidence = [span]

        def field(value):
            return {
                "state": "candidate",
                "value": value,
                "evidence_span_ids": evidence,
                "reason": None,
            }

        unparsed = {
            "state": "unparsed",
            "value": None,
            "evidence_span_ids": [],
            "reason": "Not interpreted",
        }
        recipes = [uuid.uuid4().hex for _ in range(4)]

        def insert(record):
            record["method"] = "synthetic fixture"
            db.execute(
                "insert into entities values(?,?,?,?,?)",
                (record["id"], book, record["kind"], "Synthetic", json.dumps(record)),
            )

        for recipe_id in recipes:
            insert(
                {
                    "id": recipe_id,
                    "kind": "recipe",
                    "edition_id": book,
                    "state": "candidate",
                    "evidence_span_ids": evidence,
                    "title": field("Synthetic beans"),
                    "content_span_ids": evidence,
                    "yield_value": unparsed,
                    "main_text_state": "unchecked",
                    "parsed_fields_state": "unparsed",
                    "supporting_work_state": "partial",
                }
            )

        def use(source, target, classification="required", scope="whole"):
            record = {
                "id": uuid.uuid4().hex,
                "kind": "recipe_use",
                "edition_id": book,
                "state": "candidate",
                "evidence_span_ids": evidence,
                "source_recipe_id": source,
                "target_recipe_id": target,
                "source_link_id": None,
                "source_part_id": None,
                "selected_formulation_id": None,
                "selected_part_id": None,
                "classification": field(classification),
                "scope": field(scope),
                "scope_wording": field(scope),
                "modification_wording": unparsed,
                "amount_used": unparsed,
            }
            insert(record)
            return record["id"]

        a, b, c, d = recipes
        use(a, b)
        partial = use(a, c, scope="partial")
        use(a, d, classification="alternative")
        use(b, a)
        hidden = use(c, d)
        for _ in range(3):
            insert(
                {
                    "id": uuid.uuid4().hex,
                    "kind": "recipe_choice",
                    "edition_id": book,
                    "state": "candidate",
                    "evidence_span_ids": evidence,
                    "recipe_id": a,
                    "choice_kind": "sourcing",
                    "member_use_ids": [],
                    "other_option_wordings": [field("Buy"), field("Make")],
                    "selection_wording": unparsed,
                }
            )
        db.commit()
    validate_model(model.path, manifest.publication_id)
    work = model.supporting_work(book, a)
    assert work["citation"]["target_id"] == a
    assert work["cycles"] == [[a, b, a]]
    assert partial in work["unresolved_scope_or_target"]
    assert hidden not in {u["id"] for u in work["uses"]}
    assert work["supporting_work_state"] == "partial"
    depth_limited = model.supporting_work(book, a, depth=0)
    assert depth_limited["truncated"] and all(
        u["source_recipe_id"] == a for u in depth_limited["uses"]
    )
    limited = model.supporting_work(book, a, limit=1)
    assert (
        limited["truncated"]
        and len(limited["uses"]) <= 1
        and len(limited["choices"]) == 1
    )
    assert len(canonical(limited)) < 26000


def test_prepared_lookup_continues_during_another_index_import(structured, tmp_path):
    import threading

    from cookbook.book_search import BookSearch

    _, manifest, _, _, root = structured
    engine = BookSearch(tmp_path / "unused-binary", tmp_path / "engine")
    engine.prepared.add(engine.collection(manifest.publication_id))
    finished = threading.Event()
    thread = threading.Thread(
        target=lambda: (engine.prepare(manifest, root), finished.set())
    )
    with engine.lock:  # A different publication is being imported.
        thread.start()
        ready = finished.wait(timeout=1)
    thread.join(timeout=2)
    assert ready and not thread.is_alive()


def test_restart_reuses_full_validation_but_always_checks_bytes(
    structured, tmp_path, monkeypatch
):
    from cookbook import book_build

    _, manifest, _, _, root = structured
    inputs = {
        k: Path(v) for k, v in json.loads((root / "inputs.json").read_bytes()).items()
    }
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    calls = []
    original = book_build.validate_model

    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(book_build, "validate_model", counted)
    publish(store, manifest, inputs, expected_version=None, activate=runtime.activate)
    assert len(calls) == 1
    runtime.resume_cached()
    assert len(calls) == 1
    version = runtime.root / "versions" / manifest.publication_id
    (version / ".model-validation.json").write_text("broken receipt")
    runtime.resume_cached()
    assert len(calls) == 2
    from cookbook import publication

    monkeypatch.setattr(publication, "_model_validation_signature", lambda: "new rules")
    runtime.resume_cached()
    assert len(calls) == 3
    model = runtime.root / "versions" / manifest.publication_id / MODEL_PATH
    with model.open("r+b") as stream:
        stream.seek(-1, 2)
        byte = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([byte[0] ^ 1]))
    with pytest.raises(IntegrityError, match="checksum"):
        runtime.resume_cached()
    assert len(calls) == 3 and runtime.active() is None


def test_validation_receipt_write_failure_preserves_verified_source(
    structured, tmp_path, monkeypatch
):
    from cookbook import publication

    _, manifest, _, _, root = structured
    inputs = {
        k: Path(v) for k, v in json.loads((root / "inputs.json").read_bytes()).items()
    }
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    original = publication.atomic_write

    def unavailable(path, data):
        if path.name == ".model-validation.json":
            raise OSError("cache unavailable")
        return original(path, data)

    monkeypatch.setattr(publication, "atomic_write", unavailable)
    publish(store, manifest, inputs, expected_version=None, activate=runtime.activate)
    active = runtime.active()
    runtime.resume_cached()
    assert runtime.active() == active and not list(runtime.root.glob("invalid-*"))


@pytest.mark.parametrize("ready_after", [240, None])
def test_expanded_index_reload_waits_but_remains_bounded(
    tmp_path, monkeypatch, free_tcp_port, free_tcp_port_factory, ready_after
):
    from urllib.error import URLError

    from cookbook import book_search

    clock = [0.0]

    class Child:
        exited = False

        def poll(self):
            return 0 if self.exited else None

        def terminate(self):
            self.exited = True

        def wait(self, timeout):
            return 0

    monkeypatch.setenv("REPORTS_AWS_SECRET_ACCESS_KEY", "synthetic-reports-secret")
    monkeypatch.setenv("REPORTS_S3_BUCKET", "synthetic-reports")

    def spawn(*args, **kwargs):
        assert not any(name.startswith("REPORTS_") for name in kwargs["env"])
        return Child()

    monkeypatch.setattr(book_search.subprocess, "Popen", spawn)
    monkeypatch.setattr(book_search.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        book_search.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    engine = book_search.BookSearch(
        tmp_path / "unused-binary",
        tmp_path / "engine",
        port=free_tcp_port,
        peer_port=free_tcp_port_factory(),
    )

    def call(method, path, **kwargs):
        if path == "/health":
            if ready_after is None or clock[0] < ready_after:
                raise URLError("complete index still loading")
            return {"ok": True}
        return {"version": "30.2"}

    monkeypatch.setattr(engine, "call", call)
    try:
        if ready_after is None:
            with pytest.raises(IntegrityError, match="startup timed out"):
                engine.start()
            assert 600 <= clock[0] < 601 and engine.process is None
        else:
            engine.start()
            assert ready_after <= clock[0] < 600 and engine.process is not None
    finally:
        engine.close()
