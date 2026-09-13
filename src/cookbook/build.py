"""Build an index from an explicitly approved, already verified snapshot."""

from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from .extract import VERSION, epub, paged, ident
from .publication import Entry, Manifest
from .storage import IntegrityError, atomic_write, canonical, digest_file

SCHEMA = """
CREATE TABLE info(publication_id TEXT NOT NULL, extraction_version TEXT NOT NULL);
CREATE TABLE books(id TEXT PRIMARY KEY, calibre_id INTEGER, title TEXT, authors TEXT, tags TEXT, source_id TEXT);
CREATE TABLE sources(id TEXT PRIMARY KEY, format TEXT, sha256 TEXT, original_path TEXT, toc TEXT);
CREATE TABLE sections(id TEXT PRIMARY KEY, source_id TEXT, ordinal INTEGER, title TEXT, text TEXT, locator TEXT, provenance TEXT, kind TEXT, images TEXT);
CREATE INDEX sections_source ON sections(source_id,ordinal);
CREATE TABLE images(id TEXT PRIMARY KEY, source_id TEXT, asset TEXT, document TEXT, caption TEXT);
CREATE TABLE image_context(image_id TEXT PRIMARY KEY, title TEXT, section_id TEXT);
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
        db.execute(
            "insert into search values (?,?,?,?)",
            (s["id"], source, s["title"], s["text"]),
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


def build_snapshot(
    snapshot: Path,
    approved_ids: list[int],
    output: Path,
    cache: Path,
    progress=print,
    *,
    force_ocr_ids=(),
):
    if output.exists():
        raise IntegrityError("build directory must be new")
    force_ocr_ids = set(force_ocr_ids)
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
        records.append(dict(row))
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
        formats = db.execute(
            "select format,name from data where book=?", (r["id"],)
        ).fetchall()
        if len(formats) != 1 or formats[0][0] not in ("PDF", "DJVU"):
            raise IntegrityError("forced OCR requires a PDF or DjVu source")
        fmt, name = formats[0]
        rel = r["path"] + "/" + name + "." + fmt.lower()
        forced_sources.add(fmt.lower() + ":" + proof_files[rel]["sha256"])
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
        formats = db.execute(
            "select format,name from data where book=?", (r["id"],)
        ).fetchall()
        if len(formats) != 1:
            raise IntegrityError("POC requires one format per record")
        fmt, name = formats[0]
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
                else "low_text_pages"
                if fmt != "EPUB"
                else "not_applicable",
                "images": len(images),
                "toc_entries": len(toc),
                "unresolved_toc": sum(t.get("section_id") is None for t in toc),
            }
        )
        dest.commit()
        progress({"event": "extract_done", **stats[-1]})
    db.close()
    dest.execute("insert into search(search) values('optimize')")
    dest.commit()
    dest.close()
    from .quality import make_report, QUALITY_PATH

    report = make_report(pub, quality_items, forced_ocr_sources=forced_sources)
    atomic_write(output / "ocr-review.json", canonical(report))
    inputs[QUALITY_PATH] = output / "ocr-review.json"
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
        created_at=datetime.now(timezone.utc).isoformat(),
        files=entries,
    )
    atomic_write(output / "manifest.json", canonical(m.model_dump()))
    atomic_write(
        output / "inputs.json", canonical({k: str(v) for k, v in inputs.items()})
    )
    atomic_write(output / "stats.json", canonical(stats))
    return m, inputs, stats
