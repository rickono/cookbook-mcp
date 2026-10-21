"""Validated saved-scan evidence. No IO, model execution, or approval policy."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy

VERSION = "scanned-transcription.v1"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(record, keys, name):
    _require(isinstance(record, dict) and set(record) == set(keys.split()), name)


def _id(value):
    _require(isinstance(value, str) and bool(value.strip()), "invalid ID/label")


def _hash(value):
    _require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
        "invalid SHA-256",
    )


def _number(value):
    _require(
        type(value) in (int, float) and math.isfinite(value), "nonfinite coordinate"
    )


def _positive_int(value):
    _require(type(value) is int and value > 0, "expected positive integer")


def _size(value):
    _require(isinstance(value, list) and len(value) == 2, "invalid size")
    for number in value:
        _number(number)
        _require(number > 0, "nonpositive size")


def _indexed(records, name):
    _require(isinstance(records, list), f"{name} must be a list")
    indexed = {}
    for record in records:
        _require(isinstance(record, dict) and "id" in record, f"invalid {name}")
        _id(record["id"])
        _require(record["id"] not in indexed, f"duplicate {name} ID")
        indexed[record["id"]] = record
    return indexed


def _refs(ids, lines, page_id):
    _require(
        isinstance(ids, list) and all(isinstance(i, str) for i in ids),
        "invalid line references",
    )
    _require(len(ids) == len(set(ids)), "duplicate line references")
    for line_id in ids:
        _require(
            line_id in lines and lines[line_id] == page_id,
            "invalid/cross-page line reference",
        )


def _validate_snapshot(snapshot: dict) -> None:
    """Reject malformed coordinates, source lineage, ownership and references."""
    _keys(snapshot, "version edition pages blocks tables diagnostics", "snapshot shape")
    _require(snapshot["version"] == VERSION, "unsupported snapshot version")
    edition = snapshot["edition"]
    _keys(edition, "id source_sha256 format", "edition shape")
    _id(edition["id"])
    _hash(edition["source_sha256"])
    _require(edition["format"] in ("pdf", "djvu"), "unsupported source format")
    pages = _indexed(snapshot["pages"], "page")
    lines = {}
    physical_pages = set()
    for page in pages.values():
        _keys(
            page,
            "id physical_page source_page_sha256 render_sha256 render_size source_size render_to_source recognition lines",
            "page shape",
        )
        _positive_int(page["physical_page"])
        _require(page["physical_page"] not in physical_pages, "duplicate physical page")
        physical_pages.add(page["physical_page"])
        _hash(page["source_page_sha256"])
        _hash(page["render_sha256"])
        _size(page["render_size"])
        _size(page["source_size"])
        transform = page["render_to_source"]
        _require(
            isinstance(transform, list) and len(transform) == 6,
            "affine transform shape",
        )
        for value in transform:
            _number(value)
        a, b, c, d, e, f = transform
        _require(abs(a * d - b * c) > 1e-12, "degenerate affine transform")
        _keys(page["recognition"], "method artifact_sha256", "recognition shape")
        _id(page["recognition"]["method"])
        _hash(page["recognition"]["artifact_sha256"])
        for line in _indexed(page["lines"], "line").values():
            _keys(line, "id text polygon confidence", "line shape")
            _require(line["id"] not in lines, "duplicate global line ID")
            lines[line["id"]] = page["id"]
            _require(isinstance(line["text"], str), "line text must be a string")
            confidence = line["confidence"]
            if confidence is not None:
                _number(confidence)
                _require(0 <= confidence <= 1, "confidence out of range")
            polygon = line["polygon"]
            _require(
                isinstance(polygon, list) and len(polygon) == 4,
                "polygon needs four vertices",
            )
            for point in polygon:
                _require(isinstance(point, list) and len(point) == 2, "invalid vertex")
                x, y = point
                _number(x)
                _number(y)
                _require(
                    0 <= x <= page["render_size"][0]
                    and 0 <= y <= page["render_size"][1],
                    "polygon outside render",
                )
                sx, sy = a * x + c * y + e, b * x + d * y + f
                _require(
                    -1e-6 <= sx <= page["source_size"][0] + 1e-6
                    and -1e-6 <= sy <= page["source_size"][1] + 1e-6,
                    "polygon outside source",
                )
            area = sum(
                polygon[i][0] * polygon[(i + 1) % 4][1]
                - polygon[(i + 1) % 4][0] * polygon[i][1]
                for i in range(4)
            )
            _require(abs(area) > 1e-9, "degenerate polygon")
    blocks = _indexed(snapshot["blocks"], "block")
    covered = set()
    parent_count = {}
    for block in blocks.values():
        _keys(block, "id page_id kind line_ids children marker", "block shape")
        _require(block["page_id"] in pages, "unknown block page")
        _id(block["kind"])
        _refs(block["line_ids"], lines, block["page_id"])
        covered.update(block["line_ids"])
        _require(
            block["marker"] is None or isinstance(block["marker"], str),
            "invalid list marker",
        )
        children = block["children"]
        _require(
            isinstance(children, list) and all(isinstance(i, str) for i in children),
            "invalid block children",
        )
        _require(
            isinstance(children, list) and len(children) == len(set(children)),
            "duplicate children",
        )
        for child in children:
            _require(
                child in blocks and blocks[child]["page_id"] == block["page_id"],
                "invalid child",
            )
            parent_count[child] = parent_count.get(child, 0) + 1
            _require(parent_count[child] == 1, "multiple block parents")
    _require(covered == set(lines), "unrepresented canonical lines")
    visiting, visited = set(), set()

    def visit(block_id):
        _require(block_id not in visiting, "block hierarchy cycle")
        if block_id in visited:
            return
        visiting.add(block_id)
        for child in blocks[block_id]["children"]:
            visit(child)
        visiting.remove(block_id)
        visited.add(block_id)

    for block_id in blocks:
        visit(block_id)
    cell_ids = set()
    cell_line_ids = set()
    for table in _indexed(snapshot["tables"], "table").values():
        _keys(table, "id block_id page_id rows columns cells", "table shape")
        _require(
            table["block_id"] in blocks
            and blocks[table["block_id"]]["page_id"] == table["page_id"],
            "invalid table block",
        )
        _positive_int(table["rows"])
        _positive_int(table["columns"])
        occupied = set()
        for cell in _indexed(table["cells"], "cell").values():
            _keys(
                cell,
                "id row_start row_end column_start column_end line_ids column_header row_header",
                "cell shape",
            )
            _require(cell["id"] not in cell_ids, "duplicate global cell ID")
            cell_ids.add(cell["id"])
            for key in ("row_start", "row_end", "column_start", "column_end"):
                _require(type(cell[key]) is int, "invalid cell offset")
            _require(
                0 <= cell["row_start"] < cell["row_end"] <= table["rows"]
                and 0 <= cell["column_start"] < cell["column_end"] <= table["columns"],
                "cell outside table grid",
            )
            _refs(cell["line_ids"], lines, table["page_id"])
            _require(
                not cell_line_ids.intersection(cell["line_ids"]),
                "duplicate table line assignment",
            )
            cell_line_ids.update(cell["line_ids"])
            _require(
                set(cell["line_ids"]) <= set(blocks[table["block_id"]]["line_ids"]),
                "cell lines outside table block",
            )
            _require(
                type(cell["column_header"]) is bool
                and type(cell["row_header"]) is bool,
                "invalid header flag",
            )
            for row in range(cell["row_start"], cell["row_end"]):
                for col in range(cell["column_start"], cell["column_end"]):
                    _require((row, col) not in occupied, "overlapping table grid")
                    occupied.add((row, col))
    _require(isinstance(snapshot["diagnostics"], list), "diagnostics must be a list")
    for diagnostic in snapshot["diagnostics"]:
        _keys(diagnostic, "code page_id block_id line_ids detail", "diagnostic shape")
        _id(diagnostic["code"])
        _id(diagnostic["detail"])
        page_id, block_id = diagnostic["page_id"], diagnostic["block_id"]
        _require(page_id is None or page_id in pages, "invalid diagnostic page")
        _require(block_id is None or block_id in blocks, "invalid diagnostic block")
        if block_id is not None:
            _require(blocks[block_id]["page_id"] == page_id, "diagnostic page mismatch")
        if page_id is None:
            _require(
                diagnostic["line_ids"] == [], "global diagnostic cannot have lines"
            )
        else:
            _refs(diagnostic["line_ids"], lines, page_id)


def validate_snapshot(snapshot: dict) -> None:
    """Validate JSON evidence, consistently raising ValueError for malformed data."""
    try:
        _validate_snapshot(snapshot)
    except (KeyError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError("malformed snapshot shape or reference") from error


def snapshot_digest(snapshot: dict) -> str:
    """Bind additive semantic/review proposals to exactly this saved evidence."""
    validate_snapshot(snapshot)
    return hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _bounds(polygon):
    return (
        min(p[0] for p in polygon),
        min(p[1] for p in polygon),
        max(p[0] for p in polygon),
        max(p[1] for p in polygon),
    )


def _bbox(box, height):
    _require(isinstance(box, dict), "missing Docling bbox")
    left, top, right, bottom = [box[k] for k in ("l", "t", "r", "b")]
    for value in (left, top, right, bottom):
        _number(value)
    origin = box.get("coord_origin", "TOPLEFT").upper()
    _require(origin in ("TOPLEFT", "BOTTOMLEFT"), "unknown coordinate origin")
    if origin == "BOTTOMLEFT":
        top, bottom = height - top, height - bottom
    _require(left <= right and top <= bottom, "inverted Docling bbox")
    return left, top, right, bottom


def _adapt_docling(
    edition: dict, pages: list[dict], document: dict, predictions: dict
) -> dict:
    """Adapt saved Docling JSON, preserving frozen recognition and source evidence.

    Prediction page numbers are document-local, mapped to supplied page order.
    Recognition cells must match every raw line exactly once at top level.
    """
    snapshot = {
        "version": VERSION,
        "edition": deepcopy(edition),
        "pages": deepcopy(pages),
        "blocks": [],
        "tables": [],
        "diagnostics": [],
    }
    _require(
        isinstance(document, dict) and isinstance(predictions, dict),
        "saved document/predictions must be objects",
    )
    _require(set(predictions) == {p["id"] for p in pages}, "prediction pages mismatch")
    nodes = {}
    for key in (
        "texts",
        "pictures",
        "tables",
        "groups",
        "key_value_items",
        "form_items",
    ):
        _require(
            isinstance(document.get(key, []), list), "invalid saved node collection"
        )
        for node in document.get(key, []):
            _require(
                isinstance(node, dict) and node.get("self_ref") not in nodes,
                "duplicate Docling node",
            )
            nodes[node["self_ref"]] = node
    page_meta = {}

    def diagnose(code, page_id, block_id, line_ids, detail):
        snapshot["diagnostics"].append(
            {
                "code": code,
                "page_id": page_id,
                "block_id": block_id,
                "line_ids": line_ids,
                "detail": detail,
            }
        )

    for number, page in enumerate(snapshot["pages"], 1):
        doc_page = document.get("pages", {}).get(str(number))
        _require(doc_page is not None, "missing Docling page")
        size = doc_page["size"]
        width, height = size["width"], size["height"]
        _size([width, height])
        sx, sy = width / page["render_size"][0], height / page["render_size"][1]
        page_meta[number] = (page, width, height, sx, sy)
        assignments = {}
        for cluster in predictions[page["id"]].get("layout", {}).get("clusters", []):
            for cell in cluster.get("cells", []):
                index = cell.get("index")
                _require(
                    type(index) is int and 0 <= index < len(page["lines"]),
                    "invalid frozen cell index",
                )
                _require(index not in assignments, "duplicate frozen prediction line")
                line = page["lines"][index]
                _require(
                    cell.get("orig") == line["text"]
                    and cell.get("text") == line["text"],
                    "changed frozen recognition text",
                )
                rect = cell["rect"]
                actual = (
                    min(rect[f"r_x{i}"] for i in range(4)),
                    min(rect[f"r_y{i}"] for i in range(4)),
                    max(rect[f"r_x{i}"] for i in range(4)),
                    max(rect[f"r_y{i}"] for i in range(4)),
                )
                expected = _bounds([[x * sx, y * sy] for x, y in line["polygon"]])
                _require(
                    max(abs(a - b) for a, b in zip(actual, expected)) < 1e-5,
                    "frozen coordinate mismatch",
                )
                l, t, r, b = expected
                actual_vertices = sorted(
                    (rect[f"r_x{i}"], rect[f"r_y{i}"]) for i in range(4)
                )
                expected_vertices = sorted([(l, t), (r, t), (r, b), (l, b)])
                _require(
                    all(
                        abs(x - ex) < 1e-5 and abs(y - ey) < 1e-5
                        for (x, y), (ex, ey) in zip(actual_vertices, expected_vertices)
                    ),
                    "frozen rectangle vertex mismatch",
                )
                assignments[index] = cluster["id"]
        _require(
            set(assignments) == set(range(len(page["lines"]))),
            "missing frozen prediction lines",
        )

    def matches(page_no, box):
        _require(page_no in page_meta, "unknown Docling provenance page")
        page, _, height, sx, sy = page_meta[page_no]
        l, t, r, b = _bbox(box, height)
        found = []
        for line in page["lines"]:
            x = sum(p[0] for p in line["polygon"]) / 4 * sx
            y = sum(p[1] for p in line["polygon"]) / 4 * sy
            if l - 1e-5 <= x <= r + 1e-5 and t - 1e-5 <= y <= b + 1e-5:
                found.append(line["id"])
        return found

    visited, stack = set(), set()

    def walk(ref):
        _require(
            isinstance(ref, dict) and isinstance(ref.get("cref"), str),
            "invalid Docling child reference",
        )
        key = ref["cref"]
        _require(
            key in nodes and key not in stack and key not in visited,
            "invalid/cyclic/repeated Docling child",
        )
        visited.add(key)
        stack.add(key)
        node = nodes[key]
        created = []
        provenance = node.get("prov", [])
        by_page = {}
        for prov in provenance:
            page_no = prov["page_no"]
            ids = matches(page_no, prov["bbox"])
            by_page.setdefault(page_no, []).extend(
                i for i in ids if i not in by_page.get(page_no, [])
            )
        # Structural groups carry no provenance but their children still survive.
        for page_no, ids in by_page.items():
            page = page_meta[page_no][0]
            block = {
                "id": f"{page['id']}:{key}",
                "page_id": page["id"],
                "kind": node.get("label") or "unclassified",
                "line_ids": ids,
                "children": [],
                "marker": node.get("marker") if node.get("enumerated") else None,
            }
            snapshot["blocks"].append(block)
            created.append(block)
            unsupported = [
                name for name in ("annotations", "image", "meta") if node.get(name)
            ]
            if unsupported or key.startswith(("#/key_value_items/", "#/form_items/")):
                diagnose(
                    "unsupported_node_metadata",
                    page["id"],
                    block["id"],
                    ids,
                    "Raw lines retained; saved model metadata requires a separate interpretation: "
                    + ", ".join(unsupported or [key]),
                )
            if key.startswith("#/tables/"):
                data = node.get("data", {})
                table = {
                    "id": f"{block['id']}:table",
                    "block_id": block["id"],
                    "page_id": page["id"],
                    "rows": data.get("num_rows"),
                    "columns": data.get("num_cols"),
                    "cells": [],
                }
                pending = []
                claims = {}
                for i, cell in enumerate(data.get("table_cells", [])):
                    cell_lines = [
                        line_id
                        for line_id in matches(page_no, cell["bbox"])
                        if line_id in ids
                    ]
                    converted = {
                        "id": f"{table['id']}:cell:{i}",
                        "row_start": cell["start_row_offset_idx"],
                        "row_end": cell["end_row_offset_idx"],
                        "column_start": cell["start_col_offset_idx"],
                        "column_end": cell["end_col_offset_idx"],
                        "line_ids": cell_lines,
                        "column_header": cell.get("column_header", False),
                        "row_header": cell.get("row_header", False),
                    }
                    pending.append(converted)
                    for line_id in cell_lines:
                        claims.setdefault(line_id, []).append(converted)
                for line_id, cells in claims.items():
                    if len(cells) > 1:
                        for cell in cells:
                            cell["line_ids"].remove(line_id)
                        diagnose(
                            "ambiguous_table_cell",
                            page["id"],
                            block["id"],
                            [line_id],
                            "Line center belongs to multiple model cells; no quantity association asserted.",
                        )
                table["cells"] = pending
                snapshot["tables"].append(table)
                for cell in pending:
                    if cell["column_header"] and cell["row_start"] > 0:
                        diagnose(
                            "suspicious_column_header",
                            page["id"],
                            block["id"],
                            cell["line_ids"],
                            "Model marks a non-first-row cell as a column header; semantics require review.",
                        )
                unmatched = [line_id for line_id in ids if line_id not in claims]
                if unmatched:
                    diagnose(
                        "unassigned_table_lines",
                        page["id"],
                        block["id"],
                        unmatched,
                        "Canonical lines have no model cell association.",
                    )
        for child in node.get("children", []):
            child_blocks = walk(child)
            for parent in created:
                parent["children"].extend(
                    b["id"] for b in child_blocks if b["page_id"] == parent["page_id"]
                )
        if not provenance and node.get("label") not in (
            "list",
            "group",
            "ordered_list",
            "unordered_list",
        ):
            diagnose(
                "unsupported_node",
                None,
                None,
                [],
                f"Saved node {key} has no supported provenance.",
            )
        stack.remove(key)
        return created

    for container in ("body", "furniture"):
        for child in document.get(container, {}).get("children", []):
            walk(child)
    for key in nodes.keys() - visited:
        diagnose(
            "unreachable_node",
            None,
            None,
            [],
            f"Saved node {key} is outside document roots; preserved as diagnostic.",
        )
        walk({"cref": key})
    covered = {line_id for block in snapshot["blocks"] for line_id in block["line_ids"]}
    for page in snapshot["pages"]:
        missing = [line["id"] for line in page["lines"] if line["id"] not in covered]
        if missing:
            block = {
                "id": f"{page['id']}:unclassified",
                "page_id": page["id"],
                "kind": "unclassified",
                "line_ids": missing,
                "children": [],
                "marker": None,
            }
            snapshot["blocks"].append(block)
            diagnose(
                "unclassified_lines",
                page["id"],
                block["id"],
                missing,
                "Prediction evidence survived but document geometry did not represent these lines.",
            )
    validate_snapshot(snapshot)
    return snapshot


def adapt_docling(
    edition: dict, pages: list[dict], document: dict, predictions: dict
) -> dict:
    """Adapt saved JSON without IO; malformed evidence consistently raises ValueError."""
    try:
        return _adapt_docling(edition, pages, document, predictions)
    except (
        KeyError,
        TypeError,
        OverflowError,
        RecursionError,
        AttributeError,
    ) as error:
        raise ValueError("malformed saved Docling shape or reference") from error
