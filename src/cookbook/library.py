"""Read-only library queries and bounded authenticated content responses."""

from __future__ import annotations

import io
import json
import re
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from .extract import render_page
from .storage import IntegrityError, digest_file, verify


class Library:
    def __init__(self, runtime, cache_bytes=512 * 1024**2, search_engine=None):
        self.runtime = runtime
        self.cache_bytes = cache_bytes
        self.asset_lock = threading.Lock()
        self.search_engine = search_engine

    def model(self, publication_id):
        from .book_model import MODEL_PATH, BookModel

        pub = self.publication(publication_id)
        manifest = self.runtime.manifest(pub)
        if not any(
            e.path == MODEL_PATH and e.role == "runtime" for e in manifest.files
        ):
            raise IntegrityError(
                "whole-book structure unavailable for this publication"
            )
        return BookModel(self.runtime.root / "versions" / pub / MODEL_PATH, pub)

    def get_book_structure(self, publication_id, book_id, offset=0, limit=30):
        return self.model(publication_id).describe(book_id, offset, limit)

    def read_book_content(
        self,
        publication_id,
        book_id,
        target_id,
        cursor=None,
        byte_budget=16000,
        node_budget=100,
    ):
        return self.model(publication_id).read(
            book_id, target_id, cursor, byte_budget, node_budget
        )

    def get_supporting_work(
        self, publication_id, book_id, recipe_id, depth=4, limit=30
    ):
        return self.model(publication_id).supporting_work(
            book_id, recipe_id, depth, limit
        )

    def find_book_content(
        self,
        query,
        publication_id=None,
        book_ids=None,
        kinds=None,
        include_candidates=True,
        limit=25,
        page=1,
    ):
        from .book_model import connection, payload

        allowed_kinds = {
            "source",
            "recipe",
            "recipe_part",
            "recipe_ingredient",
            "instruction",
            "recipe_use",
            "recipe_choice",
            "recipe_formulation",
            "ingredient_allocation",
            "division",
            "passage",
            "reference_entry",
            "attribution",
            "attribute_assertion",
            "pairing_assertion",
        }
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 200
            or not 1 <= limit <= 50
            or not 1 <= page <= 100
            or page > 1
            and publication_id is None
        ):
            raise IntegrityError("invalid whole-book search")
        if book_ids is not None and (
            len(book_ids) > 100
            or any(not re.fullmatch(r"[a-f0-9]{32}", b) for b in book_ids)
        ):
            raise IntegrityError("invalid book scope")
        if kinds is not None and (
            not kinds
            or len(kinds) > len(allowed_kinds)
            or any(k not in allowed_kinds for k in kinds)
        ):
            raise IntegrityError("invalid search kinds")
        model = self.model(publication_id)
        if self.search_engine is None:
            raise IntegrityError("search engine unavailable")
        with connection(model.path) as db:
            editions = {
                r["id"]: payload(r) for r in db.execute("select * from editions")
            }
            if book_ids is not None and any(i not in editions for i in book_ids):
                raise IntegrityError("unavailable book scope")
            if book_ids == []:
                return {
                    "publication_id": model.publication_id,
                    "model_snapshot_id": model.snapshot,
                    "results": [],
                    "next_page": None,
                }
            manifest = self.runtime.manifest(model.publication_id)
            self.search_engine.prepare(manifest, model.path.parents[1])
            found = self.search_engine.search(
                model.publication_id,
                query,
                book_ids,
                kinds,
                include_candidates,
                limit,
                page,
            )
            results = []
            for group in found.get("grouped_hits", [])[:limit]:
                hit = group["hits"][0]
                row = db.execute(
                    "select * from search_units where id=?", (hit["document"]["id"],)
                ).fetchone()
                if (
                    row is None
                    or book_ids
                    and row["edition_id"] not in book_ids
                    or kinds
                    and row["kind"] not in kinds
                    or not include_candidates
                    and row["state"] == "candidate"
                ):
                    raise IntegrityError(
                        "search hit is outside the requested source scope"
                    )
                entity_row = db.execute(
                    "select payload from entities where id=?", (row["target_id"],)
                ).fetchone()
                entity = payload(entity_row) if entity_row else None
                results.append(
                    {
                        "citation": model.citation(
                            editions[row["edition_id"]], target_id=row["target_id"]
                        ),
                        "kind": row["kind"],
                        "title": row["title"],
                        "source_state": row["state"],
                        "main_text_state": entity.get("main_text_state")
                        if entity
                        else None,
                        "supporting_work_state": entity.get("supporting_work_state")
                        if entity
                        else None,
                        "snippet": next(
                            (
                                h.get("snippet", "")
                                for h in hit.get("highlights", [])
                                if h.get("field") == "text"
                            ),
                            "",
                        )[:500],
                    }
                )
            return {
                "publication_id": model.publication_id,
                "model_snapshot_id": model.snapshot,
                "results": results,
                "next_page": page + 1 if len(results) == limit and page < 100 else None,
                "search_cutoff": bool(found.get("search_cutoff")),
                "retrieval": "literal keywords, typo tolerance, 5:1 title/body weighting; relevance does not establish suitability",
                "coverage": {
                    "native_source_books": len(editions),
                    "books_with_recipe_records": db.execute(
                        "select count(distinct edition_id) from entities where kind='recipe'"
                    ).fetchone()[0],
                    "interpretation": "Partial. Search kinds=['source'] as well when seeking recipes across books without recipe records; empty recipe results are not proof of no suitable recipe.",
                },
            }

    def publication(self, pub):
        if pub is None:
            p = self.runtime.active()
            if not p:
                raise IntegrityError("unavailable publication")
            pub = p["publication_id"]
        self.runtime.manifest(pub)
        return pub

    @contextmanager
    def db(self, pub):
        path = self.runtime.root / "versions" / pub / "runtime/index.sqlite"
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def book(self, db, book, source=None):
        r = db.execute(
            "select b.*,s.format,s.sha256,s.original_path,s.toc from books b join sources s on b.source_id=s.id where b.id=?",
            (book,),
        ).fetchone()
        if r is None or (source and r["source_id"] != source):
            raise IntegrityError("unavailable identifier")
        return r

    def extraction_version(self, pub):
        with self.db(pub) as db:
            return db.execute("select extraction_version from info").fetchone()[0]

    def citation(self, pub, book, section=None):
        d = {
            "publication_id": pub,
            "book_id": book["id"],
            "title": book["title"],
            "authors": json.loads(book["authors"]),
            "source_id": book["source_id"],
            "format": book["format"],
            "source_sha256": book["sha256"],
        }
        if section:
            d.update(
                section_id=section["id"],
                section_title=section["title"],
                locator=json.loads(section["locator"]),
                extraction={
                    "provenance": section["provenance"],
                    "version": self.extraction_version(pub),
                },
            )
        if section and d["locator"]["kind"] == "page":
            d["page_id"] = section["id"]
        return d

    def search(
        self,
        query,
        mode="fulltext",
        publication_id=None,
        book_ids=None,
        author=None,
        tag=None,
        format=None,
        limit=10,
        offset=0,
    ):
        if (
            not 1 <= limit <= 20
            or not 0 <= offset <= 10000
            or len(query) > 200
            or mode not in ("fulltext", "catalog")
        ):
            raise IntegrityError("invalid search request")
        if offset and not publication_id:
            raise IntegrityError("continuation requires publication")
        if book_ids and len(book_ids) > 100:
            raise IntegrityError("too many book identifiers")
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            where = []
            args = []
            if book_ids:
                where.append("b.id in (" + ",".join("?" for _ in book_ids) + ")")
                args += book_ids
            if author:
                where.append("b.authors like ?")
                args += ["%" + author[:100] + "%"]
            if tag:
                where.append("exists(select 1 from json_each(b.tags) where value=?)")
                args += [tag[:100]]
            if format:
                where.append("s.format=?")
                args += [format.upper()]
            if mode == "catalog":
                where.append("(b.title like ? or b.authors like ? or b.tags like ?)")
                args += ["%" + query + "%"] * 3
                sql = (
                    "select b.*,s.format,s.sha256 from books b join sources s on b.source_id=s.id where "
                    + " and ".join(where)
                    + " order by b.title,b.id"
                )
                rows = db.execute(sql, args).fetchall()
                grouped = {}
                for r in rows:
                    grouped.setdefault(r["source_id"], []).append(r)
                groups = list(grouped.values())
                results = []
                for g in groups[offset : offset + limit]:
                    results.append(
                        {
                            "citation": self.citation(pub, g[0]),
                            "aliases": [r["id"] for r in g],
                            "calibre_ids": [r["calibre_id"] for r in g],
                        }
                    )
                more = offset + limit < len(groups)
            else:
                words = re.findall(r"\w+", query, flags=re.UNICODE)
                if not words:
                    return {"publication_id": pub, "results": [], "next_offset": None}
                fts = " AND ".join('"' + w + '"' for w in words)
                # Source grouping before pagination preserves duplicate identities without repeated hits.
                condition = (" and " + " and ".join(where)) if where else ""
                sql = (
                    """select search.section_id, search.source_id, snippet(search,3,'','', ' … ',40) as snippet, bm25(search) as rank
                    from search where search match ? and exists
                    (select 1 from books b join sources s on s.id=b.source_id where b.source_id=search.source_id"""
                    + condition
                    + ") order by rank,search.section_id limit ? offset ?"
                )
                rows = db.execute(sql, [fts] + args + [limit + 1, offset]).fetchall()
                more = len(rows) > limit
                results = []
                for r in rows[:limit]:
                    aliases = db.execute(
                        "select b.*,s.format,s.sha256 from books b join sources s on b.source_id=s.id where b.source_id=?"
                        + condition
                        + " order by b.id",
                        [r["source_id"]] + args,
                    ).fetchall()
                    sec = db.execute(
                        "select * from sections where id=?", (r["section_id"],)
                    ).fetchone()
                    results.append(
                        {
                            "citation": self.citation(pub, aliases[0], sec),
                            "aliases": [a["id"] for a in aliases],
                            "snippet": r["snippet"][:500],
                            "rank": r["rank"],
                        }
                    )
        return {
            "publication_id": pub,
            "results": results,
            "next_offset": offset + limit if more else None,
        }

    def get_book(self, publication_id, book_id, offset=0, limit=30):
        if not 1 <= limit <= 50 or not 0 <= offset <= 100000:
            raise IntegrityError("invalid page bounds")
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            b = self.book(db, book_id)
            toc = json.loads(b["toc"])
            return {
                "citation": self.citation(pub, b),
                "calibre_id": b["calibre_id"],
                "tags": json.loads(b["tags"]),
                "toc": toc[offset : offset + limit],
                "next_offset": offset + limit if offset + limit < len(toc) else None,
                "artifact_id": "original",
                "coverage": {
                    "recipe_labels": "conservative source structure only",
                    "image_association": "EPUB document",
                    "ocr": "English; low-text physical pages",
                },
            }

    def read_section(
        self, publication_id, book_id, source_id, section_id, offset=0, limit=4000
    ):
        if not 1 <= limit <= 12000 or not 0 <= offset <= 1000000:
            raise IntegrityError("invalid passage bounds")
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            b = self.book(db, book_id, source_id)
            s = db.execute(
                "select * from sections where id=? and source_id=?",
                (section_id, source_id),
            ).fetchone()
            if s is None:
                raise IntegrityError("unavailable identifier")
            return {
                "citation": self.citation(pub, b, s),
                "text": s["text"][offset : offset + limit],
                "text_offset": offset,
                "next_offset": offset + limit
                if offset + limit < len(s["text"])
                else None,
                "kind": s["kind"],
                "image_ids": json.loads(s["images"])[:50],
            }

    def cached(self, pub, logical):
        m = self.runtime.manifest(pub)
        e = next((e for e in m.files if e.path == logical), None)
        if not e:
            raise IntegrityError("unavailable asset")
        if e.size > self.cache_bytes:
            raise IntegrityError("asset exceeds cache budget")
        cache = self.runtime.root / "cache"
        cache.mkdir(exist_ok=True, mode=0o700)
        p = cache / e.sha256
        if p.exists() and digest_file(p) == (e.sha256, e.size):
            p.touch()
            return p
        p.unlink(missing_ok=True)
        files = sorted(
            (f for f in cache.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime
        )
        size = sum(f.stat().st_size for f in files)
        for f in files:
            if size + e.size <= self.cache_bytes:
                break
            size -= f.stat().st_size
            f.unlink()
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as f:
            tmp = Path(f.name)
        try:
            verify(self.runtime.store, e.key, e.sha256, e.size, tmp)
            tmp.replace(p)
        finally:
            tmp.unlink(missing_ok=True)
        return p

    def image_metadata(self, db, pub, book, im):
        context = None
        # Older immutable publications remain readable without this additive table.
        if db.execute(
            "select 1 from sqlite_master where type='table' and name='image_context'"
        ).fetchone():
            row = db.execute(
                "select title,section_id from image_context where image_id=?",
                (im["id"],),
            ).fetchone()
            context = dict(row) if row else None
        return {
            "citation": self.citation(pub, book),
            "image_id": im["id"],
            "document": im["document"],
            "caption": im["caption"],
            "recipe_context": context,
        }

    def list_images(
        self, publication_id, book_id, source_id, section_id, offset=0, limit=10
    ):
        if not 1 <= limit <= 20 or not 0 <= offset <= 100000:
            raise IntegrityError("invalid image bounds")
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            b = self.book(db, book_id, source_id)
            section = db.execute(
                "select * from sections where id=? and source_id=?",
                (section_id, source_id),
            ).fetchone()
            if section is None:
                raise IntegrityError("unavailable identifier")
            ids = json.loads(section["images"])
            images = []
            for image_id in ids[offset : offset + limit]:
                im = db.execute(
                    "select id,document,caption from images where id=? and source_id=?",
                    (image_id, source_id),
                ).fetchone()
                if im is None:
                    raise IntegrityError("unavailable identifier")
                images.append(self.image_metadata(db, pub, b, im))
            return {
                "citation": self.citation(pub, b, section),
                "association": "epub_document",
                "images": images,
                "next_offset": offset + limit if offset + limit < len(ids) else None,
            }

    def get_image(self, publication_id, book_id, source_id, image_id):
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            b = self.book(db, book_id, source_id)
            im = db.execute(
                "select * from images where id=? and source_id=?", (image_id, source_id)
            ).fetchone()
            if im is None:
                raise IntegrityError("unavailable identifier")
            metadata = self.image_metadata(db, pub, b, im)
            with self.asset_lock:
                data = self.cached(pub, im["asset"]).read_bytes()
            return metadata, data

    def get_page(self, publication_id, book_id, source_id, physical_page, edge=1600):
        pub = self.publication(publication_id)
        if not 256 <= edge <= 1600:
            raise IntegrityError("invalid rendering bounds")
        with self.db(pub) as db:
            b = self.book(db, book_id, source_id)
            s = db.execute(
                "select * from sections where source_id=? and ordinal=? and kind=?",
                (source_id, physical_page - 1, "page"),
            ).fetchone()
            if s is None:
                raise IntegrityError("unavailable identifier")
            with (
                self.asset_lock,
                tempfile.TemporaryDirectory(dir=self.runtime.root) as d,
            ):
                original = self.cached(pub, b["original_path"])
                png = Path(d) / "page.png"
                render_page(original, b["format"], physical_page, png, edge)
                with Image.open(png) as im:
                    out = io.BytesIO()
                    im.convert("RGB").save(out, "JPEG", quality=85)
                    data = out.getvalue()
            return {
                "citation": self.citation(pub, b, s),
                "text": s["text"][:4000],
                "text_truncated": len(s["text"]) > 4000,
                "width_limit": edge,
            }, data

    def get_artifact(self, publication_id, book_id, source_id, artifact_id):
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            b = self.book(db, book_id, source_id)
            if artifact_id == "original":
                e = next(
                    e
                    for e in self.runtime.manifest(pub).files
                    if e.path == b["original_path"]
                )
                return {
                    "citation": self.citation(pub, b),
                    "artifact_id": "original",
                    "bytes": e.size,
                    "delivery": "not_available_in_local_poc",
                    "reason": "Original-file delivery requires the ChatGPT acceptance test.",
                }
        section = self.read_section(pub, book_id, source_id, artifact_id, limit=12000)
        return {
            "artifact_id": artifact_id,
            "delivery": "derived_text",
            "mime_type": "text/plain",
            **section,
        }
