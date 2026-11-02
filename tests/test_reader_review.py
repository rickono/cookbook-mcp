"""Saved-label review preserves occurrences; entirely synthetic, no reader calls."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts/reader_bench"))

import pipeline
from review import ReviewError, remap_labels


def record(blocks, references=None):
    return {"calls": [{"model": "saved"}], "errors": [], "label": {
        "printed_page": "1", "page_kinds": ["recipe"], "blocks": blocks,
        "references": references or [],
    }}  # fmt: skip


def block(start, end, title="Recipe", part="ingredients"):
    return {"from": start, "to": end, "section_title": title,
            "section_kind": "recipe", "part": part}  # fmt: skip


def test_trace_replays_frozen_and_reviewed_text_with_distinct_authored_origins():
    readers = [f"synthetic#{i}" for i in range(3)]
    page = "FIRST\n\n7g synthetic herb\nSECOND\n7g synthetic herb"
    votes = pipeline.vote(dict.fromkeys(readers, "7g synthetic herb")) * 4
    old, _, old_origins = pipeline.patch_origins(page, votes, readers[0])
    new, _, new_origins = pipeline.patch_origins(page, votes, readers[0], reviewed=True)
    assert old == pipeline.patch(page, votes, readers[0])[0]
    assert new == pipeline.reviewed_patch(page, votes, readers[0])[0] == page
    assert new_origins == [("page", i) for i in (0, 2, 3, 4)]
    assert set(new_origins) < set(old_origins)


def test_remap_deletes_only_removed_addition_and_keeps_authored_repetition():
    source = record([block(1, 2, "First"), block(3, 4, "Second"), block(5, 5)])
    before = copy.deepcopy(source)
    old = [("page", i) for i in range(4)] + [("vote", 0)]
    result = remap_labels(source, old, old[:-1])
    assert result["label"]["blocks"] == source["label"]["blocks"][:2]
    assert result["calls"] == source["calls"]
    assert source == before


def test_remap_moves_following_block_and_reference_by_occurrence():
    old = [("page", 0), ("vote", 0), ("page", 1)]
    source = record(
        [block(1, 2), block(3, 3, part="instructions")],
        [
            {"line": 2, "label": "removed duplicate"},
            {"line": 3, "label": "authored reference"},
        ],
    )
    result = remap_labels(source, old, [old[0], old[2]])
    assert [(b["from"], b["to"]) for b in result["label"]["blocks"]] == [(1, 1), (2, 2)]
    assert result["label"]["references"] == [{"line": 2, "label": "authored reference"}]


@pytest.mark.parametrize("new", [[("page", 1)], [("page", 0), ("page", 0)]])
def test_remap_refuses_unlabelled_or_repeated_occurrence(new):
    with pytest.raises(ReviewError):
        remap_labels(record([block(1, 1)]), [("page", 0)], new)


def test_remap_refuses_moved_occurrences():
    old = [("page", i) for i in range(3)]
    with pytest.raises(ReviewError):
        remap_labels(record([block(1, 3)]), old, list(reversed(old)))


def test_existing_failed_label_evidence_is_preserved():
    source = {"label": None, "errors": ["saved failure"], "calls": ["saved call"]}
    assert remap_labels(source, [("page", 0)], [("page", 0)]) == source
