"""Synthetic native EPUB interpretation; never invokes OCR or model inference."""

import json
import sqlite3
import uuid
import zipfile

import pytest
from test_book_model import native_build

from cookbook.book_build import structure_build, validate_model
from cookbook.book_interpret import (
    Block,
    blocks_for_book,
    fragmented_page_roles,
    ingredient_fields,
    interpret,
    project_entities,
    proposed_recipes,
    role,
    svg_roles,
)
from cookbook.book_model import BookModel, source_text
from cookbook.storage import IntegrityError, digest_file


@pytest.fixture
def recipe_source(tmp_path):
    _, inputs, book = native_build(tmp_path / "base")
    original = inputs["backup/book.epub"]
    with zipfile.ZipFile(original) as archive:
        package = archive.read("book.opf")
        container = archive.read("META-INF/container.xml")
    ingredients = "".join(
        f'<li class="ing"><p><span class="inline-ing">¼ cup beans {i}, rinsed</span></p></li>'
        for i in range(22)
    )
    body = f'<html><body><h1 class="recipe" id="beans"><span class="inline-title">Beans</span></h1><p><span class="inline-title">Headnote</span> prose.</p><p class="group">For the sauce</p><ul>{ingredients}</ul><p class="step">Simmer with <a href="#stock">stock</a>.</p><p class="cont">Continue simmering, then serve.</p><p class="variation">Variation</p><p>Use red beans instead.</p><p class="section">History</p><p>2 cups beans in a historical essay.</p><h1 class="recipe" id="stock">Stock</h1><p class="ing">1½ cups water</p><p class="step">Boil.</p><h1 class="recipe" id="essay">Essay</h1><p>No ingredient/method markup.</p></body></html>'
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("book.opf", package)
        archive.writestr("chapter.xhtml", body)
    # Update the synthetic build's immutable source identity after replacing bytes.
    sha, _size = digest_file(original)
    index = sqlite3.connect(inputs["runtime/index.sqlite"])
    old = index.execute("select source_id from books").fetchone()[0]
    new = "epub:" + sha
    index.execute("update books set source_id=?", (new,))
    index.execute("update sources set id=?,sha256=? where id=?", (new, sha, old))
    index.commit()
    index.close()
    manifest_path = tmp_path / "base" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for entry in manifest["files"]:
        entry["sha256"], entry["size"] = digest_file(inputs[entry["path"]])
    manifest_path.write_text(json.dumps(manifest))
    published, _ = structure_build(
        tmp_path / "base", tmp_path / "structured", progress=lambda _: None
    )
    path = tmp_path / "structured" / "whole-books.sqlite"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    config = {
        "profiles": {
            "1": {
                "title": ["recipe"],
                "ingredient": ["ing"],
                "instruction": ["step"],
                "instruction_continuation": ["cont"],
                "stop": ["section"],
                "part": {"ingredient_group": ["group"], "variation": ["variation"]},
            }
        },
        "special_books": {},
    }
    report = interpret(db, config, progress=lambda _: None)
    project_entities(db)
    db.close()
    return path, published.publication_id, book, report


def test_source_blocks_boundaries_nested_lists_and_uncertain_uses(recipe_source):
    path, pub, _, report = recipe_source
    assert report["recipe_books"] == 1
    assert report["books"][0]["entity_counts"]["recipe"] == 2
    assert len(report["books"][0]["rejected_headings"]) == 1
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        recipes = {
            r["label"]: json.loads(r["payload"])
            for r in db.execute("select * from entities where kind='recipe'")
        }
        beans = recipes["Beans"]
        text = source_text(db, beans["content_span_ids"])
        assert (
            "Headnote prose" in text and "History" not in text and "Stock" not in text
        )
        assert (
            db.execute(
                "select count(*) from entities where kind='recipe_ingredient'"
            ).fetchone()[0]
            == 23
        )
        uses = [
            json.loads(r[0])
            for r in db.execute("select payload from entities where kind='recipe_use'")
        ]
        assert len(uses) == 1
        assert uses[0]["target_recipe_id"] == recipes["Stock"]["id"]
        assert uses[0]["classification"]["state"] == "unresolved"
        assert uses[0]["scope"]["value"] is None
        assert all(
            json.loads(r[0])["state"] == "candidate"
            for r in db.execute("select payload from entities")
        )
    assert validate_model(path, pub)["entity_counts"]["instruction"] == 3


