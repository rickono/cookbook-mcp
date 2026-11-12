"""Read-only library queries and bounded authenticated content responses."""

from __future__ import annotations

import io
import json
import math
import os
import re
import sqlite3
import tempfile
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from .reader_diagnostics import Stage, stage
from .rendering import RenderError, raster, render_page
from .reports import check_region
from .scanned import LABEL
from .storage import IntegrityError, digest_file, has_table, verify

RASTER_BYTES = 8 * 1024**2
RASTER_ENTRIES = 32
JPEG_QUALITY = 85

ZOOM_EDGE = 2400  # largest render for a region zoom; about 25 MB of RGB on a 1 GB host


def crop_region(im, box, edge):
    """Cut a normalized box out of a rendered page and fit it within edge pixels."""
    w, h = im.size
    x0, y0, x1, y1 = box
    im = im.crop((int(x0 * w), int(y0 * h), math.ceil(x1 * w), math.ceil(y1 * h)))
    if max(im.size) > edge:
        im.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    return im


class Library:
    def __init__(
        self,
        runtime,
        cache_bytes=512 * 1024**2,
        search_engine=None,
        *,
        raster_cache_bytes=RASTER_BYTES,
    ):
        self.runtime = runtime
        self.cache_bytes = cache_bytes
        self.asset_lock = threading.Lock()
        self._verified = OrderedDict()
        self.render_lock = threading.Lock()
        self.search_engine = search_engine
        if not 0 <= raster_cache_bytes <= RASTER_BYTES:
            raise ValueError("invalid raster cache budget")
        self.raster_cache_bytes = raster_cache_bytes
        self._rasters = OrderedDict()
        self._raster_size = 0

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
        related_offset=0,
        _reader=False,
    ):
        return self.model(publication_id).read(
            book_id,
            target_id,
            cursor,
            byte_budget,
            node_budget,
            related_offset,
            _reader=_reader,
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

    def withdrawals(self, section, events=None):
        from .withdrawal import current_withdrawals

        locator = json.loads(section["locator"])
        review = locator.get("content_review", {})
        return [
            e
            for e in (
                current_withdrawals(self.runtime.store) if events is None else events
            )
            if review.get("decision_id") in e["affected_decisions"]
            or (
                (section["kind"] == "page" or not review)
                and any(
                    section["source_id"].split(":", 1)[-1] == p["source_sha256"]
                    and p["physical_page"]
                    in locator.get("physical_pages", [locator.get("physical_page")])
                    for p in e["affected_pages"]
                )
            )
        ]

    def suppressed(self, section, events=None):
        return bool(self.withdrawals(section, events)) or bool(
            json.loads(section["locator"]).get("superseded_transcription")
        )

    def eligibility(self, section, events=None):
        withdrawals = self.withdrawals(section, events)
        if withdrawals:
            return {
                "eligible": False,
                "reasons": sorted(
                    {
                        "approval_revoked"
                        if e["action"] == "revoke"
                        else "confirmed_substantive_error"
                        for e in withdrawals
                    }
                ),
                "withdrawals": withdrawals,
            }
        locator = json.loads(section["locator"])
        if locator.get("superseded_transcription"):
            return {"eligible": False, "reasons": ["superseded_transcription"]}
        review = locator.get("content_review")
        if review:
            return {"eligible": review["eligible"], "reasons": review["reasons"]}
        return (
            {
                "eligible": False,
                "reasons": ["legacy_transcription_is_not_complete_content_approval"],
            }
            if "ocr" in section["provenance"]
            else {
                "eligible": False,
                "reasons": ["complete_content_approval_not_recorded"],
            }
        )

    def additive_row(self, db, table, key, value):
        """The row of an additive table whose ``key`` is ``value``; None without one.

        Older immutable publications remain readable without the additive tables.
        """
        if not has_table(db, table):
            return None
        return db.execute(f"select * from {table} where {key}=?", (value,)).fetchone()

    def transcription_counts(self, pub):
        """Scanned sources, applied corrections and unresolved items in a publication.

        Read from each source's transcription summary, so corrections count once they
        are recorded there. Byte-identical Calibre records share a source and count once.
        """
        counts = {"scanned_books": 0, "applied_corrections": 0, "unresolved_items": 0}
        with self.db(pub) as db:
            if not has_table(db, "transcription_sources"):
                return counts
            for (raw,) in db.execute("select summary from transcription_sources"):
                summary = json.loads(raw)
                counts["scanned_books"] += 1
                counts["applied_corrections"] += len(summary["corrections"]["applied"])
                counts["unresolved_items"] += summary["unresolved"]
        return counts

    def citation(self, pub, book, section=None, *, withdrawal_events=None):
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
            with self.db(pub) as db:
                unit = self.additive_row(
                    db, "transcription_units", "section_id", section["id"]
                )
            if unit is not None:
                d["extraction"]["label"] = json.loads(unit["label"])
                # Ledger corrections served in this unit's text: [{id, reviewer}].
                if corrections := json.loads(unit["corrections"]):
                    d["extraction"]["corrections"] = corrections
        if section:
            d["eligibility"] = self.eligibility(section, withdrawal_events)
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
                from .withdrawal import current_withdrawals

                # One fresh control snapshot per query, shared by suppression and
                # citations. Re-reading per hit multiplies remote storage latency.
                withdrawal_events = current_withdrawals(self.runtime.store)
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
                    if self.suppressed(sec, withdrawal_events):
                        continue
                    results.append(
                        {
                            "citation": self.citation(
                                pub,
                                aliases[0],
                                sec,
                                withdrawal_events=withdrawal_events,
                            ),
                            "aliases": [a["id"] for a in aliases],
                            "snippet": r["snippet"][:500],
                            "eligibility": self.eligibility(sec, withdrawal_events),
                            "rank": r["rank"],
                        }
                    )
        return {
            "publication_id": pub,
            "results": results,
            "next_offset": offset + limit if more else None,
        }

    def get_book(
        self, publication_id, book_id, offset=0, limit=30, *, _reader_contents=False
    ):
        if not 1 <= limit <= 50 or not 0 <= offset <= 100000:
            raise IntegrityError("invalid page bounds")
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            b = self.book(db, book_id)
            toc = json.loads(b["toc"])
            if _reader_contents and b["format"] in ("PDF", "DJVU"):
                from .reader_contents import scanned_contents

                toc = scanned_contents(toc)
            coverage = {
                "recipe_labels": "conservative source structure only",
                "image_association": "EPUB document",
                "ocr": "English; low-text physical pages",
            }
            scanned = self.additive_row(
                db, "transcription_sources", "source_id", b["source_id"]
            )
            if scanned is not None:
                summary = json.loads(scanned["summary"])
                coverage = {
                    "recipe_labels": "agent-assembled sections, unapproved",
                    "image_association": "none",
                    "transcription": {
                        "label": LABEL,
                        "pages_total": summary["pages_total"],
                        **summary["coverage"],
                        "unresolved": summary["unresolved"],
                    },
                }
            return {
                "citation": self.citation(pub, b),
                "calibre_id": b["calibre_id"],
                "tags": json.loads(b["tags"]),
                "toc": toc[offset : offset + limit],
                "next_offset": offset + limit if offset + limit < len(toc) else None,
                "artifact_id": "original",
                "coverage": coverage,
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
            from .withdrawal import current_withdrawals

            # One fresh observation per section call keeps text and both
            # eligibility projections consistent without caching current policy.
            withdrawal_events = current_withdrawals(self.runtime.store)
            withdrawn = self.suppressed(s, withdrawal_events)
            result = {
                "citation": self.citation(
                    pub, b, s, withdrawal_events=withdrawal_events
                ),
                "text": "" if withdrawn else s["text"][offset : offset + limit],
                "eligibility": self.eligibility(s, withdrawal_events),
                "text_offset": offset,
                "next_offset": offset + limit
                if not withdrawn and offset + limit < len(s["text"])
                else None,
                "kind": s["kind"],
                "image_ids": json.loads(s["images"])[:50],
            }
            # Scanned units only: where to zoom with get_page(region=box); EPUB is unchanged.
            unit = self.additive_row(db, "transcription_units", "section_id", s["id"])
            if unit is not None:
                result["check_regions"] = json.loads(unit["check_regions"])
            return result

    def section_navigation(
        self, publication_id, book_id, source_id, section_id, offset=0, limit=20
    ):
        """Bounded authored targets and adjacency established by retained contents.

        Native extraction retains no authored reference graph: never infer it from
        wording. Scanned locator references already carry resolved section IDs.
        """
        if not 0 <= offset <= 100000 or not 1 <= limit <= 50:
            raise IntegrityError("invalid relationship bounds")
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            b = self.book(db, book_id, source_id)
            row = db.execute(
                "select * from sections where id=? and source_id=?",
                (section_id, source_id),
            ).fetchone()
            if row is None:
                raise IntegrityError("unavailable identifier")
            refs = json.loads(row["locator"]).get("references", [])
            related = []
            for ref in refs[offset : offset + limit]:
                target = ref.get("target_section_id")
                exists = (
                    target
                    and db.execute(
                        "select 1 from sections where id=? and source_id=?",
                        (target, source_id),
                    ).fetchone()
                )
                related.append(
                    {
                        "label": ref.get("label", "Authored reference"),
                        "section_id": target if exists else None,
                    }
                )
            toc = json.loads(b["toc"])
            ids = list(
                dict.fromkeys(t["section_id"] for t in toc if t.get("section_id"))
            )
            adjacent = []
            if section_id in ids:
                i = ids.index(section_id)
                for n, label in ((i - 1, "Previous section"), (i + 1, "Next section")):
                    if 0 <= n < len(ids):
                        adjacent.append({"label": label, "section_id": ids[n]})
            return {
                "related": related,
                "next_offset": offset + limit if offset + limit < len(refs) else None,
                "adjacent": adjacent,
            }

    def section_pages(self, publication_id, book_id, source_id, section_id):
        """Physical pages of a scanned section, from its locator; None for any other."""
        try:
            pub = self.publication(publication_id)
        except IntegrityError:
            return None
        with self.db(pub) as db:
            s = db.execute(
                "select s.locator from sections s join books b on b.source_id=s.source_id"
                " where s.id=? and s.source_id=? and b.id=?",
                (section_id, source_id, book_id),
            ).fetchone()
        locator = json.loads(s["locator"]) if s else {}
        if locator.get("kind") != "scanned-section":
            return None
        return locator["physical_pages"]

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
        if self._still_verified(p, e) or (
            p.exists() and digest_file(p) == (e.sha256, e.size)
        ):
            p.touch()
            self._remember_verified(p, e)
            return p
        self._verified.pop(e.sha256, None)
        p.unlink(missing_ok=True)
        files = sorted(
            (f for f in cache.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime
        )
        size = sum(f.stat().st_size for f in files)
        for f in files:
            if size + e.size <= self.cache_bytes:
                break
            size -= f.stat().st_size
            self._verified.pop(f.name, None)
            f.unlink()
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as f:
            tmp = Path(f.name)
        try:
            verify(self.runtime.store, e.key, e.sha256, e.size, tmp)
            tmp.replace(p)
        finally:
            tmp.unlink(missing_ok=True)
        self._remember_verified(p, e)
        return p

    # Callers hold asset_lock. A verified cache file is re-hashed only after its
    # device, inode, size, or nanosecond modification/change time differs, as in
    # docs/manifest-cache.md. This detects local changes, not hostile host mutation.
    @staticmethod
    def _fingerprint(path):
        s = path.stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

    def _still_verified(self, path, entry):
        known = self._verified.get(entry.sha256)
        try:
            return known is not None and known == (entry.size, self._fingerprint(path))
        except OSError:
            return False

    def _remember_verified(self, path, entry):
        self._verified[entry.sha256] = (entry.size, self._fingerprint(path))
        self._verified.move_to_end(entry.sha256)
        while len(self._verified) > 4096:
            self._verified.popitem(last=False)

    def image_metadata(self, db, pub, book, im):
        context = None
        # Older immutable publications remain readable without this additive table.
        if has_table(db, "image_context"):
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

    def page_row(self, db, source_id, physical_page):
        s = db.execute(
            "select * from sections where source_id=? and ordinal=? and kind=?",
            (source_id, physical_page - 1, "page"),
        ).fetchone()
        if s is None:
            raise IntegrityError("unavailable identifier")
        return s

    def page_context(
        self, publication_id, book_id, source_id, physical_page, section_id=None
    ):
        """Full page (and optional section) text a transcription report must quote."""
        pub = self.publication(publication_id)
        with self.db(pub) as db:
            b = self.book(db, book_id, source_id)
            if b["format"] not in ("PDF", "DJVU"):
                raise IntegrityError("unsupported page format")
            texts = [self.page_row(db, source_id, physical_page)["text"]]
            if section_id is not None:
                s = db.execute(
                    "select text from sections where id=? and source_id=?",
                    (section_id, source_id),
                ).fetchone()
                if s is None:
                    raise IntegrityError("unavailable identifier")
                texts.append(s["text"])
            return {
                "publication_id": pub,
                "source_sha256": b["sha256"],
                "format": b["format"],
                "texts": texts,
            }

    def get_page(
        self, publication_id, book_id, source_id, physical_page, edge=1600, region=None
    ):
        # Refuse concurrent work rather than accumulating blocked tool threads.
        if not self.render_lock.acquire(blocking=False):
            raise RenderError("renderer busy")
        try:
            return self._get_page(
                publication_id, book_id, source_id, physical_page, edge, region
            )
        finally:
            self.render_lock.release()

    def _get_page(
        self, publication_id, book_id, source_id, physical_page, edge=1600, region=None
    ):
        pub = self.publication(publication_id)
        if not 256 <= edge <= 1600:
            raise IntegrityError("invalid rendering bounds")
        box = check_region(region)
        # A zoom renders the whole page larger, then keeps only the box at <= edge.
        render_edge = (
            edge
            if box is None
            else min(
                ZOOM_EDGE,
                max(edge, math.ceil(edge / max(box[2] - box[0], box[3] - box[1]))),
            )
        )
        with self.db(pub) as db:
            b = self.book(db, book_id, source_id)
            s = self.page_row(db, source_id, physical_page)
            # Consult the current manifest before reuse. Never retain text or access
            # decisions with the pixels. The existing render slot owns this LRU.
            entry = next(
                (
                    e
                    for e in self.runtime.manifest(pub).files
                    if e.path == b["original_path"]
                ),
                None,
            )
            if entry is None or entry.size > self.cache_bytes:
                raise IntegrityError("unavailable original")
            key = (
                b["sha256"],
                entry.sha256,
                entry.size,
                b["format"],
                physical_page,
                edge,
                tuple(box) if box is not None else None,
                render_edge,
                JPEG_QUALITY,
            )
            data = self._rasters.get(key)
            if data is not None:
                with stage(Stage.RASTER_HIT) as span:
                    span.attempt()
                    self._rasters.move_to_end(key)
            else:
                with stage(Stage.RASTER_MISS) as span:
                    span.attempt()
                with tempfile.TemporaryDirectory(dir=self.runtime.root) as d:
                    original = Path(d) / "original"
                    with stage(Stage.ORIGINAL_CACHE) as span:
                        span.attempt()
                        with self.asset_lock:
                            os.link(self.cached(pub, b["original_path"]), original)
                    png = Path(d) / "page.png"
                    with stage(Stage.ORIGINAL_RENDER) as span:
                        span.attempt()
                        render_page(
                            original, b["format"], physical_page, png, render_edge
                        )
                    with stage(Stage.ORIGINAL_ENCODE) as span:
                        span.attempt()
                        with Image.open(png) as im:
                            im = im.convert("RGB")
                            if box is not None:
                                im = crop_region(im, box, edge)
                            out = io.BytesIO()
                            im.save(out, "JPEG", quality=JPEG_QUALITY)
                            data = out.getvalue()
                    raster(data)
                if len(data) <= self.raster_cache_bytes:
                    while self._rasters and (
                        self._raster_size + len(data) > self.raster_cache_bytes
                        or len(self._rasters) >= RASTER_ENTRIES
                    ):
                        _, evicted = self._rasters.popitem(last=False)
                        self._raster_size -= len(evicted)
                    self._rasters[key] = data
                    self._raster_size += len(data)
            with stage(Stage.ORIGINAL_METADATA) as span:
                span.attempt()
                suppressed = self.suppressed(s)
                meta = {
                    "citation": self.citation(pub, b, s),
                    "text": "" if suppressed else s["text"][:4000],
                    "text_truncated": not suppressed and len(s["text"]) > 4000,
                    "width_limit": edge,
                }
            if box is not None:
                meta.update(region=box, render_edge=render_edge)
            return meta, data

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
