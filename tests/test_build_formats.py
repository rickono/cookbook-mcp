import json
import sqlite3

import pytest

from cookbook.build import build_snapshot, select_format
from cookbook.publication import Runtime, publish
from cookbook.library import Library
from cookbook.storage import IntegrityError, LocalStore, canonical, digest_file
from test_extract import make_epub


@pytest.mark.parametrize(
    "formats",
    [
        [("AZW3", "original"), ("EPUB", "converted")],
        [("EPUB", "converted"), ("AZW3", "original")],
        [("PDF", "scan"), ("EPUB", "converted")],
    ],
)
def test_epub_preferred(formats):
    assert select_format(formats) == ("EPUB", "converted")


@pytest.mark.parametrize(
    "formats",
    [
        [],
        [("AZW3", "original")],
        [("PDF", "scan"), ("DJVU", "other")],
    ],
)
def test_missing_or_ambiguous_supported_format_refused(formats):
    with pytest.raises(IntegrityError, match="unambiguous"):
        select_format(formats)


@pytest.mark.parametrize("fmt", ["PDF", "DJVU"])
def test_single_paged_format_keeps_existing_selection(fmt):
    assert select_format([(fmt, "book")]) == (fmt, "book")


def test_multiformat_snapshot_search_and_backup(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot" / "library"
    book = snapshot / "Author" / "Book (1)"
    book.mkdir(parents=True)
    make_epub(book / "book.epub")
    (book / "book.azw3").write_bytes(b"synthetic original AZW3 backup")
    with sqlite3.connect(snapshot / "metadata.db") as db:
        db.executescript("""
            CREATE TABLE library_id(uuid TEXT);
            INSERT INTO library_id VALUES('library');
            CREATE TABLE books(id INTEGER,uuid TEXT,title TEXT,path TEXT);
            INSERT INTO books VALUES(1,'book','Beans','Author/Book (1)');
            CREATE TABLE data(book INTEGER,format TEXT,name TEXT);
            INSERT INTO data VALUES(1,'AZW3','book'),(1,'EPUB','book');
            CREATE TABLE authors(id INTEGER,name TEXT);
            CREATE TABLE books_authors_link(id INTEGER,book INTEGER,author INTEGER);
            CREATE TABLE tags(id INTEGER,name TEXT);
            CREATE TABLE books_tags_link(book INTEGER,tag INTEGER);
        """)
    proof = {"files": []}
    for path in sorted(snapshot.rglob("*")):
        if path.is_file():
            sha, size = digest_file(path)
            proof["files"].append(
                {"path": str(path.relative_to(snapshot)), "sha256": sha, "size": size}
            )
    (snapshot.parent / "snapshot-manifest.json").write_bytes(canonical(proof))

    def no_paged(*args, **kwargs):
        pytest.fail("EPUB selection must not invoke paged ingestion or OCR")

    monkeypatch.setattr("cookbook.build.paged", no_paged)
    output, cache = tmp_path / "build", tmp_path / "unused-cache"
    with pytest.raises(IntegrityError, match="forced OCR requires"):
        build_snapshot(snapshot, [1], output, cache, force_ocr_ids=[1])
    assert not output.exists()
    manifest, inputs, stats = build_snapshot(
        snapshot, [1], output, cache, progress=lambda _: None
    )
    assert stats[0]["format"] == "EPUB"
    assert not cache.exists()
    for suffix in ("epub", "azw3"):
        logical = f"backup/Author/Book (1)/book.{suffix}"
        entry = next(e for e in manifest.files if e.path == logical)
        assert entry.role == "backup"
        assert digest_file(inputs[logical]) == (entry.sha256, entry.size)
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    result = publish(
        store, manifest, inputs, expected_version=None, activate=runtime.activate
    )
    assert result["status"] == "active"
    with sqlite3.connect(output / "index.sqlite") as db:
        assert db.execute("select format from sources").fetchall() == [("EPUB",)]
        assert db.execute(
            "select text from sections where text like '%1/2 teaspoon%'"
        ).fetchone()
    library = Library(runtime)
    assert library.search("beans")["results"]
    assert json.loads((output / "ocr-review.json").read_bytes())["pending_ids"] == []
