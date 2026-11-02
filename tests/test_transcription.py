"""Synthetic saved-document tests; no OCR, rendering or private source text."""

import math
from copy import deepcopy

import pytest

from cookbook.transcription import adapt_docling, snapshot_digest, validate_snapshot


def saved():
    edition = {"id": "synthetic", "source_sha256": "a" * 64, "format": "pdf"}
    lines = [
        {
            "id": "p:l0",
            "text": "1. Stir the synthetic soup.",
            "polygon": [[10, 10], [90, 10], [90, 20], [10, 20]],
            "confidence": 0.8,
        },
        {
            "id": "p:l1",
            "text": "½",
            "polygon": [[10, 50], [30, 50], [30, 60], [10, 60]],
            "confidence": None,
        },
    ]
    page = {
        "id": "p",
        "physical_page": 1,
        "source_page_sha256": "b" * 64,
        "render_sha256": "c" * 64,
        "render_size": [100, 100],
        "source_size": [50, 50],
        "render_to_source": [0.5, 0, 0, 0.5, 0, 0],
        "recognition": {"method": "synthetic", "artifact_sha256": "d" * 64},
        "lines": lines,
    }

    def box(l, t, r, b):
        return {"l": l, "t": t, "r": r, "b": b, "coord_origin": "TOPLEFT"}

    def prov(bbox):
        return [{"page_no": 1, "bbox": bbox}]

    document = {
        "pages": {"1": {"size": {"width": 50, "height": 50}}},
        "body": {"children": [{"cref": "#/pictures/0"}, {"cref": "#/tables/0"}]},
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "list_item",
                "enumerated": True,
                "marker": "1.",
                "text": "Stir the synthetic soup.",
                "prov": prov(box(5, 5, 45, 10)),
                "children": [],
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "picture",
                "prov": prov(box(0, 0, 50, 15)),
                "children": [{"cref": "#/texts/0"}],
            }
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "children": [],
                "prov": prov(box(0, 20, 50, 40)),
                "data": {
                    "num_rows": 2,
                    "num_cols": 1,
                    "table_cells": [
                        {
                            "bbox": box(0, 20, 50, 40),
                            "start_row_offset_idx": 1,
                            "end_row_offset_idx": 2,
                            "start_col_offset_idx": 0,
                            "end_col_offset_idx": 1,
                            "column_header": True,
                            "row_header": False,
                        }
                    ],
                },
            }
        ],
    }
    cells = []
    for i, line in enumerate(lines):
        rect = {
            f"r_{axis}{n}": p[a] * 0.5
            for n, p in enumerate(line["polygon"])
            for a, axis in enumerate(("x", "y"))
        }
        cells.append(
            {"index": i, "orig": line["text"], "text": line["text"], "rect": rect}
        )
    predictions = {"p": {"layout": {"clusters": [{"id": 0, "cells": cells}]}}}
    return edition, [page], document, predictions


def test_nested_picture_list_marker_and_table_preserve_evidence():
    args = saved()
    original = deepcopy(args)
    snapshot = adapt_docling(*args)
    assert args == original
    assert snapshot["pages"][0]["lines"] == args[1][0]["lines"]
    assert len(snapshot["pages"][0]["lines"]) == 2
    item = next(b for b in snapshot["blocks"] if b["kind"] == "list_item")
    picture = next(b for b in snapshot["blocks"] if b["kind"] == "picture")
    assert item["marker"] == "1."
    assert item["line_ids"] == ["p:l0"]
    assert picture["children"] == [item["id"]]
    assert snapshot["tables"][0]["cells"][0]["line_ids"] == ["p:l1"]
    assert snapshot["diagnostics"][0]["code"] == "suspicious_column_header"
    assert snapshot_digest(snapshot) == snapshot_digest(deepcopy(snapshot))
    snapshot["pages"][0]["lines"][0]["text"] = "changed"
    assert args == original


@pytest.mark.parametrize(
    "failure", ["missing", "duplicate", "changed", "coordinate", "index"]
)
def test_frozen_prediction_failures_refuse(failure):
    args = saved()
    cells = args[3]["p"]["layout"]["clusters"][0]["cells"]
    if failure == "missing":
        cells.pop()
    elif failure == "duplicate":
        cells.append(deepcopy(cells[0]))
    elif failure == "changed":
        cells[0]["orig"] = "plausible replacement"
    elif failure == "coordinate":
        cells[0]["rect"]["r_x0"] += 1
    else:
        cells[0]["index"] = -1
    with pytest.raises(ValueError):
        adapt_docling(*args)