def test_recipe_children_are_completely_pageable_in_source_order(recipe_source):
    path, pub, book, _ = recipe_source
    with sqlite3.connect(path) as db:
        recipe = db.execute(
            "select id from entities where kind='recipe' and label='Beans'"
        ).fetchone()[0]
        expected = [
            r[0]
            for r in db.execute(
                "select id from entities where json_extract(payload,'$.recipe_id')=? or json_extract(payload,'$.source_recipe_id')=? order by kind,coalesce(json_extract(payload,'$.ordinal'),0),id",
                (recipe, recipe),
            )
        ]
    model = BookModel(path, pub)
    found, offset = [], 0
    while True:
        response = model.read(book, recipe, related_offset=offset)
        found.extend(r["id"] for r in response["related_records"])
        offset = response["next_related_offset"]
        if offset is None:
            break
    assert found == expected and len(found) > 16
    with pytest.raises(IntegrityError):
        model.read(book, recipe, related_offset=-1)
    with pytest.raises(IntegrityError):
        model.read(uuid.uuid4().hex, recipe, related_offset=16)


def test_simple_quantity_and_complex_amounts_remain_honest():
    sid = "a" * 32
    name, quantity, prep = ingredient_fields("1½ cups beans, rinsed", sid)
    assert name["value"] == "beans"
    assert quantity["value"]["amount"] == {"numerator": 3, "denominator": 2}
    assert prep["value"] == "rinsed"
    for wording in (
        "1 cup (120 g) flour",
        "1 to 2 cups flour",
        "1 cup plus 2 tbsp flour",
        "½ cup / 120 ml water",
        "Salt to taste",
        "2 (8-ounce) cans tomatoes",
    ):
        assert ingredient_fields(wording, sid)[1]["state"] == "unparsed"


def test_shared_markup_does_not_make_method_equipment_or_yield_ingredients():
    profile = {
        "ingredient": ["ingred"],
        "instruction": [],
        "role_prefixes": {
            "instruction": ["Method "],
            "equipment": ["Equipment "],
            "yield": ["Yield "],
        },
    }
    for wording, expected in [
        ("1 liter water", "ingredient"),
        ("Method Combine and stir.", "instruction"),
        ("Equipment Strainer", "equipment"),
        ("Yield 1 liter", "yield"),
    ]:
        block = Block(
            "a" * 32, None, "b" * 32, "b" * 32, 1, 2, "p", {"ingred"}, wording
        )
        assert role(block, profile) == expected


def test_existing_supported_fields_and_candidate_ids_survive_rerun(recipe_source):
    path, _, _, _ = recipe_source
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    row = db.execute(
        "select * from entities where kind='recipe_ingredient' limit 1"
    ).fetchone()
    supported = json.loads(row["payload"])
    supported["state"] = "supported"
    supported["method"] = "Synthetic manual source review"
    for field in ("ingredient_name", "quantity", "preparation"):
        if supported[field]["value"] is not None:
            supported[field]["state"] = "supported"
    db.execute(
        "update entities set payload=? where id=?", (json.dumps(supported), row["id"])
    )
    before = dict(db.execute("select kind,count(*) from entities group by kind"))
    config = {
        "profiles": {
            "1": {
                "title": ["recipe"],
                "ingredient": ["ing"],
                "instruction": ["step"],
                "instruction_continuation": ["cont"],
                "stop": ["section"],
                "part": {"ingredient_group": ["group"], "variation": ["variation"]},
            }
        },
        "special_books": {},
    }
    interpret(db, config, progress=lambda _: None)
    assert (
        dict(db.execute("select kind,count(*) from entities group by kind")) == before
    )
    assert (
        json.loads(
            db.execute(
                "select payload from entities where id=?", (row["id"],)
            ).fetchone()[0]
        )
        == supported
    )
    db.close()


