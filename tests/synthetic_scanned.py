"""A synthetic scanned-candidate.v1 book and a snapshot that registers it.

Nothing here is book-derived. The PDF is a placeholder that is never parsed; the
candidate rows imitate the production assembler's output shape.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3

from cookbook.storage import atomic_write, canonical, digest_file

BOOK = 9001
RECIPE = f"{BOOK}:lentil-soup"
SIDEBAR = f"{BOOK}:on-lentils"
REVIEW = f"{BOOK}:p001:crop1"
BOX = [0.1, 0.4, 0.9, 0.7]
READERS = [f"claude:claude-haiku-5-5#{n}" for n in (1, 2, 3)]

TABLE = "Lentils | 1½ cups\nSalt | 2 tsp\nCumin | 3 tsp"
PAGE_1 = "LENTIL SOUP\nA plain soup for cold evenings.\n" + TABLE
INSTRUCTIONS = "Simmer the lentils with the salt and cumin for 30 minutes."
SIDEBAR_TEXT = "Small green lentils keep their shape."
PAGE_2 = INSTRUCTIONS + "\nON LENTILS\n" + SIDEBAR_TEXT
PAGE_4 = "Printed on synthetic paper for the colophon."
# The crop readers disagreed about this quantity; it must never be served.
RAW_READINGS = ["Cumin | 5 tsp", "Cumin | 8 tsp"]


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def page(n, status, text="", *, sections=(), unresolved=(), printed=None, **extra):
    row = {
        "physical_page": n,
        "status": status,
        "text": text,
        "text_sha256": sha(text),
        "image_sha256": sha(f"image {n}"),
        "printed_page": printed,
        "section_ids": list(sections),
        "unresolved_ids": list(unresolved),
        "page_reader": READERS[0] if status == "transcribed" else None,
        "vote_correction_ids": [],
        "blank_evidence": None,
    }
    row.update(extra)
    return row


def part(kind, source_page, text, unresolved=()):
    return {
        "kind": kind,
        "source_page": source_page,
        "text": text,
        "description": None,
        "unresolved_ids": list(unresolved),
    }


def rows():
    """Multi-page recipe, sidebar passage, table quantities, one unresolved quantity, one blank page."""
    return copy.deepcopy(
        {
            "pages": [
                page(1, "transcribed", PAGE_1, sections=[RECIPE], unresolved=["u1"])
                | {"printed_page": "12", "vote_correction_ids": [f"{BOOK}:p001:c0"]},
                page(
                    2, "transcribed", PAGE_2, sections=[RECIPE, SIDEBAR], printed="13"
                ),
                page(
                    3,
                    "blank",
                    blank_evidence={
                        "rule": "page_read_empty_response",
                        "attempts": 2,
                        "page_read_errors": ["empty response"] * 2,
                    },
                ),
                page(4, "transcribed", PAGE_4),
            ],
            "sections": [
                {
                    "id": RECIPE,
                    "kind": "recipe",
                    "title": "LENTIL SOUP",
                    "physical_pages": [1, 2],
                    "printed_pages": ["12", "13"],
                    "status": "complete_in_book",
                    "parts": [
                        part("title", 1, "LENTIL SOUP"),
                        part("headnote", 1, "A plain soup for cold evenings."),
                        part("table", 1, TABLE, unresolved=["u1"]),
                        part("instructions", 2, INSTRUCTIONS),
                    ],
                    "references": [],
                },
                {
                    "id": SIDEBAR,
                    "kind": "passage",
                    "title": "ON LENTILS",
                    "physical_pages": [2],
                    "printed_pages": ["13"],
                    "parts": [
                        part("title", 2, "ON LENTILS"),
                        part("text", 2, SIDEBAR_TEXT),
                    ],
                    "references": [
                        {
                            "source_page": 2,
                            "label": "see the soup",
                            "printed_target": "12",
                            "target_section_id": RECIPE,
                            "scope": "authored reference",
                        }
                    ],
                },
            ],
            "quantity-review": [
                {
                    "id": REVIEW,
                    "physical_page": 1,
                    "box": BOX,
                    "section_ids": [RECIPE],
                    "crop_sha256": sha("crop 1"),
                    "fields_reviewed": ["Salt | 2 tsp", "Cumin | 3 tsp"],
                    "remaining_uncertainty": ["Cumin | 3 tsp"],
                    "readers": READERS,
                }
            ],
            "unresolved": [
                {
                    "id": "u1",
                    "section_id": RECIPE,
                    "physical_page": 1,
                    "field": "amount",
                    "code": "amount",
                    "reason": "crop readers did not reach a majority",
                    "source_fragment": "Cumin | 3 tsp",
                    "span": "3 tsp",
                    "box": BOX,
                    "review_id": REVIEW,
                    "crop_readings": RAW_READINGS,
                }
            ],
            "vote-corrections": [
                {
                    "id": f"{BOOK}:p001:c0",
                    "physical_page": 1,
                    "section_id": RECIPE,
                    "from": "Salt | 2 tbsp",
                    "to": "Salt | 2 tsp",
                }
            ],
        }
    )


def jsonl(items):
    return b"".join(canonical(i) + b"\n" for i in items)


def pack(data, source_sha256, *, physical_pages=None, **changes):
    """Contract files (name -> bytes) with a freeze record that binds them."""
    files = {
        f"{key}.jsonl": jsonl(items)
        for key, items in data.items()
        if key != "candidate"
    }
    statuses = [p["status"] for p in data["pages"]]
    candidate = {
        "version": "scanned-candidate.v1",
        "book_id": BOOK,
        "source": {
            "sha256": source_sha256,
            "format": "PDF",
            "physical_pages": physical_pages or len(data["pages"]),
        },
        "config_id": "pipeline-claude-haiku-5-5-x3-fb-gpt-6-luna--low-a4",
        "reader": {
            "spec": "claude:claude-haiku-5-5",
            "samples": 3,
            "sample_labels": READERS,
            "fallback": "codex:gpt-6-luna@low#fallback",
        },
        "assembler": "v4",
        "prompts_sha256": {
            k: sha("prompt " + k) for k in ("page", "region", "crop", "sectioning")
        },
        "code_sha256": sha("code"),
        "repo_head": None,
        "coverage": {
            "pages_total": physical_pages or len(data["pages"]),
            **{s: statuses.count(s) for s in ("transcribed", "blank", "failed")},
        },
        "counts": {
            "sections": len(data["sections"]),
            "quantity_reviews": len(data["quantity-review"]),
            "unresolved": len(data["unresolved"]),
        },
        "approval": "unapproved",
        "files": {
            name: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
            for name, b in files.items()
        },
    }
    candidate.update(changes)
    return {"candidate.json": canonical(candidate), **files}


def write_candidate(directory, files):
    directory.mkdir(parents=True)
    for name, data in files.items():
        (directory / name).write_bytes(data)
    return directory


PDF_BYTES = b"%PDF-synthetic placeholder, never parsed"


def snapshot(tmp_path, *, epub=None, pdf=True):
    """A verified snapshot with one approved book (Calibre id 1); optional EPUB bytes."""
    library = tmp_path / "snapshot" / "library"
    folder = library / "Test" / "Lentils (1)"
    folder.mkdir(parents=True)
    formats = []
    if pdf:
        (folder / "scan.pdf").write_bytes(PDF_BYTES)
        formats.append("(1,'PDF','scan')")
    if epub is not None:
        epub(folder / "scan.epub")
        formats.append("(1,'EPUB','scan')")
    with sqlite3.connect(library / "metadata.db") as db:
        db.executescript(f"""
            CREATE TABLE library_id(uuid TEXT); INSERT INTO library_id VALUES('synthetic');
            CREATE TABLE books(id INTEGER,uuid TEXT,title TEXT,path TEXT);
            INSERT INTO books VALUES(1,'lentils','Synthetic Lentils','Test/Lentils (1)');
            CREATE TABLE data(book INTEGER,format TEXT,name TEXT);
            INSERT INTO data VALUES {",".join(formats)};
            CREATE TABLE authors(id INTEGER,name TEXT); INSERT INTO authors VALUES(1,'Test Author');
            CREATE TABLE books_authors_link(id INTEGER,book INTEGER,author INTEGER);
            INSERT INTO books_authors_link VALUES(1,1,1);
            CREATE TABLE tags(id INTEGER,name TEXT);
            CREATE TABLE books_tags_link(book INTEGER,tag INTEGER);
        """)
    proof = {"files": []}
    for p in sorted(library.rglob("*")):
        if p.is_file():
            digest, size = digest_file(p)
            proof["files"].append(
                {"path": str(p.relative_to(library)), "sha256": digest, "size": size}
            )
    atomic_write(library.parent / "snapshot-manifest.json", canonical(proof))
    return library


def pdf_sha256():
    return hashlib.sha256(PDF_BYTES).hexdigest()


def registry(tmp_path, data=None, *, source_sha256=None, physical_pages=4, **changes):
    """Register a candidate directory for the synthetic PDF; returns the build mapping."""
    digest = source_sha256 or pdf_sha256()
    files = pack(data or rows(), digest, **changes)
    directory = write_candidate(
        tmp_path / f"candidate-{len(list(tmp_path.glob('candidate-*')))}", files
    )
    return {pdf_sha256(): {"physical_pages": physical_pages, "candidate": directory}}


def one_section_rows(texts, section="lentil-soup", title="Lentil soup"):
    """Every page transcribed and owned by one recipe section; nothing unresolved."""
    numbers = list(range(1, len(texts) + 1))
    return {
        "pages": [
            page(n, "transcribed", t, sections=[section])
            for n, t in zip(numbers, texts)
        ],
        "sections": [
            {
                "id": section,
                "kind": "recipe",
                "title": title,
                "physical_pages": numbers,
                "printed_pages": [None] * len(numbers),
                "parts": [part("text", n, t) for n, t in zip(numbers, texts)],
                "references": [],
            }
        ],
        "quantity-review": [],
        "unresolved": [],
        "vote-corrections": [],
    }


def publish_scanned(tmp_path, data, monkeypatch):
    """Build the synthetic snapshot from a candidate, gate and publish it; no OCR or rendering."""
    import cookbook.build as build_module
    from cookbook.build import build_snapshot
    from cookbook.library import Library
    from cookbook.publication import Runtime, publish
    from cookbook.scanned import ident
    from cookbook.storage import LocalStore

    def refuse(*args, **kwargs):
        raise AssertionError("scanned import must not render or OCR")

    monkeypatch.setattr(build_module, "paged", refuse)
    m, inputs, _ = build_snapshot(
        snapshot(tmp_path),
        [1],
        tmp_path / "build",
        tmp_path / "cache",
        progress=lambda event: None,
        scanned=registry(tmp_path, data, physical_pages=len(data["pages"])),
    )
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    publish(store, m, inputs, expected_version=None, activate=runtime.activate)
    ids = {
        "publication_id": m.publication_id,
        "book_id": ident("synthetic", "lentils"),
        "source_id": "pdf:" + pdf_sha256(),
    }
    return Library(runtime), ids


def dump(value):
    return json.dumps(value, ensure_ascii=False)


REVIEWER = {"kind": "agent", "id": "blind-reread:claude:claude-haiku-5-5 x3"}


def correction(n, from_text, to_text, *, page=1, section_id=None, source=None, **extra):
    """A correction-ledger row as triage writes it (scripts/triage_reports.py)."""
    digest = source or pdf_sha256()
    row = {
        "id": sha(f"report {n}"),
        "decided_at": f"2026-10-20T10:00:{n:02d}Z",
        "report_id": sha(f"report {n}"),
        "publication_id": "an-earlier-publication",
        "book_id": "synthetic-book",
        "source_id": "pdf:" + digest,
        "source_sha256": digest,
        "physical_page": page,
        "section_id": section_id,
        "region": None,
        "kind": "quantity",
        "from_text": from_text,
        "to_text": to_text,
        "state": "source_reviewed",
        "reviewer": dict(REVIEWER),
        "evidence": {
            "crop_sha256": sha(f"crop {n}"),
            "readings_sha256": sha(f"readings {n}"),
            "votes": {"proposed": 3, "current": 0, "neither": 0},
        },
    }
    row.update(extra)
    return row