@pytest.mark.parametrize(
    "failure",
    [
        "cross_page",
        "unknown_line",
        "cycle",
        "hash",
        "nan",
        "degenerate",
        "source_bounds",
        "global_duplicate",
        "table_overlap",
        "table_outside",
        "diagnostic",
    ],
)
def test_malformed_snapshot_refuses(failure):
    snapshot = adapt_docling(*saved())
    page = snapshot["pages"][0]
    block = snapshot["blocks"][0]
    if failure == "cross_page":
        block["page_id"] = "unknown"
    elif failure == "unknown_line":
        block["line_ids"] = ["missing"]
    elif failure == "cycle":
        block["children"] = [block["id"]]
    elif failure == "hash":
        snapshot["edition"]["source_sha256"] = "x" * 64
    elif failure == "nan":
        page["lines"][0]["polygon"][0][0] = math.nan
    elif failure == "degenerate":
        page["render_to_source"] = [0, 0, 0, 0, 0, 0]
    elif failure == "source_bounds":
        page["render_to_source"][-1] = 100
    elif failure == "global_duplicate":
        second = deepcopy(page)
        second.update(id="p2", physical_page=2)
        snapshot["pages"].append(second)
    elif failure == "table_overlap":
        cell = deepcopy(snapshot["tables"][0]["cells"][0])
        cell["id"] = "new"
        snapshot["tables"][0]["cells"].append(cell)
    elif failure == "table_outside":
        snapshot["tables"][0]["cells"][0]["row_end"] = 3
    else:
        snapshot["diagnostics"][0]["block_id"] = "missing"
    with pytest.raises(ValueError):
        validate_snapshot(snapshot)


def test_bottom_left_geometry_and_unclassified_lines():
    args = saved()
    args[2]["texts"][0]["prov"][0]["bbox"] = {
        "l": 5,
        "t": 45,
        "r": 45,
        "b": 40,
        "coord_origin": "BOTTOMLEFT",
    }
    args[2]["tables"] = []
    args[2]["body"]["children"].pop()
    snapshot = adapt_docling(*args)
    assert next(b for b in snapshot["blocks"] if b["kind"] == "list_item")[
        "line_ids"
    ] == ["p:l0"]
    assert next(b for b in snapshot["blocks"] if b["kind"] == "unclassified")[
        "line_ids"
    ] == ["p:l1"]


def test_ambiguous_cell_mapping_is_not_guessed():
    args = saved()
    data = args[2]["tables"][0]["data"]
    cell = deepcopy(data["table_cells"][0])
    cell.update(start_row_offset_idx=0, end_row_offset_idx=1)
    data["table_cells"].append(cell)
    snapshot = adapt_docling(*args)
    assert all(c["line_ids"] == [] for c in snapshot["tables"][0]["cells"])
    assert any(d["code"] == "ambiguous_table_cell" for d in snapshot["diagnostics"])
    assert snapshot["pages"][0]["lines"][1]["text"] == "½"


def test_disjoint_table_cells_cannot_duplicate_a_full_source_line():
    snapshot = adapt_docling(*saved())
    table = snapshot["tables"][0]
    other = deepcopy(table["cells"][0])
    other.update(id="other-cell", row_start=0, row_end=1)
    table["cells"].append(other)
    with pytest.raises(ValueError, match="duplicate table line"):
        validate_snapshot(snapshot)


@pytest.mark.parametrize("bad_children", [None, 4, [{}], [False]])
def test_malformed_child_shapes_have_stable_validation_errors(bad_children):
    snapshot = adapt_docling(*saved())
    snapshot["blocks"][0]["children"] = bad_children
    with pytest.raises(ValueError):
        validate_snapshot(snapshot)


@pytest.mark.parametrize("bad_ref", [None, {"cref": {}}, {"cref": "missing"}])
def test_malformed_saved_references_have_stable_validation_errors(bad_ref):
    args = saved()
    args[2]["body"]["children"] = [bad_ref]
    with pytest.raises(ValueError):
        adapt_docling(*args)


def test_unsupported_picture_metadata_is_explicit():
    args = saved()
    args[2]["pictures"][0]["annotations"] = [{"kind": "unsupported"}]
    snapshot = adapt_docling(*args)
    assert any(
        d["code"] == "unsupported_node_metadata" for d in snapshot["diagnostics"]
    )
    assert snapshot["pages"][0]["lines"] == args[1][0]["lines"]
