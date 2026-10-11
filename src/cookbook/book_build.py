"""Add validated native whole-book structure to an existing immutable EPUB build."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from .book_capture import capture, key
from .book_model import (
    MODEL_PATH,
    REPORT_PATH,
    bounds,
    connection,
    payload,
    source_text,
)
from .book_types import (
    ContentNode,
    SemanticEntity,
    SemanticRelation,
    SourceSpan,
    UnresolvedContent,
)
from .publication import Entry, Manifest
from .quality import QUALITY_PATH, make_report
from .storage import IntegrityError, atomic_write, canonical, digest_file

SEMANTIC = TypeAdapter(SemanticEntity)
NODES = TypeAdapter(ContentNode)


def import_interpretations(db, path):
    """Import evidence over exactly matching originals; never promote interpretation states."""
    if path is None:
        return
    with connection(path) as source:
        for row in source.execute("select * from editions"):
            old = payload(row)
            current = db.execute(
                "select payload from editions where id=?", (row["id"],)
            ).fetchone()
            if (
                current is None
                or payload(current)["source_sha256"] != old["source_sha256"]
            ):
                raise IntegrityError(
                    "interpretation edition is outside this publication"
                )
        for table in ("spans", "entities", "relations", "issues"):
            columns = [r[1] for r in source.execute("pragma table_info(" + table + ")")]
            for row in source.execute("select * from " + table):
                if table == "entities":
                    SEMANTIC.validate_json(row["payload"])
                elif table == "spans":
                    SourceSpan.model_validate_json(row["payload"])
                db.execute(
                    "insert or ignore into "
                    + table
                    + " values ("
                    + ",".join("?" for _ in columns)
                    + ")",
                    tuple(row),
                )


def index_units(db):
    db.executescript("""
        CREATE TABLE search_units(id TEXT PRIMARY KEY,edition_id TEXT,target_id TEXT,kind TEXT,state TEXT,title TEXT,text TEXT);
        CREATE INDEX units_target ON search_units(target_id);
        CREATE INDEX nodes_document ON nodes(document_id,preorder);
        CREATE INDEX recipe_children ON entities(edition_id,kind,json_extract(payload,'$.recipe_id'));
        CREATE INDEX recipe_uses ON entities(edition_id,kind,json_extract(payload,'$.source_recipe_id'));
    """)

    def insert(edition, target, kind, state, title, text):
        if not text.strip():
            return
        # Search-only chunks retain the complete canonical reading target.
        for ordinal, start in enumerate(range(0, len(text), 18000)):
            unit = key(target, ordinal, "whole-book-search-v1")
            db.execute(
                "insert into search_units values(?,?,?,?,?,?,?)",
                (
                    unit,
                    edition,
                    target,
                    kind,
                    state,
                    title or "",
                    text[start : start + 18000],
                ),
            )

    for row in db.execute("select * from entities order by id").fetchall():
        entity = payload(row)
        spans = (
            entity.get("content_span_ids")
            or entity.get("source_span_ids")
            or entity["evidence_span_ids"]
        )
        title = (entity.get("title") or entity.get("label") or {}).get("value")
        insert(
            row["edition_id"],
            row["id"],
            row["kind"],
            entity["state"],
            title,
            source_text(db, spans),
        )

    # Index outer readable blocks so phrases survive emphasis and other inline markup.
    block_kinds = {
        "paragraph",
        "heading",
        "list_item",
        "table_cell",
        "caption",
        "quotation",
        "code",
    }
    for document in db.execute("select * from documents order by id").fetchall():
        rows = db.execute(
            "select * from nodes where document_id=? order by preorder",
            (document["id"],),
        ).fetchall()
        covered_until = -1
        for row in rows:
            if row["preorder"] <= covered_until or row["content_kind"] == "non_reading":
                if row["content_kind"] == "non_reading":
                    covered_until = max(covered_until, row["subtree_end"])
                continue
            if row["content_kind"] not in block_kinds and row["node_kind"] != "text":
                continue
            if row["node_kind"] == "text" and not row["text"].strip():
                continue
            covered_until = row["subtree_end"]
            span = SourceSpan(
                id=key(row["id"], "native-search-span-v1"),
                edition_id=document["edition_id"],
                locator_version="source-dom-v1",
                parts=[
                    {
                        "document_id": document["id"],
                        "reading_occurrence_id": None,
                        "start": {
                            "node_id": row["id"],
                            "side": "before",
                            "offset": None,
                        },
                        "end": {"node_id": row["id"], "side": "after", "offset": None},
                    }
                ],
            )
            db.execute(
                "insert into spans values(?,?,?)",
                (span.id, span.edition_id, span.model_dump_json()),
            )
            text = source_text(db, [span.id])
            insert(
                document["edition_id"],
                span.id,
                "source",
                "native",
                text[:160] if row["content_kind"] == "heading" else "",
                text,
            )
        db.commit()


def validate_model(path, publication_id, runtime_index=None):
    """Check source ownership, ordered trees, typed references, evidence and search targets."""
    with connection(path) as db:
        # This is one bounded validation connection, not a per-request cache.
        # Repeated parent/span lookups otherwise thrash a large on-volume index.
        db.execute("pragma cache_size=-131072")
        if db.execute("pragma integrity_check").fetchone()[0] != "ok":
            raise IntegrityError("invalid whole-book database")
        info_row = db.execute("select payload from model_info").fetchone()
        if not info_row or json.loads(info_row[0])["publication_id"] != publication_id:
            raise IntegrityError("whole-book publication mismatch")
        editions = {r["id"]: payload(r) for r in db.execute("select * from editions")}
        if runtime_index:
            with connection(runtime_index) as index:
                admitted = {
                    r["id"]: r["source_id"]
                    for r in index.execute("select id,source_id from books")
                }
                if set(editions) != set(admitted) or any(
                    e["source_id"] != admitted[i] for i, e in editions.items()
                ):
                    raise IntegrityError(
                        "whole-book selection differs from publication"
                    )
        documents = {r["id"]: r for r in db.execute("select * from documents")}
        counts = Counter()
        for document in documents.values():
            meta = payload(document)
            total = db.execute(
                "select count(*) from nodes where document_id=?", (document["id"],)
            ).fetchone()[0]
            body_hash = hashlib.sha256()
            seen = 0
            for row in db.execute(
                "select * from nodes where document_id=? order by preorder",
                (document["id"],),
            ):
                node = NODES.validate_json(row["payload"])
                if (
                    node.id != row["id"]
                    or node.document_id != document["id"]
                    or node.preorder != seen
                    or node.parent_id != row["parent_id"]
                    or node.kind != row["node_kind"]
                ):
                    raise IntegrityError("invalid canonical node identity/order")
                seen += 1
                if node.kind == "text":
                    if node.text != row["text"] or row["subtree_end"] != node.preorder:
                        raise IntegrityError("native source text differs")
                    body_hash.update(node.text.encode())
                elif (
                    node.subtree_end != row["subtree_end"]
                    or not node.preorder <= node.subtree_end < total
                ):
                    raise IntegrityError("invalid canonical subtree")
            if (
                body_hash.hexdigest() != meta["body_text_sha256"]
                or db.execute(
                    "select 1 from nodes where id=? and document_id=? and parent_id is null",
                    (document["root_id"], document["id"]),
                ).fetchone()
                is None
            ):
                raise IntegrityError("native source text differs")
            counts["nodes"] += seen
        invalid = db.execute("""select 1 from nodes n left join nodes p on p.id=n.parent_id
            where n.parent_id is not null and (p.id is null or p.document_id!=n.document_id or p.node_kind!='element'
            or n.preorder<=p.preorder or n.subtree_end>p.subtree_end
            or json_extract(p.payload,'$.child_ids[' || json_extract(n.payload,'$.child_ordinal') || ']') is not n.id) limit 1""").fetchone()
        if invalid:
            raise IntegrityError("invalid canonical parent/child membership")
        invalid = db.execute("""select 1 from nodes p,json_each(p.payload,'$.child_ids') child
            left join nodes n on n.id=child.value where p.node_kind='element' and (n.id is null or n.parent_id is not p.id
            or json_extract(n.payload,'$.child_ordinal')!=cast(child.key as integer)) limit 1""").fetchone()
        if invalid:
            raise IntegrityError("invalid canonical subtree")
        # Spans are streamed: a library-wide source index must not load hundreds of
        # thousands of nested selections into memory during runtime activation.
        for row in db.execute("select * from spans"):
            span = payload(row)
            SourceSpan.model_validate(span)
            if span["id"] != row["id"] or span["edition_id"] != row["edition_id"]:
                raise IntegrityError("invalid span identity")
            for part in span["parts"]:
                if (
                    part["document_id"] not in documents
                    or documents[part["document_id"]]["edition_id"]
                    != span["edition_id"]
                ):
                    raise IntegrityError("cross-edition evidence")
                bounds(db, part)
                if part["reading_occurrence_id"]:
                    occurrence = db.execute(
                        "select document_id from occurrences where id=?",
                        (part["reading_occurrence_id"],),
                    ).fetchone()
                    if occurrence is None or occurrence[0] != part["document_id"]:
                        raise IntegrityError("invalid reading occurrence")
        entities = {r["id"]: payload(r) for r in db.execute("select * from entities")}
        references = {
            "recipe_id": "recipe",
            "source_recipe_id": "recipe",
            "target_recipe_id": "recipe",
            "part_id": "recipe_part",
            "parent_part_id": "recipe_part",
            "source_part_id": "recipe_part",
            "selected_part_id": "recipe_part",
            "selected_formulation_id": "recipe_formulation",
            "recipe_ingredient_id": "recipe_ingredient",
            "instruction_id": "instruction",
            "recipe_use_id": "recipe_use",
            "passage_id": "passage",
            "subject_entry_id": "reference_entry",
            "attribution_entity_id": "attribution",
            "parent_division_id": "division",
        }

        def evidence(value, edition):
            if isinstance(value, dict):
                for name, v in value.items():
                    if name.endswith("span_ids"):
                        if any(
                            db.execute(
                                "select 1 from spans where id=? and edition_id=?",
                                (sid, edition),
                            ).fetchone()
                            is None
                            for sid in v
                        ):
                            raise IntegrityError("invalid semantic evidence")
                    else:
                        evidence(v, edition)
            elif isinstance(value, list):
                for v in value:
                    evidence(v, edition)

        for entity in entities.values():
            SEMANTIC.validate_python(entity)
            evidence(entity, entity["edition_id"])
            for field, kind in references.items():
                target = entity.get(field)
                if target and (
                    target not in entities
                    or entities[target]["kind"] != kind
                    or entities[target]["edition_id"] != entity["edition_id"]
                ):
                    raise IntegrityError("invalid typed semantic reference")
            for field in ("selected_part_id", "selected_formulation_id"):
                if (
                    entity.get(field)
                    and entities[entity[field]]["recipe_id"]
                    != entity["target_recipe_id"]
                ):
                    raise IntegrityError("invalid selected preparation ownership")
            counts[entity["kind"]] += 1
        for row in db.execute("select payload from relations"):
            relation = SemanticRelation.model_validate(payload(row))
            evidence(relation.model_dump(), relation.edition_id)
            for target in (relation.source_entity_id, relation.target_entity_id):
                if target and (
                    target not in entities
                    or entities[target]["edition_id"] != relation.edition_id
                ):
                    raise IntegrityError("cross-edition semantic relation")
        for row in db.execute("select payload from issues"):
            issue = UnresolvedContent.model_validate(payload(row))
            evidence(issue.model_dump(), issue.edition_id)
            if issue.edition_id not in editions:
                raise IntegrityError("invalid unresolved content ownership")
        invalid = db.execute("""select 1 from search_units u left join entities e on e.id=u.target_id
            left join spans s on s.id=u.target_id where coalesce(e.edition_id,s.edition_id) is not u.edition_id
            or (e.id is not null and (e.kind!=u.kind or json_extract(e.payload,'$.state')!=u.state))
            or (e.id is null and u.kind!='source') limit 1""").fetchone()
        if invalid:
            raise IntegrityError("invalid search reading target")
        return {
            "editions": len(editions),
            "nodes": counts.pop("nodes", 0),
            "entity_counts": dict(counts),
            "search_units": db.execute("select count(*) from search_units").fetchone()[
                0
            ],
            "spans": db.execute("select count(*) from spans").fetchone()[0],
        }


def structure_build(build, output, interpretation=None, progress=print):
    """Create a new publication from an unchanged admitted source build, without re-ingestion."""
    build, output = Path(build).resolve(), Path(output).resolve()
    if output.exists():
        raise IntegrityError("structured build output must be new")
    manifest = Manifest.model_validate_json((build / "manifest.json").read_bytes())
    inputs = {
        k: Path(v) for k, v in json.loads((build / "inputs.json").read_bytes()).items()
    }
    for entry in manifest.files:
        if entry.path not in inputs or digest_file(inputs[entry.path]) != (
            entry.sha256,
            entry.size,
        ):
            raise IntegrityError("base build input differs from manifest")
    original_index = inputs["runtime/index.sqlite"]
    with connection(original_index) as index:
        if (
            index.execute("select publication_id from info").fetchone()[0]
            != manifest.publication_id
        ):
            raise IntegrityError("base build publication mismatch")
        books = [
            dict(r)
            for r in index.execute(
                "select b.*,s.format,s.original_path from books b join sources s on s.id=b.source_id order by b.calibre_id"
            )
        ]
    if any(b["format"] != "EPUB" for b in books):
        raise IntegrityError(
            "native whole-book build requires EPUBs; PDF/DjVu remains resource-gated"
        )
    for book in books:
        book["path"] = inputs[book["original_path"]]
    output.mkdir(mode=0o700, parents=True)
    pub = uuid.uuid4().hex
    index_path = output / "index.sqlite"
    shutil.copyfile(original_index, index_path)
    with sqlite3.connect(index_path) as index:
        index.execute("update info set publication_id=?", (pub,))
    inputs = {k: v for k, v in inputs.items() if k not in (MODEL_PATH, REPORT_PATH)}
    inputs["runtime/index.sqlite"] = index_path
    model_path = output / "whole-books.sqlite"
    captures = capture(books, pub, model_path, progress)
    implementation = hashlib.sha256(
        b"".join(
            Path(__file__).with_name(f).read_bytes()
            for f in (
                "book_build.py",
                "book_capture.py",
                "book_types.py",
                "book_model.py",
            )
        )
    ).hexdigest()
    interpretation_sha = digest_file(interpretation)[0] if interpretation else None
    snapshot = {
        "id": key(pub, implementation, interpretation_sha, "whole-book-snapshot-v1"),
        "source_publication_id": manifest.publication_id,
        "extractor_version": "epub-native-dom-v1",
        "interpretation_version": "imported-source-evidence-v1"
        if interpretation
        else "unassessed-v1",
        "locator_version": "source-dom-v1",
        "implementation_sha256": implementation,
    }
    info = {
        "publication_id": pub,
        "model_snapshot": snapshot,
        "schema_version": "whole-book-draft-v1",
        "interpretation_sha256": interpretation_sha,
    }
    with sqlite3.connect(model_path) as db:
        db.row_factory = sqlite3.Row
        import_interpretations(db, interpretation)
        db.executescript(
            "CREATE TABLE model_info(payload TEXT); CREATE TABLE coverage(edition_id TEXT PRIMARY KEY,payload TEXT);"
        )
        db.execute("insert into model_info values(?)", (json.dumps(info),))
        for book in books:
            counts = dict(
                db.execute(
                    "select kind,count(*) from entities where edition_id=? group by kind",
                    (book["id"],),
                )
            )
            coverage = {
                "resource_inventory_complete": True,
                "source_tree_complete": True,
                "native_body_text_roundtrip": True,
                "readable_image_text_state": "not_assessed",
                "semantic_state": "partial" if counts else "not_assessed",
                "entity_counts": counts,
                "recipe_boundaries": "candidate or source-supported; inspect record state",
                "parsed_fields": "partial examples; absent fields are unparsed",
                "supporting_work": "partial examples; absence is not proof of no dependency",
            }
            db.execute(
                "insert into coverage values(?,?)", (book["id"], json.dumps(coverage))
            )
        db.commit()
        index_units(db)
    report = {
        **info,
        "validation": validate_model(model_path, pub, index_path),
        "capture": captures,
    }
    atomic_write(output / "whole-books.json", canonical(report))
    inputs[MODEL_PATH] = model_path
    inputs[REPORT_PATH] = output / "whole-books.json"
    atomic_write(output / "ocr-review.json", canonical(make_report(pub, [])))
    inputs[QUALITY_PATH] = output / "ocr-review.json"
    entries = [
        Entry(
            path=k,
            sha256=digest_file(v)[0],
            size=v.stat().st_size,
            role="runtime"
            if k.startswith("runtime/")
            else "backup"
            if k.startswith(("backup/", "quality/"))
            else "asset",
        )
        for k, v in sorted(inputs.items())
    ]
    result = Manifest(
        publication_id=pub,
        created_at=datetime.now(UTC).isoformat(),
        locator_version=manifest.locator_version,
        files=entries,
    )
    atomic_write(output / "manifest.json", canonical(result.model_dump()))
    atomic_write(
        output / "inputs.json", canonical({k: str(v) for k, v in inputs.items()})
    )
    return result, report
