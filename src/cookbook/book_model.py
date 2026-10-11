"""Read immutable whole-book artifacts with source-scoped, bounded continuations."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .storage import IntegrityError, canonical

MODEL_PATH = "runtime/whole-books.sqlite"
REPORT_PATH = "runtime/whole-books.json"


@contextmanager
def connection(path):
    db = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True
    )
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def payload(row):
    if row is None:
        raise IntegrityError("unavailable whole-book identifier")
    return json.loads(row["payload"])


def bounds(db, part):
    a = db.execute(
        "select * from nodes where id=?", (part["start"]["node_id"],)
    ).fetchone()
    b = db.execute(
        "select * from nodes where id=?", (part["end"]["node_id"],)
    ).fetchone()
    if (
        a is None
        or b is None
        or a["document_id"] != part["document_id"]
        or b["document_id"] != part["document_id"]
    ):
        raise IntegrityError("invalid source span")

    def position(node, pos):
        side = pos["side"]
        if side == "before":
            return node["preorder"], 0
        if side == "after":
            return node["subtree_end"] + 1, 0
        offset = pos.get("offset")
        if (
            side != "text_offset"
            or node["node_kind"] != "text"
            or not isinstance(offset, int)
            or not 0 <= offset <= len(node["text"])
        ):
            raise IntegrityError("invalid source offset")
        return node["preorder"], offset

    lo, hi = position(a, part["start"]), position(b, part["end"])
    if lo > hi:
        raise IntegrityError("reversed source span")
    return lo, hi


def source_text(db, span_ids):
    """Rebuild search text from the canonical selection, never from search snippets."""
    out = []
    for sid in span_ids:
        span = payload(
            db.execute("select payload from spans where id=?", (sid,)).fetchone()
        )
        for part in span["parts"]:
            lo, hi = bounds(db, part)
            for row in db.execute(
                "select * from nodes where document_id=? and preorder between ? and ? order by preorder",
                (part["document_id"], lo[0], hi[0]),
            ):
                if row["preorder"] == hi[0] and hi[1] == 0:
                    break
                if row["node_kind"] == "text":
                    start = lo[1] if row["preorder"] == lo[0] else 0
                    end = hi[1] if row["preorder"] == hi[0] else len(row["text"])
                    out.append(row["text"][start:end])
                elif row["content_kind"] == "image":
                    out.append(" [uninterpreted image] ")
                elif (
                    row["content_kind"]
                    in {
                        "paragraph",
                        "heading",
                        "table_row",
                        "table_cell",
                        "list_item",
                        "line_break",
                        "caption",
                    }
                    or row["content_kind"] == "container"
                    and payload(row)["source_tag"].split("}")[-1]
                    in {"div", "section", "article"}
                ):
                    out.append("\n")
            out.append("\n")
    return "".join(out).strip()


class BookModel:
    def __init__(self, path, publication_id):
        self.path = Path(path)
        self.publication_id = publication_id
        with connection(self.path) as db:
            info = json.loads(
                db.execute("select payload from model_info").fetchone()[0]
            )
        if info["publication_id"] != publication_id:
            raise IntegrityError("whole-book publication mismatch")
        self.info = info
        self.snapshot = info["model_snapshot"]["id"]

    def edition(self, db, book_id):
        return payload(
            db.execute("select payload from editions where id=?", (book_id,)).fetchone()
        )

    def citation(self, edition, **locator):
        return {
            "publication_id": self.publication_id,
            "model_snapshot_id": self.snapshot,
            "book_id": edition["id"],
            "source_id": edition["source_id"],
            "source_sha256": edition["source_sha256"],
            "title": edition["title"],
            "authors": edition["authors"],
            "format": edition["format"],
            **locator,
        }

    def coverage(self, db, book_id):
        coverage = json.loads(
            db.execute(
                "select payload from coverage where edition_id=?", (book_id,)
            ).fetchone()[0]
        )
        coverage["parser_diagnostic_count"] = db.execute(
            "select coalesce(sum(json_array_length(payload,'$.parser_diagnostics')),0) from documents where edition_id=?",
            (book_id,),
        ).fetchone()[0]
        coverage["source_fidelity"] = (
            "Parsed native body text is retained; originals remain authoritative. Parser diagnostics, image text and semantic interpretation are separate coverage limits."
        )
        return coverage

    def describe(self, book_id, offset=0, limit=30):
        if not 1 <= limit <= 50 or not 0 <= offset <= 100000:
            raise IntegrityError("invalid book bounds")
        with connection(self.path) as db:
            edition = self.edition(db, book_id)
            rows = db.execute(
                "select o.payload,d.path,d.root_id from occurrences o join documents d on d.id=o.document_id where o.edition_id=? order by o.ordinal limit ? offset ?",
                (book_id, limit + 1, offset),
            ).fetchall()
            return {
                "citation": self.citation(edition),
                "coverage": self.coverage(db, book_id),
                "reading_order": [
                    {
                        **json.loads(r["payload"]),
                        "resource_path": r["path"],
                        "root_node_id": r["root_id"],
                    }
                    for r in rows[:limit]
                ],
                "next_offset": offset + limit if len(rows) > limit else None,
                "navigation": [
                    payload(r)
                    for r in db.execute(
                        "select payload from navigation where edition_id=? order by ordinal limit ? offset ?",
                        (book_id, limit, offset),
                    )
                ],
                "next_navigation_offset": offset + limit
                if db.execute(
                    "select count(*) from navigation where edition_id=?", (book_id,)
                ).fetchone()[0]
                > offset + limit
                else None,
                "navigation_count": db.execute(
                    "select count(*) from navigation where edition_id=?", (book_id,)
                ).fetchone()[0],
                "entity_counts": dict(
                    db.execute(
                        "select kind,count(*) from entities where edition_id=? group by kind",
                        (book_id,),
                    )
                ),
            }

    def selection(self, db, book_id, target_id):
        occurrence = db.execute(
            "select id,document_id from occurrences where id=? and edition_id=?",
            (target_id, book_id),
        ).fetchone()
        occurrence_id = occurrence["id"] if occurrence else None
        if occurrence:
            target_id = db.execute(
                "select root_id from documents where id=?", (occurrence["document_id"],)
            ).fetchone()[0]
        entity = db.execute(
            "select payload from entities where id=? and edition_id=?",
            (target_id, book_id),
        ).fetchone()
        if entity:
            record = payload(entity)
            spans = (
                record.get("content_span_ids")
                or record.get("source_span_ids")
                or record["evidence_span_ids"]
            )
            parts = []
            for sid in spans:
                span = payload(
                    db.execute(
                        "select payload from spans where id=? and edition_id=?",
                        (sid, book_id),
                    ).fetchone()
                )
                parts.extend(span["parts"])
            return parts, record
        span = db.execute(
            "select payload from spans where id=? and edition_id=?",
            (target_id, book_id),
        ).fetchone()
        if span:
            return payload(span)["parts"], None
        nav = db.execute(
            "select payload from navigation where id=? and edition_id=?",
            (target_id, book_id),
        ).fetchone()
        if nav:
            target = payload(nav)["target"]
            if target["state"] != "resolved_node":
                raise IntegrityError("unresolved navigation target")
            target_id = target["node_id"]
        node = db.execute(
            "select n.id,n.document_id from nodes n join documents d on d.id=n.document_id where n.id=? and d.edition_id=?",
            (target_id, book_id),
        ).fetchone()
        if node is None:
            raise IntegrityError("unavailable whole-book target")
        return [
            {
                "document_id": node["document_id"],
                "reading_occurrence_id": occurrence_id,
                "start": {"node_id": node["id"], "side": "before", "offset": None},
                "end": {"node_id": node["id"], "side": "after", "offset": None},
            }
        ], None

    def read(self, book_id, target_id, cursor=None, byte_budget=16000, node_budget=100):
        if not 2048 <= byte_budget <= 60000 or not 1 <= node_budget <= 300:
            raise IntegrityError("invalid reading budget")
        with connection(self.path) as db:
            edition = self.edition(db, book_id)
            parts, entity = self.selection(db, book_id, target_id)
            signature = hashlib.sha256(
                canonical(
                    [self.publication_id, self.snapshot, book_id, target_id, parts]
                )
            ).hexdigest()
            position = {
                "selection": signature,
                "part": 0,
                "preorder": None,
                "offset": None,
            }
            if cursor:
                try:
                    if len(cursor) > 512:
                        raise ValueError()
                    position = json.loads(base64.urlsafe_b64decode(cursor))
                    if (
                        set(position) != {"selection", "part", "preorder", "offset"}
                        or position["selection"] != signature
                        or type(position["part"]) is not int
                        or not 0 <= position["part"] < len(parts)
                    ):
                        raise ValueError()
                except (ValueError, TypeError, KeyError):
                    raise IntegrityError("invalid source continuation") from None
            response = {
                "citation": self.citation(edition, target_id=target_id),
                "coverage": self.coverage(db, book_id),
                "entity": entity if not cursor else None,
                "nodes": [],
                "citations": [],
                "next_cursor": None,
            }
            if entity and not cursor:
                related = db.execute(
                    "select id,kind,payload from entities where edition_id=? and (json_extract(payload,'$.recipe_id')=? or json_extract(payload,'$.source_recipe_id')=?) order by kind,id limit 17",
                    (book_id, target_id, target_id),
                ).fetchall()
                response["related_records"] = [
                    {"id": r["id"], "kind": r["kind"], "state": payload(r)["state"]}
                    for r in related[:16]
                ]
                response["related_records_truncated"] = len(related) > 16
            # Structural/semantic metadata also counts against the byte budget.
            used = len(canonical(response)) + 600
            if used >= byte_budget:
                raise IntegrityError("metadata exceeds reading budget")

            def continuation(part, preorder, offset):
                state = {
                    "selection": signature,
                    "part": part,
                    "preorder": preorder,
                    "offset": offset,
                }
                response["next_cursor"] = base64.urlsafe_b64encode(
                    canonical(state)
                ).decode()
                return response

            for i in range(position["part"], len(parts)):
                part = parts[i]
                lo, hi = bounds(db, part)
                current = lo
                if i == position["part"] and position["preorder"] is not None:
                    if (
                        type(position["preorder"]) is not int
                        or type(position["offset"]) is not int
                    ):
                        raise IntegrityError("invalid source continuation")
                    current = position["preorder"], position["offset"]
                    if not lo <= current <= hi:
                        raise IntegrityError("invalid source continuation")
                doc = db.execute(
                    "select path from documents where id=? and edition_id=?",
                    (part["document_id"], book_id),
                ).fetchone()
                if doc is None:
                    raise IntegrityError("cross-book source selection")
                citation = {
                    "document_id": part["document_id"],
                    "resource_path": doc["path"],
                    "reading_occurrence_id": part["reading_occurrence_id"],
                    "start": part["start"],
                    "end": part["end"],
                }
                cite_size = len(canonical(citation))
                if used + cite_size > byte_budget:
                    return continuation(i, *current)
                response["citations"].append(citation)
                used += cite_size
                for row in db.execute(
                    "select * from nodes where document_id=? and preorder between ? and ? order by preorder",
                    (part["document_id"], current[0], hi[0]),
                ):
                    if row["preorder"] == hi[0] and hi[1] == 0:
                        break
                    offset = current[1] if row["preorder"] == current[0] else 0
                    if len(response["nodes"]) >= node_budget:
                        return continuation(i, row["preorder"], offset)
                    node = payload(row)
                    item = {"node": node}
                    if node["kind"] == "element" and node["content_kind"] in {
                        "link",
                        "image",
                    }:
                        item["source_links"] = [
                            payload(r)
                            for r in db.execute(
                                "select payload from links where node_id=? and edition_id=? limit 4",
                                (node["id"], book_id),
                            )
                        ]
                    if node["kind"] == "element":
                        item["child_count"] = len(node.pop("child_ids"))
                        item["projection"] = "children follow in source order"
                    if node["kind"] == "text":
                        end = hi[1] if row["preorder"] == hi[0] else len(node["text"])
                        if not 0 <= offset <= end:
                            raise IntegrityError("invalid source continuation")
                        raw = node["text"]
                        item["source_text_range"] = {"start": offset, "end": end}
                        node["text"] = raw[offset:end]
                    size = len(canonical(item))
                    if used + size > byte_budget:
                        if response["nodes"]:
                            return continuation(i, row["preorder"], offset)
                        if node["kind"] != "text":
                            raise IntegrityError(
                                "source node metadata exceeds reading budget"
                            )
                        # Binary search uses serialized UTF-8 bytes, including JSON escapes.
                        left, right = offset, end
                        while left < right:
                            mid = (left + right + 1) // 2
                            node["text"] = raw[offset:mid]
                            item["source_text_range"]["end"] = mid
                            if used + len(canonical(item)) <= byte_budget:
                                left = mid
                            else:
                                right = mid - 1
                        if left == offset:
                            raise IntegrityError(
                                "source node metadata exceeds reading budget"
                            )
                        node["text"] = raw[offset:left]
                        item["source_text_range"]["end"] = left
                        response["nodes"].append(item)
                        return continuation(i, row["preorder"], left)
                    response["nodes"].append(item)
                    used += size
            return response

    def supporting_work(self, book_id, recipe_id, depth=4, limit=30):
        if not 0 <= depth <= 8 or not 1 <= limit <= 100:
            raise IntegrityError("invalid supporting-work budget")
        with connection(self.path) as db:
            edition = self.edition(db, book_id)
            recipe = payload(
                db.execute(
                    "select payload from entities where id=? and edition_id=? and kind='recipe'",
                    (recipe_id, book_id),
                ).fetchone()
            )
            output, cycles, unresolved, choices = [], [], [], []
            queue = [(recipe_id, 0, (recipe_id,))]
            truncated = False
            used = 0
            while queue:
                current, level, path = queue.pop(0)
                for row in db.execute(
                    "select payload from entities where edition_id=? and kind='recipe_choice' and json_extract(payload,'$.recipe_id')=? order by id limit ?",
                    (book_id, current, limit + 1),
                ):
                    choice = payload(row)
                    size = len(canonical(choice))
                    if len(choices) >= limit or used + size > 24000:
                        truncated = True
                        break
                    choices.append(choice)
                    used += size
                for row in db.execute(
                    "select payload from entities where edition_id=? and kind='recipe_use' and json_extract(payload,'$.source_recipe_id')=? order by id",
                    (book_id, current),
                ):
                    use = payload(row)
                    used += len(canonical(use))
                    if len(output) >= limit or used > 24000:
                        truncated = True
                        queue.clear()
                        break
                    output.append(use)
                    classification, scope = (
                        use["classification"]["value"],
                        use["scope"]["value"],
                    )
                    if (
                        classification is None
                        or not use["target_recipe_id"]
                        or scope is None
                    ):
                        unresolved.append(use["id"])
                    if classification != "required":
                        continue
                    if scope != "whole" or not use["target_recipe_id"]:
                        unresolved.append(use["id"])
                        continue
                    target = use["target_recipe_id"]
                    if target in path:
                        cycles.append([*path, target])
                    elif level >= depth:
                        truncated = True
                    else:
                        queue.append((target, level + 1, (*path, target)))
            return {
                "citation": self.citation(
                    edition, target_id=recipe_id, recipe_id=recipe_id
                ),
                "uses": output,
                "choices": choices,
                "cycles": cycles,
                "unresolved_scope_or_target": list(dict.fromkeys(unresolved)),
                "truncated": truncated,
                "supporting_work_state": recipe["supporting_work_state"],
                "coverage": "Only interpreted uses are included; absence of a use is not proof of no supporting work.",
            }
