"""Synthetic region regressions; no source books, OCR or image processing."""

from copy import deepcopy

import pytest

from cookbook.transcription_boundaries import propose_boundaries, validate_boundaries


def evidence(*page_regions):
    snapshot = {
        "version": "scanned-transcription.v1",
        "edition": {"id": "synthetic", "source_sha256": "0" * 64, "format": "pdf"},
        "pages": [],
        "blocks": [],
        "tables": [],
        "diagnostics": [],
    }
    for number, regions in enumerate(page_regions, 1):
        page_id = f"page-{number}"
        page = {
            "id": page_id,
            "physical_page": number,
            "source_page_sha256": "1" * 64,
            "render_sha256": "2" * 64,
            "render_size": [1000, 1000],
            "source_size": [1000, 1000],
            "render_to_source": [1, 0, 0, 1, 0, 0],
            "recognition": {"method": "synthetic", "artifact_sha256": "3" * 64},
            "lines": [],
        }
        for index, (kind, text, x, y, width, marker) in enumerate(regions):
            line_id = f"p{number}-l{index}"
            page["lines"].append(
                {
                    "id": line_id,
                    "text": text,
                    "polygon": [
                        [x, y],
                        [x + width, y],
                        [x + width, y + 20],
                        [x, y + 20],
                    ],
                    "confidence": None,
                }
            )
            snapshot["blocks"].append(
                {
                    "id": f"p{number}-b{index}",
                    "page_id": page_id,
                    "kind": kind,
                    "line_ids": [line_id],
                    "children": [],
                    "marker": marker,
                }
            )
        snapshot["pages"].append(page)
    return snapshot


def region(kind, text, x=50, y=20, width=350, marker=None):
    return kind, text, x, y, width, marker


def recipe(title, x=50, y=20):
    return [
        region("section_header", title, x, y),
        region("text", "2 cups water", x, y + 40),
        region("text", "3 carrots", x, y + 70),
        region("list_item", "1. Simmer the vegetables.", x, y + 100),
        region("list_item", "2. Stir slowly.", x, y + 130),
    ]


def containing(result, line_id):
    return next(s for s in result["selections"] if line_id in s["line_ids"])


def test_continued_final_step_excludes_mid_page_independent_single_word_sidebar():
    snapshot = evidence(
        recipe("Synthetic stew"),
        [region("list_item", "3. Serve the stew.", y=20)]
        + recipe("Relish", x=600, y=300),
    )
    original = deepcopy(snapshot)
    result = propose_boundaries(snapshot)
    stew, relish = containing(result, "p1-l0"), containing(result, "p2-l1")
    assert stew["kind"] == relish["kind"] == "recipe"
    assert "p2-l0" in stew["line_ids"]
    assert set(stew["line_ids"]).isdisjoint(relish["line_ids"])
    assert result["links"][0]["selection_id"] == stew["id"]
    assert result["links"][0]["line_ids"] == ["p2-l0"]
    assert snapshot == original
    validate_boundaries(snapshot, result)


def test_multi_line_top_heading_is_one_candidate():
    rows = [
        region("title", "Synthetic roots", y=0),
        region("section_header", "with herbs", y=25),
        *recipe("unused")[1:],
    ]
    result = propose_boundaries(evidence(rows))
    assert len(result["selections"]) == 1
    assert result["selections"][0]["kind"] == "recipe"
    assert result["selections"][0]["line_ids"][:2] == ["p1-l0", "p1-l1"]


def test_spanning_heading_supports_two_columns_and_method_lane_continuation():
    snapshot = evidence(
        [
            region("title", "Synthetic two-column dish", width=900),
            region("text", "2 cups water", y=60),
            region("text", "3 carrots", y=90),
            region("list_item", "1. Simmer.", x=600, y=60),
            region("list_item", "2. Stir.", x=600, y=90),
        ],
        [region("list_item", "3. Serve.", x=600)],
    )
    result = propose_boundaries(snapshot)
    assert len(result["selections"]) == 1
    assert result["selections"][0]["kind"] == "recipe"
    assert len(result["selections"][0]["line_ids"]) == 6
    assert len(result["links"]) == 1


def test_narrow_heading_does_not_silently_join_neighboring_ingredient_column():
    snapshot = evidence(
        [
            region("title", "Synthetic two-column dish"),
            region("list_item", "1. Simmer.", y=60),
            region("list_item", "2. Stir.", y=90),
            region("text", "2 cups water", x=600, y=60),
            region("text", "3 carrots", x=600, y=90),
        ]
    )
    result = propose_boundaries(snapshot)
    assert all(s["state"] == "unresolved" for s in result["selections"])
    assert containing(result, "p1-l0")["id"] != containing(result, "p1-l3")["id"]


