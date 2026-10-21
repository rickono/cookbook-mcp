"""Boundary regressions using synthetic publisher markup, never book fixtures."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "recipe_catalog_prototype",
    Path(__file__).parents[1] / "scripts/recipe_catalog.prototype.py",
)
prototype = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prototype)


def block(i, cls, text, tag="p"):
    return {
        "i": i,
        "class": cls,
        "tag": tag,
        "text": text,
        "xpath": f"/html/body/{tag}[{i + 1}]",
        "links": [],
    }


def book(documents):
    return {
        "calibre_id": 67,
        "path": "synthetic.epub",
        "id": "synthetic-edition",
        "source_id": "epub:synthetic",
        "sha256": "synthetic",
        "title": "Synthetic book",
        "documents": [
            {"path": f"part-{i}.xhtml", "blocks": rows}
            for i, rows in enumerate(documents)
        ],
    }


def test_continuation_kept_and_unrelated_following_prose_excluded():
    source = book(
        [
            [
                block(0, "recipe_rt", "Synthetic soup"),
                block(1, "recipe_i", "1 cup water"),
            ],
            [block(0, "recipe_rsteps", "Heat and serve.")],
            [block(0, "noindent", "An unrelated essay about knives.")],
        ]
    )
    found, _ = prototype.profile_book(source)
    assert len(found) == 1
    assert [p["document"] for p in found[0]["parts"]] == [
        "part-0.xhtml",
        "part-1.xhtml",
    ]
    assert "Heat and serve." in found[0]["text"]
    assert "unrelated" not in found[0]["text"]


def test_multiline_title_and_instruction_table_retained():
    source = book(
        [
            [
                block(0, "recipe_rt1a", "Synthetic eggs"),
                block(1, "recipe_rt1", "for a crowd"),
                block(2, "recipe_i", "6 eggs"),
                block(3, "recipe_rsteps", "Cook according to this table."),
                block(4, "tdhead", "Cooking time", "td"),
                block(5, "td", "8 minutes", "td"),
                block(6, "caption", "Photo of the next recipe."),
            ]
        ]
    )
    found, _ = prototype.profile_book(source)
    assert found[0]["title"] == "Synthetic eggs for a crowd"
    assert "8 minutes" in found[0]["text"]
    assert "Photo" not in found[0]["text"]


def test_heading_with_quantities_in_prose_is_not_a_recipe():
    source = book(
        [
            [
                block(0, "recipe_rt", "Synthetic history"),
                block(
                    1,
                    "noindent",
                    "People once used 2 cups of water in this old experiment.",
                ),
            ]
        ]
    )
    found, rejected = prototype.profile_book(source)
    assert not found
    assert len(rejected) == 1