def test_native_page_roles_keep_uncertain_lists_and_svg_line_fragments():
    def block(i, text):
        ident = f"{i:032x}"
        return Block("a" * 32, None, ident, ident, i, i, "p", set(), text)

    page = [
        block(1, "TUNA WELLINGTON The recipe has a headnote."),
        block(2, "MAKES 2 SERVES 300 g tuna 3 egg yolks"),
        block(3, "Place the tuna in the oven."),
    ]
    fragmented_page_roles(page)
    assert page[0].text == "TUNA WELLINGTON"
    assert "fragment-ingredient-list" in page[1].classes
    assert "fragment-instruction" in page[2].classes
    narrative = [
        block(4, "HOW TO USE THIS BOOK This chapter explains serving."),
        block(5, "This serves as an introduction."),
    ]
    fragmented_page_roles(narrative)
    assert not any(b.classes for b in narrative)
    svg = [
        block(10, "Yogurt"),
        block(11, "Apricots and Curry"),
        block(12, "Serves 8"),
        block(13, "APRICOT CONFIT"),
        block(14, "4 apricots"),
        block(15, "Grapeseed oil"),
        block(16, "Preheat the oven to 350°F."),
        block(17, "and discard the pits."),
    ]
    attrs = {
        b.node: {"style": "font-family:'Akkurat-Light'; font-size:7.861;"} for b in svg
    }
    for b in svg[:2]:
        attrs[b.node]["style"] = "font-family:'Sagan-Bold'; font-size:21.4392;"
    svg_roles(svg, attrs)
    assert all("svg-recipe-title" in b.classes for b in svg[:2])
    assert "svg-component" in svg[3].classes
    assert all("svg-ingredient" in b.classes for b in svg[4:6])
    assert all("svg-instruction" in b.classes for b in svg[6:])


def test_inline_roles_require_complete_text_coverage(recipe_source):
    path, _, book, _ = recipe_source
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        blocks = blocks_for_book(
            db,
            book,
            {
                "title": [],
                "ingredient": [],
                "instruction": [],
                "stop": [],
                "title_inline_classes": ["inline-title"],
                "ingredient_inline_classes": ["inline-ing"],
            },
        )
    by_text = {b.text: b for b in blocks}
    assert "authored-inline-title" in by_text["Beans"].classes
    assert "authored-inline-title" not in by_text["Headnote prose."].classes
    assert sum("authored-inline-ingredient" in b.classes for b in blocks) == 22


def test_profiles_are_bound_to_source_bytes(recipe_source):
    path, _, _, _ = recipe_source
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        report = interpret(
            db,
            {"profiles": {"1": {"source_sha256": "0" * 64}}, "special_books": {}},
            progress=lambda _: None,
        )
    assert report["books"][0]["profile"] is None
    assert (
        report["books"][0]["unresolved_reason"]
        == "Markup profile belongs to different source bytes"
    )


def test_boxed_prose_does_not_require_numeric_quantities_or_include_outro(
    recipe_source,
):
    path, _, book, _ = recipe_source
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        profile = {
            "title": ["recipe"],
            "ingredient": [],
            "instruction": ["step"],
            "stop": [],
            "prose_recipe": True,
            "retain_trailing_document": False,
        }
        blocks = blocks_for_book(db, book, profile)
        title = next(b for b in blocks if b.text == "Beans")
        method = next(b for b in blocks if b.text == "Simmer with stock.")
        outro = next(b for b in blocks if b.text == "History")
        candidates, rejected = proposed_recipes(
            db, book, [title, method, outro], profile
        )
        assert not rejected and len(candidates) == 1
        assert candidates[0][1] == [title, method]
        assert "History" not in source_text(db, candidates[0][0]["content_span_ids"])