def test_menu_reference_wine_and_edge_title_never_absorb_previous_recipe():
    snapshot = evidence(
        recipe("Synthetic dessert"),
        [
            region("section_header", "Menu"),
            region("text", "2 carrots", y=50),
            region("text", "3 lemons", y=80),
            region("list_item", "1. Main course", y=110),
            region(
                "reference_entry",
                "Synthetic leaves: an ingredient reference.",
                x=600,
                y=20,
            ),
            region("section_header", "Wine service", y=250),
            region("text", "The host serves wine with dinner.", y=290),
            region("title", "Synthetic tomorrow", y=600),
        ],
    )
    result = propose_boundaries(snapshot)
    assert containing(result, "p1-l0")["line_ids"] == [f"p1-l{n}" for n in range(5)]
    assert containing(result, "p2-l0")["kind"] == "passage"
    assert containing(result, "p2-l4")["kind"] == "reference_entry"
    assert containing(result, "p2-l6")["kind"] == "unclassified"
    assert containing(result, "p2-l6")["state"] == "unresolved"
    edge = containing(result, "p2-l7")
    assert edge["kind"] == "unclassified" and edge["state"] == "unresolved"
    assert not result["links"]


def test_ambiguous_next_step_stays_unresolved_instead_of_choosing_recipe():
    snapshot = evidence(
        recipe("Synthetic left", x=50) + recipe("Synthetic nearby", x=110),
        [region("list_item", "3. Serve when ready.", x=80)],
    )
    # Close, overlapping lanes are insufficient to choose between two recipes.
    result = propose_boundaries(snapshot)
    assert containing(result, "p2-l0")["state"] == "unresolved"
    assert not result["links"]


@pytest.mark.parametrize("first_step,physical_page", [(4, 2), (3, 3)])
def test_number_gap_or_physical_page_gap_refuses_continuation(
    first_step, physical_page
):
    snapshot = evidence(
        recipe("Synthetic dish"), [region("list_item", f"{first_step}. Finish.")]
    )
    snapshot["pages"][1]["physical_page"] = physical_page
    result = propose_boundaries(snapshot)
    assert containing(result, "p2-l0")["state"] == "unresolved"
    assert not result["links"]


def test_picture_and_caption_ownership_unresolved_and_all_lines_retained():
    snapshot = evidence(
        recipe("Synthetic dish")
        + [
            region("picture", "Unlabeled image region", y=300),
            region("caption", "Uncertain caption", y=330),
        ]
    )
    result = propose_boundaries(snapshot)
    assert containing(result, "p1-l5")["state"] == "unresolved"
    assert containing(result, "p1-l6")["state"] == "unresolved"
    assert containing(result, "p1-l5")["id"] != containing(result, "p1-l6")["id"]
    assert result["unresolved_elements"][0]["block_id"] == "p1-b5"
    assert sorted(i for s in result["selections"] for i in s["line_ids"]) == sorted(
        line["id"] for line in snapshot["pages"][0]["lines"]
    )


def test_parent_evidence_is_not_duplicated_and_authored_list_marker_is_used():
    snapshot = evidence(recipe("Synthetic dish"))
    instruction = snapshot["pages"][0]["lines"][3]
    instruction["text"] = "Simmer the vegetables."
    snapshot["blocks"][3]["marker"] = "1."
    snapshot["blocks"].append(
        {
            "id": "container",
            "page_id": "page-1",
            "kind": "group",
            "line_ids": [line["id"] for line in snapshot["pages"][0]["lines"]],
            "children": [b["id"] for b in snapshot["blocks"]],
            "marker": None,
        }
    )
    result = propose_boundaries(snapshot)
    assert result["selections"][0]["kind"] == "recipe"
    assert len(result["selections"][0]["line_ids"]) == 5
    assert instruction["text"] == "Simmer the vegetables."


def test_picture_instruction_children_remain_readable_without_photo_ownership():
    snapshot = evidence(recipe("Synthetic dish"))
    snapshot["blocks"].append(
        {
            "id": "photo-container",
            "page_id": "page-1",
            "kind": "picture",
            "line_ids": ["p1-l3", "p1-l4"],
            "children": ["p1-b3", "p1-b4"],
            "marker": None,
        }
    )
    result = propose_boundaries(snapshot)
    assert containing(result, "p1-l3")["kind"] == "recipe"
    assert result["unresolved_elements"][0]["block_id"] == "photo-container"


def test_competing_leaf_evidence_remains_unresolved():
    snapshot = evidence(recipe("Synthetic dish"))
    duplicate = deepcopy(snapshot["blocks"][0])
    duplicate["id"] = "competing-heading"
    snapshot["blocks"].append(duplicate)
    result = propose_boundaries(snapshot)
    assert containing(result, "p1-l0")["state"] == "unresolved"
    validate_boundaries(snapshot, result)


@pytest.mark.parametrize(
    "damage", ["digest", "missing", "duplicate", "foreign", "approval", "picture"]
)
def test_validator_rejects_stale_or_invalid_proposals(damage):
    snapshot = evidence(recipe("Synthetic dish") + [region("picture", "Image", y=300)])
    result = propose_boundaries(snapshot)
    if damage == "digest":
        result["snapshot_digest"] = "9" * 64
    elif damage == "missing":
        result["selections"][0]["line_ids"].pop()
    elif damage == "duplicate":
        result["selections"][1]["line_ids"].append("p1-l0")
    elif damage == "foreign":
        result["selections"][0]["line_ids"].append("foreign")
    elif damage == "approval":
        result["selections"][0]["state"] = "approved"
    elif damage == "picture":
        result["unresolved_elements"] = []
    with pytest.raises(ValueError):
        validate_boundaries(snapshot, result)
