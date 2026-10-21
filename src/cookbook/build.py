"""Build an index from an explicitly approved, already verified snapshot."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import ledger as ledger_rows
from .extract import VERSION, epub, ident, paged
from .publication import Entry, Manifest
from .scanned import (
    BUILD_REPORT,
    INVENTORY,
    SUMMARY_PATH,
    SUMMARY_VERSION,
    build_report,
    correction_counts,
    import_candidate,
    read_candidate,
)
from .storage import IntegrityError, atomic_write, canonical, digest_file

BUILD_INPUTS = "quality/build-inputs.json"
BUILD_INPUTS_VERSION = "build-inputs.v1"

SCHEMA = """
CREATE TABLE info(publication_id TEXT NOT NULL, extraction_version TEXT NOT NULL);
CREATE TABLE books(id TEXT PRIMARY KEY, calibre_id INTEGER, title TEXT, authors TEXT, tags TEXT, source_id TEXT);
CREATE TABLE sources(id TEXT PRIMARY KEY, format TEXT, sha256 TEXT, original_path TEXT, toc TEXT);
CREATE TABLE sections(id TEXT PRIMARY KEY, source_id TEXT, ordinal INTEGER, title TEXT, text TEXT, locator TEXT, provenance TEXT, kind TEXT, images TEXT);
CREATE INDEX sections_source ON sections(source_id,ordinal);
CREATE TABLE images(id TEXT PRIMARY KEY, source_id TEXT, asset TEXT, document TEXT, caption TEXT);
CREATE TABLE image_context(image_id TEXT PRIMARY KEY, title TEXT, section_id TEXT);
CREATE TABLE transcription_sources(source_id TEXT PRIMARY KEY, summary TEXT);
CREATE TABLE transcription_units(section_id TEXT PRIMARY KEY, source_id TEXT, label TEXT, check_regions TEXT, corrections TEXT);
CREATE VIRTUAL TABLE search USING fts5(section_id UNINDEXED, source_id UNINDEXED, title, text, tokenize='unicode61 remove_diacritics 2');
"""


def create_index(path, pub):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute("insert into info values (?,?)", (pub, VERSION))
    return db


def add_content(db, source, fmt, sha, original, sections, images, toc):
    db.execute(
        "insert into sources values (?,?,?,?,?)",
        (source, fmt, sha, original, json.dumps(toc)),
    )
    for i, s in enumerate(sections):
        db.execute(
            "insert into sections values (?,?,?,?,?,?,?,?,?)",
            (
                s["id"],
                source,
                i,
                s["title"],
                s["text"],
                json.dumps(s["locator"]),
                s["provenance"],
                s["kind"],
                json.dumps(s["images"]),
            ),
        )
        # Scanned page units covered by a section stay readable but are not search hits.
        if s.get("searchable", True):
            db.execute(
                "insert into search values (?,?,?,?)",
                (s["id"], source, s["title"], s["text"]),
            )
        if "transcription" in s:
            t = s["transcription"]
            db.execute(
                "insert into transcription_units values (?,?,?,?,?)",
                (
                    s["id"],
                    source,
                    json.dumps(t["label"]),
                    json.dumps(t["check_regions"]),
                    json.dumps(t["corrections"]),
                ),
            )
    for im in images:
        db.execute(
            "insert into images values (?,?,?,?,?)",
            (im["id"], source, im["asset"], im["document"], im["caption"]),
        )
        if im.get("recipe_context"):
            context = im["recipe_context"]
            db.execute(
                "insert into image_context values (?,?,?)",
                (im["id"], context["title"], context["section_id"]),
            )


def select_format(formats):
    """Index EPUB when available; all snapshot formats remain backed up."""
    epubs = [row for row in formats if row[0] == "EPUB"]
    if len(epubs) == 1:
        return epubs[0]
    if not epubs and len(formats) == 1 and formats[0][0] in ("PDF", "DJVU"):
        return formats[0]
    raise IntegrityError("book requires an EPUB or one unambiguous PDF/DjVu format")


def build_snapshot(
    snapshot: Path,
    approved_ids: list[int],
    output: Path,
    cache: Path,
    progress=print,
    *,
    force_ocr_ids=(),
    scanned=None,
    ledger=None,
):
    """Build a new publication directory.

    A PDF is indexed from its registered scanned candidate (``scanned`` maps a source
    sha256 to ``{"physical_pages", "candidate"}``, see scanned.read_registry), with the
    rows of the correction ``ledger`` (cookbook.ledger) for its digest applied; each
    source's rows are backed up beside its candidate and the outcomes are counted in
    ``build-report.json``, which also holds the owner queue of ambiguous corrections. A
    PDF without a candidate is refused unless it is named in ``force_ocr_ids``; native
    page OCR still passes the OCR admission check.
    """
    if output.exists():
        raise IntegrityError("build directory must be new")
    force_ocr_ids = set(force_ocr_ids)
    scanned = scanned or {}
    ledger = ledger_rows.check(ledger or [])
    if not force_ocr_ids.issubset(approved_ids):
        raise IntegrityError("forced OCR books must be in the approved selection")
    # POC backs up only approved record directories plus catalog metadata; full-library command deferred.
    snapshot = snapshot.resolve()
    proof = json.loads((snapshot.parent / "snapshot-manifest.json").read_bytes())
    proof_files = {e["path"]: e for e in proof["files"]}
    dbpath = snapshot / "metadata.db"
    if digest_file(dbpath) != (
        proof_files["metadata.db"]["sha256"],
        proof_files["metadata.db"]["size"],
    ):
        raise IntegrityError("snapshot catalog changed")
    db = sqlite3.connect(dbpath.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    library_uuid = db.execute("select uuid from library_id").fetchone()[0]
    records = []
    for bid in approved_ids:
        row = db.execute(
            "select id,uuid,title,path from books where id=?", (bid,)
        ).fetchone()
        if row is None:
            raise IntegrityError("unknown approved book")
        record = dict(row)
        record["selected_format"] = select_format(
            db.execute("select format,name from data where book=?", (bid,)).fetchall()
        )
        records.append(record)
    inputs = {}
    selected_paths = {r["path"] for r in records}
    for rel, e in proof_files.items():
        if rel in ("metadata.db", "metadata_db_prefs_backup.json") or any(
            rel.startswith(p + "/") for p in selected_paths
        ):
            p = snapshot / rel
            if p.is_symlink() or not p.resolve().is_relative_to(snapshot):
                raise IntegrityError("unsafe snapshot path")
            sha, size = digest_file(p)
            if sha != e["sha256"] or size != e["size"]:
                raise IntegrityError("snapshot changed")
            inputs["backup/" + rel] = p
    forced_sources = set()
    for r in records:
        if r["id"] not in force_ocr_ids:
            continue
        fmt, name = r["selected_format"]
        if fmt not in ("PDF", "DJVU"):
            raise IntegrityError("forced OCR requires a PDF or DjVu source")
        rel = r["path"] + "/" + name + "." + fmt.lower()
        forced_sources.add(fmt.lower() + ":" + proof_files[rel]["sha256"])
    imported = {}
    for r in records:
        fmt, name = r["selected_format"]
        if fmt != "PDF":
            continue
        sha = proof_files[r["path"] + "/" + name + ".pdf"]["sha256"]
        source = "pdf:" + sha
        if sha not in scanned:
            if r["id"] not in force_ocr_ids:
                raise IntegrityError("PDF book requires a registered scanned candidate")
            continue
        if r["id"] in force_ocr_ids:
            raise IntegrityError(
                "PDF book has both a registered scanned candidate and forced OCR"
            )
        if source not in imported:
            files = read_candidate(scanned[sha]["candidate"])
            imported[source] = import_candidate(
                files,
                source_id=source,
                source_sha256=sha,
                physical_pages=scanned[sha]["physical_pages"],
                ledger=ledger,
            )
            imported[source]["files"] = files | {
                ledger_rows.FILE: ledger_rows.dump(imported[source]["ledger"])
            }
            imported[source]["calibre_ids"] = []
        imported[source]["calibre_ids"].append(r["id"])
    output.mkdir(parents=True, mode=0o700)
    (output / "assets").mkdir(mode=0o700)
    pub = uuid.uuid4().hex
    index = output / "index.sqlite"
    dest = create_index(index, pub)

    def emit_asset(data):
        import hashlib

        sha = hashlib.sha256(data).hexdigest()
        p = output / "assets" / sha
        if not p.exists():
            atomic_write(p, data)
        logical = "assets/" + sha
        inputs[logical] = p
        return logical

    seen = set()
    stats = []
    quality_items = []
    for r in records:
        authors = [
            v[0]
            for v in db.execute(
                "select a.name from authors a join books_authors_link l on a.id=l.author where l.book=? order by l.id",
                (r["id"],),
            )
        ]
        tags = [
            v[0]
            for v in db.execute(
                "select t.name from tags t join books_tags_link l on t.id=l.tag where l.book=?",
                (r["id"],),
            )
        ]
        fmt, name = r["selected_format"]
        rel = r["path"] + "/" + name + "." + fmt.lower()
        p = snapshot / rel
        sha, size = digest_file(p)
        source = fmt.lower() + ":" + sha
        dest.execute(
            "insert into books values (?,?,?,?,?,?)",
            (
                ident(library_uuid, r["uuid"]),
                r["id"],
                r["title"],
                json.dumps(authors),
                json.dumps(tags),
                source,
            ),
        )
        if source in seen:
            continue
        progress({"event": "extract_start", "calibre_id": r["id"], "format": fmt})
        if fmt == "EPUB":
            sections, images, toc = epub(p, source, emit_asset)
        elif source in imported:
            candidate = imported[source]
            sections, images, toc = candidate["units"], [], candidate["toc"]
            for file_name, data in candidate["files"].items():
                copy = output / "scanned" / sha / file_name
                atomic_write(copy, data)
                inputs[f"{INVENTORY}/{sha}/{file_name}"] = copy
            dest.execute(
                "insert into transcription_sources values (?,?)",
                (source, json.dumps(candidate["summary"])),
            )
        else:
            sections, images, toc = paged(
                p,
                fmt,
                source,
                cache,
                progress=progress,
                force_ocr=source in forced_sources,
            )
        for section in sections:
            if "ocr" in section["locator"]:
                quality_items.append(
                    {
                        "section_id": section["id"],
                        "source_id": source,
                        "book_title": r["title"],
                        "calibre_id": r["id"],
                        **section["locator"]["ocr"],
                    }
                )
        add_content(dest, source, fmt, sha, "backup/" + rel, sections, images, toc)
        seen.add(source)
        stats.append(
            {
                "calibre_id": r["id"],
                "format": fmt,
                "sections": len(sections),
                "text_chars": sum(len(s["text"]) for s in sections),
                "ocr_pages": sum(s["provenance"] == "ocr" for s in sections),
                "ocr_empty_pages": sum(
                    s["provenance"] in ("native+ocr-empty", "ocr-empty")
                    for s in sections
                ),
                "ocr_mode": "all_pages"
                if source in forced_sources
                else "scanned_candidate"
                if source in imported
                else "low_text_pages"
                if fmt != "EPUB"
                else "not_applicable",
                "images": len(images),
                "toc_entries": len(toc),
                "unresolved_toc": sum(t.get("section_id") is None for t in toc),
            }
        )
        if source in imported:
            stats[-1]["corrections"] = correction_counts(imported[source]["summary"])
        dest.commit()
        progress({"event": "extract_done", **stats[-1]})
    db.close()
    dest.execute("insert into search(search) values('optimize')")
    dest.commit()
    dest.close()
    from .quality import QUALITY_PATH, make_report

    report = make_report(pub, quality_items, forced_ocr_sources=forced_sources)
    atomic_write(output / "ocr-review.json", canonical(report))
    inputs[QUALITY_PATH] = output / "ocr-review.json"
    if imported:
        summary = {
            "version": SUMMARY_VERSION,
            "sources": [imported[s]["summary"] for s in sorted(imported)],
        }
        atomic_write(output / "transcription-summary.json", canonical(summary))
        inputs[SUMMARY_PATH] = output / "transcription-summary.json"
        atomic_write(
            output / BUILD_REPORT,
            canonical(build_report(imported.values())),
        )
    # What a refresh needs to rebuild this publication with a new ledger: the same
    # snapshot (by its proof), approved selection, OCR choices and candidate set.
    record = {
        "version": BUILD_INPUTS_VERSION,
        "snapshot": {
            "path": str(snapshot),
            "proof_sha256": digest_file(snapshot.parent / "snapshot-manifest.json")[0],
        },
        "ocr_cache": str(Path(cache).resolve()),
        "approved_ids": list(approved_ids),
        "force_ocr_ids": sorted(force_ocr_ids),
        "scanned": [
            {
                "source_sha256": imported[s]["summary"]["source_sha256"],
                "physical_pages": scanned[imported[s]["summary"]["source_sha256"]][
                    "physical_pages"
                ],
                "candidate_sha256": imported[s]["candidate_sha256"],
            }
            for s in sorted(imported)
        ],
    }
    atomic_write(output / "build-inputs.json", canonical(record))
    inputs[BUILD_INPUTS] = output / "build-inputs.json"
    inputs["runtime/index.sqlite"] = index
    entries = []
    for logical, p in sorted(inputs.items()):
        sha, size = digest_file(p)
        entries.append(
            Entry(
                path=logical,
                sha256=sha,
                size=size,
                role="runtime"
                if logical.startswith("runtime/")
                else "backup"
                if logical.startswith(("backup/", "quality/"))
                else "asset",
            )
        )
    m = Manifest(
        publication_id=pub,
        locator_version="epub-spine-v2",
        created_at=datetime.now(UTC).isoformat(),
        files=entries,
    )
    atomic_write(output / "manifest.json", canonical(m.model_dump()))
    atomic_write(
        output / "inputs.json", canonical({k: str(v) for k, v in inputs.items()})
    )
    atomic_write(output / "stats.json", canonical(stats))
    return m, inputs, stats
