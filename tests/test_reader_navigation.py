"""Synthetic source navigation only; no ingestion, OCR, or inference."""

import json
import sqlite3

from test_reader_content import native_navigation_model

from cookbook.reader_navigation import native_neighbors


def add_occurrence(db, ordinal):
    db.execute(
        "insert into occurrences values(?,?,?,?,?)",
        (
            f"occ-{ordinal}",
            "book",
            "doc",
            ordinal,
            json.dumps({"id": f"occ-{ordinal}", "ordinal": ordinal}),
        ),
    )


def test_occurrence_neighbors_cross_contents_pages_and_stop_at_book_edges(tmp_path):
    model = native_navigation_model(tmp_path)
    with sqlite3.connect(model.path) as db:
        for ordinal in range(65):
            add_occurrence(db, ordinal)
    for ordinal in (0, 29, 30, 59, 60, 64):
        result = native_neighbors(model, "book", f"occ-{ordinal}")
        assert [r["target_id"] for r in result] == [
            f"occ-{i}" for i in (ordinal - 1, ordinal + 1) if 0 <= i < 65
        ]
        assert all(
            r["contents_offset"] == int(r["target_id"].split("-")[1]) // 30 * 30
            for r in result
        )


def test_chapter_neighbors_follow_source_positions_instead_of_contents_order(tmp_path):
    model = native_navigation_model(tmp_path)
    with sqlite3.connect(model.path) as db:
        add_occurrence(db, 0)
        db.execute("update navigation set ordinal=99 where id='nav-first'")
    following = native_neighbors(model, "book", "nav-first")
    assert [(r["label"], r["target_id"], r["title"]) for r in following] == [
        ("Next section", "nav-second", "second")
    ]
    previous = native_neighbors(model, "book", "nav-second")
    assert previous[0]["target_id"] == "nav-first"
    assert previous[0]["contents_offset"] == 0


def test_ambiguous_repeated_document_does_not_invent_a_chapter_neighbor(tmp_path):
    model = native_navigation_model(tmp_path)
    with sqlite3.connect(model.path) as db:
        add_occurrence(db, 0)
        add_occurrence(db, 1)
    assert native_neighbors(model, "book", "nav-first") == []
