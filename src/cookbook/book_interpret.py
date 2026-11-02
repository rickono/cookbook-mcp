"""Source-backed EPUB recipe markup interpretation; no OCR, inference or network.

Publisher profiles propose structure. They do not approve completeness, infer
dietary suitability, or turn a hyperlink into a required whole preparation.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from .book_build import SEMANTIC, validate_model
from .book_capture import key
from .book_model import (
    MODEL_PATH,
    REPORT_PATH,
    bounds,
    payload,
    source_text,
)
from .book_types import SourceSpan
from .publication import Entry, Manifest
from .quality import QUALITY_PATH, make_report
from .storage import IntegrityError, atomic_write, canonical, digest_file

PROFILE_PATH = Path(__file__).with_name("recipe_markup.json")
VERSION = "native-recipe-markup-v1"
METHOD = "Native publisher markup; candidate structure, not completeness or dependency approval"
FRACTIONS = {
    "¼": "1/4",
    "½": "1/2",
    "¾": "3/4",
    "⅓": "1/3",
    "⅔": "2/3",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}
UNITS = {
    "g",
    "gram",
    "grams",
    "kg",
    "kilogram",
    "kilograms",
    "ml",
    "milliliter",
    "milliliters",
    "l",
    "liter",
    "liters",
    "oz",
    "ounce",
    "ounces",
    "lb",
    "pound",
    "pounds",
    "cup",
    "cups",
    "tbsp",
    "tablespoon",
    "tablespoons",
    "tsp",
    "teaspoon",
    "teaspoons",
    "quart",
    "quarts",
    "pint",
    "pints",
    "dash",
    "dashes",
    "quantity",
    "recipe",
    "portion",
    "portions",
}
NUMBER = re.compile(
    r"^(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+|[¼½¾⅓⅔⅛⅜⅝⅞]|\d+[¼½¾⅓⅔⅛⅜⅝⅞])\s+(.*)$",
    re.DOTALL,
)


def unknown(reason="Not interpreted from markup", state="unparsed", evidence=()):
    return {
        "state": state,
        "value": None,
        "evidence_span_ids": list(evidence),
        "reason": reason,
    }


def value(v, spans, state="candidate"):
    return {
        "state": state,
        "value": v,
        "evidence_span_ids": list(spans),
        "reason": None,
    }


@dataclass
class Block:
    document: str
    occurrence: str | None
    node: str
    end_node: str
    start: int
    end: int
    tag: str
    classes: set[str]
    text: str


def matches(block, selectors):
    for selector in selectors:
        if "|" in selector:
            tag, cl = selector.split("|", 1)
            if block.tag == tag and (cl in block.classes if cl else not block.classes):
                return True
        elif selector in block.classes:
            return True
    return False


def role(block, profile):
    for kind, prefixes in profile.get("role_prefixes", {}).items():
        if any(
            block.text.casefold().startswith(prefix.casefold()) for prefix in prefixes
        ):
            return kind
    if matches(block, profile["ingredient"]):
        return "ingredient"
    if matches(block, profile["instruction"]):
        return "instruction"
    return None


def svg_roles(blocks, attributes):
    """Retain native SVG text selectors; propose roles from authored typography.

    No rasterization, OCR or coordinate-based transcription. Line fragments stay
    candidate records; paragraph joins and wrapped ingredients require review.
    """
    state = None
    for i, block in enumerate(blocks):
        attrs = attributes[block.node]
        style = attrs.get("style", "")
        size = re.search(r"font-size:\s*([\d.]+)", style)
        size = float(size.group(1)) if size else 0
        if "Sagan" in style and 15 <= size < 35:
            block.classes.add("svg-recipe-title")
            state = None
        elif size >= 7.5 and re.match(r"^(?:Serves|Makes)\b", block.text):
            block.classes.add("svg-yield")
            state = "ingredient"
        elif (
            size >= 7.5
            and "Akkurat" in style
            and block.text.isupper()
            and re.search(r"[A-Z]{3}", block.text)
        ):
            following = blocks[i + 1].text if i + 1 < len(blocks) else ""
            if re.match(r"^(?:Serves|Makes)\b", following):
                block.classes.add("svg-recipe-title")
            else:
                block.classes.add("svg-component")
            state = (
                "instruction"
                if block.text in {"TO FINISH", "TO ASSEMBLE", "TO SERVE"}
                else "ingredient"
            )
        elif size >= 7.5 and "Akkurat" in style and state:
            if state == "ingredient" and re.match(
                r"^(?:Preheat|Heat|Bring|Combine|Whisk|Place|In (?:a|the)|Mix|Add|Put|Peel|Pour|Cut|Transfer|Prepare|To (?:make|finish|assemble))\b",
                block.text,
            ):
                state = "instruction"
            block.classes.add("svg-" + state)


def fragmented_page_roles(blocks):
    """Fish Butchery: whole authored paragraphs; quantities remain unnormalized."""
    by_document = defaultdict(list)
    for block in blocks:
        by_document[block.document].append(block)
    for group in by_document.values():
        ingredient = next(
            (
                i
                for i, b in enumerate(group)
                if re.match(r"^(?:MAKES|SERVES)\b", b.text)
            ),
            None,
        )
        if ingredient is None or ingredient == 0:
            continue
        heading = group[0]
        # A page's recipe title is an initial all-capitals run followed by its
        # headnote. Do not promote chapter headings or arbitrary narrative pages.
        title = re.match(
            r"^([A-Z][A-Z0-9 ’‘&–—,:()/-]{3,})(?=\s+[A-Z][a-z])", heading.text
        )
        if title is None:
            continue
        heading.classes.add("fragment-recipe-title")
        heading.text = title.group(1).strip()
        group[ingredient].classes.add("fragment-ingredient-list")
        for block in group[ingredient + 1 :]:
            block.classes.add("fragment-instruction")


def blocks_for_book(db, edition, profile):
    """Outer text blocks, with inline text intact and no nested li/p duplicates."""
    selectors = set(
        profile.get("title", [])
        + profile.get("ingredient", [])
        + profile.get("instruction", [])
        + profile.get("stop", [])
    )
    selectors.update(s for group in profile.get("part", {}).values() for s in group)
    documents = db.execute(
        "select d.*,o.id as occurrence from documents d join (select document_id,min(ordinal) as ordinal from occurrences group by document_id) first on first.document_id=d.id join occurrences o on o.document_id=d.id and o.ordinal=first.ordinal where d.edition_id=? order by o.ordinal",
        (edition,),
    ).fetchall()
    result = []
    for document in documents:
        rows = db.execute(
            "select * from nodes where document_id=? order by preorder",
            (document["id"],),
        ).fetchall()
        projected = []
        attributes = {}
        for row in rows:
            if row["node_kind"] != "element":
                continue
            meta = payload(row)
            tag = meta["source_tag"].split("}")[-1]
            classes = set(meta["source_attributes"].get("class", "").split())
            attributes[row["id"]] = meta["source_attributes"]
            block = Block(
                document["id"],
                document["occurrence"],
                row["id"],
                row["id"],
                row["preorder"],
                row["subtree_end"],
                tag,
                classes,
                "",
            )
            # Styled divs in many EPUBs are paragraphs. Container wrappers stay
            # structural: only explicit profile classes make them text blocks.
            if (
                tag in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
                or tag == "div"
                and matches(block, selectors)
                or tag == "tr"
                and "table-r" in profile.get("ingredient", [])
                or tag == "text"
                and profile.get("svg_text")
            ):
                projected.append(block)
        covered = -1
        for block in projected:
            if block.start <= covered:
                continue
            text = []
            for row in rows[block.start : block.end + 1]:
                if block.tag == "tr" and row["node_kind"] == "element":
                    block.classes.update(
                        payload(row)["source_attributes"].get("class", "").split()
                    )
                if row["node_kind"] == "text":
                    text.append(row["text"])
                elif row["content_kind"] in {"line_break", "table_cell"}:
                    text.append("\n")
            block.text = re.sub(r"\s+", " ", "".join(text)).strip()
            # Jang places roles in inline spans. Only full paragraph coverage
            # qualifies; bold or differently styled fragments stay source text.
            for marker, classes in {
                "authored-inline-title": profile.get("title_inline_classes", []),
                "authored-inline-ingredient": profile.get(
                    "ingredient_inline_classes", []
                ),
            }.items():
                covered_text = set()
                for row in rows[block.start + 1 : block.end + 1]:
                    if row["node_kind"] != "element":
                        continue
                    child = payload(row)
                    if set(
                        child["source_attributes"].get("class", "").split()
                    ).intersection(classes):
                        covered_text.update(
                            r["preorder"]
                            for r in rows[row["preorder"] : row["subtree_end"] + 1]
                            if r["node_kind"] == "text"
                        )
                child_text = re.sub(
                    r"\s+",
                    " ",
                    "".join(
                        r["text"]
                        for r in rows[block.start : block.end + 1]
                        if r["preorder"] in covered_text
                    ),
                ).strip()
                if child_text and child_text == block.text:
                    block.classes.add(marker)
            covered = block.end
            if block.text:
                result.append(block)
        if profile.get("svg_text"):
            svg_roles([b for b in result if b.document == document["id"]], attributes)
    if profile.get("fragmented_page_text"):
        fragmented_page_roles(result)
    return result


def span(db, edition, blocks):
    parts = []
    for b in blocks:
        # Adjacent blocks may have source nodes between them. Retain those nodes.
        if parts and parts[-1]["document_id"] == b.document:
            parts[-1]["end"]["node_id"] = b.end_node
        else:
            parts.append(
                {
                    "document_id": b.document,
                    "reading_occurrence_id": b.occurrence,
                    "start": {"node_id": b.node, "side": "before", "offset": None},
                    "end": {"node_id": b.end_node, "side": "after", "offset": None},
                }
            )
    obj = SourceSpan(
        id=key(edition, parts, "recipe-interpretation-span-v1"),
        edition_id=edition,
        locator_version="source-dom-v1",
        parts=parts,
    )
    db.execute(
        "insert or ignore into spans values(?,?,?)",
        (obj.id, edition, obj.model_dump_json()),
    )
    return obj.id


def put(db, entity):
    valid = SEMANTIC.validate_python(entity)
    label = (
        entity.get("title")
        or entity.get("label")
        or entity.get("ingredient_name")
        or {}
    ).get("value")
    db.execute(
        "insert or ignore into entities values(?,?,?,?,?)",
        (
            entity["id"],
            entity["edition_id"],
            entity["kind"],
            label,
            valid.model_dump_json(),
        ),
    )
    return entity["id"]


def base(edition, ident, kind, evidence):
    return {
        "id": key(edition, ident, VERSION),
        "edition_id": edition,
        "kind": kind,
        "evidence_span_ids": evidence,
        "state": "candidate",
        "method": METHOD,
    }


def proposed_recipes(db, edition, blocks, profile):
    titles = [i for i, b in enumerate(blocks) if matches(b, profile["title"])]
    starts = [
        i
        for i in titles
        if i == 0 or i - 1 not in titles or blocks[i - 1].document != blocks[i].document
    ]
    found, rejected = [], []
    for ordinal, start in enumerate(starts):
        end = starts[ordinal + 1] if ordinal + 1 < len(starts) else len(blocks)
        title_end = start + 1
        while (
            title_end < end
            and title_end in titles
            and blocks[title_end].document == blocks[start].document
        ):
            title_end += 1
        for i in range(title_end, end):
            if matches(blocks[i], profile["stop"]):
                end = i
                break
        core = blocks[start:end]
        ingredient_at = [
            i for i, b in enumerate(core) if role(b, profile) == "ingredient"
        ]
        method_at = [
            i
            for i, b in enumerate(core)
            if role(b, profile) == "instruction"
            and (profile.get("prose_recipe") or ingredient_at and i > ingredient_at[0])
        ]
        title = " ".join(b.text for b in blocks[start:title_end])
        if (
            not ingredient_at
            and not profile.get("prose_recipe")
            or not method_at
            or len(core) > 500
            or sum(len(b.text) for b in core) > 150000
        ):
            rejected.append(
                {
                    "heading_node": blocks[start].node,
                    "reason": "No bounded paired ingredient/method evidence, or oversized window",
                }
            )
            continue
        if profile.get("prose_recipe") and not any(
            re.search(
                r"\b(?:cook|roast|heat|mix|pour|bake|add|cut|combine|sauté|saute|poach|boil|fry|simmer|stir|whisk|chop|season|marinate)\w*\b",
                b.text,
                re.IGNORECASE,
            )
            for b in core
        ):
            rejected.append(
                {
                    "heading_node": blocks[start].node,
                    "reason": "Prose heading lacks preparation-action evidence",
                }
            )
            continue
        # End at the last recognized instruction/ingredient plus authored notes,
        # not the next chapter's unrelated narrative. Existing ranges are retained.
        last = max(ingredient_at + method_at)
        end = start + last + 1
        # Trailing local variations, serving notes and continuation paragraphs are
        # part of a recipe even when their style is not the primary method style.
        # Keep the rest of that source document up to an authored stop/title.
        while (
            profile.get("retain_trailing_document", True)
            and end < len(blocks)
            and end < start + len(core)
            and end
            < (starts[ordinal + 1] if ordinal + 1 < len(starts) else len(blocks))
            and blocks[end].document == blocks[end - 1].document
        ):
            end += 1
        core = blocks[start:end]
        sid = span(db, edition, core)
        heading = span(db, edition, blocks[start:title_end])
        entity = {
            **base(edition, blocks[start].node, "recipe", [sid]),
            "title": value(title, [heading]),
            "content_span_ids": [sid],
            "yield_value": unknown(),
            "main_text_state": "unchecked",
            "parsed_fields_state": "unparsed",
            "supporting_work_state": "unchecked",
        }
        put(db, entity)
        found.append((entity, core))
    return found, rejected


def selected_blocks(db, recipe, blocks):
    selected = []
    by_document = defaultdict(list)
    for b in blocks:
        by_document[b.document].append(b)
    for sid in recipe["content_span_ids"]:
        for part in payload(
            db.execute("select payload from spans where id=?", (sid,)).fetchone()
        )["parts"]:
            lo, hi = bounds(db, part)
            selected.extend(
                b
                for b in by_document[part["document_id"]]
                if (b.start, 0) >= lo and (b.end + 1, 0) <= hi
            )
    # A retained/manual discontiguous selection can contain the same block twice.
    return list({b.node: b for b in selected}.values())


def ingredient_fields(text, sid):
    """Only unambiguous simple leading quantities; complex amounts remain unparsed."""
    match = NUMBER.match(text)
    if not match:
        return (
            unknown("Ingredient name is not separable from the authored line"),
            unknown("Quantity requires source interpretation"),
            unknown(),
        )
    number, rest = match.groups()
    for glyph, fraction in FRACTIONS.items():
        number = number.replace(glyph, " " + fraction)
    try:
        amount = sum((Fraction(x) for x in number.split()), Fraction(0))
    except (ValueError, ZeroDivisionError):
        return unknown(), unknown(), unknown()
    words = rest.split(maxsplit=1)
    unit = None
    if words[0].lower().rstrip(".") in UNITS:
        unit = words[0]
        rest = words[1] if len(words) == 2 else ""
    # Equivalences, ranges, products and divided allocations are not a simple
    # scalar. Never silently discard a parenthesized alternate amount.
    if (
        not rest
        or re.match(r"[\d¼½¾⅓⅔⅛⅜⅝⅞(/|×–-]|(?:plus|to|or)\b", rest, re.IGNORECASE)
        or re.search(r"\([^)]*\d", rest)
    ):
        return (
            unknown("Compound quantity/name needs interpretation"),
            unknown("Compound quantity retained in source; not normalized"),
            unknown(),
        )
    name, comma, prep = rest.partition(",")
    quantity = {
        "kind": "measured",
        "amount": {"numerator": amount.numerator, "denominator": amount.denominator},
        "unit": unit,
        "qualifiers": [],
        "basis": None,
    }
    return (
        value(name.strip(), [sid]),
        value(quantity, [sid]),
        value(prep.strip(), [sid])
        if comma and prep.strip()
        else unknown("No preparation separated by this parser"),
    )


def annotate_recipe(db, recipe, blocks, profile):
    edition, recipe_id = recipe["edition_id"], recipe["id"]
    original_children = [
        payload(r)
        for r in db.execute(
            "select payload from entities where edition_id=? and json_extract(payload,'$.recipe_id')=?",
            (edition, recipe_id),
        )
    ]
    if recipe["yield_value"]["state"] == "unparsed":
        yields = [
            b
            for b in blocks
            if role(b, profile) == "yield"
            or any(
                c.lower()
                in {"yield", "yld", "ry", "ry1", "ry2", "rec_serve", "os_serves"}
                or "yield" in c.lower()
                for c in b.classes
            )
        ]
        if yields:
            yield_spans = [span(db, edition, [b]) for b in yields]
            recipe["yield_value"] = value(
                {"kind": "qualitative", "wording": " ".join(b.text for b in yields)},
                yield_spans,
            )
    # Manually supported recipes already have detailed examples. Add only uncovered
    # occurrences; do not replace supported parsed quantities or selected scope.
    existing_spans = defaultdict(set)
    for child in original_children:
        for sid in child.get("source_span_ids", child.get("content_span_ids", [])):
            for part in payload(
                db.execute("select payload from spans where id=?", (sid,)).fetchone()
            )["parts"]:
                lo, hi = bounds(db, part)
                existing_spans[child["kind"]].add((part["document_id"], lo[0], hi[0]))
    seen_ingredient = False
    current_part = None
    current_part_kind = None
    groups = []
    children = []
    ingredient_ordinal = instruction_ordinal = 0
    seen_instruction = False
    for i, block in enumerate(blocks):
        part_kind = next(
            (
                kind
                for kind, selectors in profile.get("part", {}).items()
                if matches(block, selectors)
            ),
            None,
        )
        part_kind = profile.get("part_labels", {}).get(block.text.casefold(), part_kind)
        if role(block, profile) == "equipment":
            part_kind = "equipment"
        if part_kind and block.text.upper() in {
            "METHOD",
            "STEPS",
            "PROCEDURE",
            "INSTRUCTIONS",
        }:
            part_kind = "method_group"
        # Some publishers use the ingredient line style for 'For the sauce'.
        if (
            (
                role(block, profile) == "ingredient"
                or profile.get("inline_ingredient_groups")
            )
            and re.match(
                r"^(?:for (?:the )?|to (?:serve|finish|complete)\b)",
                block.text,
                re.IGNORECASE,
            )
            and len(block.text) < 100
        ):
            part_kind = "ingredient_group"
        if part_kind:
            if part_kind == "ingredient_group" and role(block, profile) == "ingredient":
                seen_ingredient = True
            sid = span(db, edition, [block])
            current_part = key(recipe_id, block.node, "part", VERSION)
            current_part_kind = part_kind
            end = next(
                (
                    j
                    for j in range(i + 1, len(blocks))
                    if any(
                        matches(blocks[j], selectors)
                        for selectors in profile.get("part", {}).values()
                    )
                    or blocks[j].text.casefold() in profile.get("part_labels", {})
                    or part_kind == "ingredient_group"
                    and role(blocks[j], profile) == "instruction"
                ),
                len(blocks),
            )
            if role(block, profile) == "equipment":
                end = i + 1
            content = span(db, edition, blocks[i:end])
            group = {
                **base(edition, current_part, "recipe_part", [content]),
                "id": current_part,
                "recipe_id": recipe_id,
                "parent_part_id": None,
                "part_kind": part_kind,
                "label": (
                    unknown(
                        "Authored ingredient paragraph has no separate group heading",
                        evidence=[sid],
                    )
                    if "fragment-ingredient-list" in block.classes
                    else value(block.text, [sid])
                ),
                "ordinal": len(groups),
                "content_span_ids": [content],
            }
            if not any(
                a <= block.start < z and doc == block.document
                for doc, a, z in existing_spans["recipe_part"]
            ):
                put(db, group)
                groups.append(group)
            else:
                current_part = None
            continue
        ingredient = (
            role(block, profile) == "ingredient" and current_part_kind != "equipment"
        )
        instruction = role(block, profile) == "instruction" and (
            seen_ingredient or profile.get("prose_recipe")
        )
        if profile.get("instruction_part_kinds") and not any(
            block.text.casefold().startswith(p.casefold())
            for p in profile.get("role_prefixes", {}).get("instruction", [])
        ):
            instruction = (
                instruction and current_part_kind in profile["instruction_part_kinds"]
            )
        instruction = (
            instruction
            or seen_instruction
            and matches(block, profile.get("instruction_continuation", []))
        )
        # Ingredients in table rows remain whole authored rows. A name-cell-only
        # profile does not discard the adjacent quantity cells.
        if ingredient:
            seen_ingredient = True
            kind, ordinal = "recipe_ingredient", ingredient_ordinal
            ingredient_ordinal += 1
        elif instruction:
            seen_instruction = True
            if current_part_kind in {"ingredient_group", "equipment"}:
                current_part = current_part_kind = None
            kind, ordinal = "instruction", instruction_ordinal
            instruction_ordinal += 1
        else:
            continue
        if any(
            doc == block.document and a < block.end + 1 and z > block.start
            for doc, a, z in existing_spans[kind]
        ):
            continue
        sid = span(db, edition, [block])
        entity = {
            **base(edition, [recipe_id, block.node, kind], kind, [sid]),
            "recipe_id": recipe_id,
            "part_id": current_part,
            "ordinal": ordinal,
            "source_span_ids": [sid],
            "formulation_ids": [],
            "formulation_state": "unparsed",
        }
        if kind == "recipe_ingredient":
            name, amount, preparation = ingredient_fields(block.text, sid)
            entity.update(
                ingredient_name=name,
                quantity=amount,
                preparation=preparation,
                recipe_use_id=None,
            )
        put(db, entity)
        children.append((entity, block))
    if children or groups:
        recipe["parsed_fields_state"] = "partial"
        # Link recovery is a separate pass; unlinked uses and requiredness remain
        # unassessed even when links have been captured.
        db.execute(
            "update entities set payload=? where id=?",
            (SEMANTIC.validate_python(recipe).model_dump_json(), recipe_id),
        )
    return children


def authored_uses(db, edition, recipes, children):
    ranges = defaultdict(list)
    for recipe, blocks in recipes:
        for block in blocks:
            ranges[block.document].append((block.start, block.end, recipe["id"]))
    range_starts = {doc: [r[0] for r in sorted(items)] for doc, items in ranges.items()}
    ranges = {doc: sorted(items) for doc, items in ranges.items()}
    all_links = db.execute(
        "select l.*,n.preorder from links l join nodes n on n.id=l.node_id where l.edition_id=? and json_extract(l.payload,'$.relation') in ('hyperlink','note_link') order by l.document_id,n.preorder",
        (edition,),
    ).fetchall()
    by_document = defaultdict(list)
    for link in all_links:
        by_document[link["document_id"]].append(link)
    generated = 0
    for child, block in children:
        recipe_id = child["recipe_id"]
        for link in by_document[block.document]:
            if not block.start <= link["preorder"] <= block.end:
                continue
            target = None
            if link["target_node"]:
                node = db.execute(
                    "select preorder from nodes where id=?", (link["target_node"],)
                ).fetchone()
                doc = link["target_document"]
                if node and doc in ranges:
                    at = bisect.bisect_right(range_starts[doc], node[0]) - 1
                    if at >= 0 and ranges[doc][at][0] <= node[0] <= ranges[doc][at][1]:
                        target = ranges[doc][at][2]
            if target == recipe_id:
                continue
            evidence = child["source_span_ids"]
            use = {
                **base(edition, [recipe_id, link["id"]], "recipe_use", evidence),
                "source_recipe_id": recipe_id,
                "target_recipe_id": target,
                "source_link_id": link["id"],
                "source_part_id": child["part_id"],
                "selected_formulation_id": None,
                "selected_part_id": None,
                "classification": unknown(
                    "Authored link does not establish requiredness",
                    "unresolved",
                    evidence,
                ),
                "amount_used": unknown("Referenced amount needs interpretation"),
                "scope": unknown(
                    "Whole, partial and variation scope need interpretation",
                    "unresolved",
                    evidence,
                ),
                "scope_wording": value(block.text, evidence),
                "modification_wording": unknown(),
            }
            # No recipe target means this is a source reference requiring review,
            # not an assertion that a preparation exists at that location.
            use["state"] = "candidate" if target else "unresolved"
            put(db, use)
            generated += 1
    return generated


def interpret(db, profiles=None, progress=print):
    config = profiles or json.loads(PROFILE_PATH.read_bytes())
    report = []
    for edition in db.execute("select * from editions order by calibre_id").fetchall():
        bid, eid = str(edition["calibre_id"]), edition["id"]
        profile = config["profiles"].get(bid)
        mismatch = bool(
            profile
            and profile.get("source_sha256")
            and profile["source_sha256"] != payload(edition)["source_sha256"]
        )
        if mismatch:
            profile = None
        rejected = []
        if profile:
            blocks = blocks_for_book(db, eid, profile)
            retained = [
                payload(r)
                for r in db.execute(
                    "select payload from entities where edition_id=? and kind='recipe' order by id",
                    (eid,),
                )
            ]
            # Never duplicate a manually bounded recipe by creating a second title
            # candidate inside its retained range. Existing candidates stay stable.
            if retained:
                recipes = [(r, selected_blocks(db, r, blocks)) for r in retained]
            else:
                recipes, rejected = proposed_recipes(db, eid, blocks, profile)
            children = []
            for recipe, selected in recipes:
                children.extend(annotate_recipe(db, recipe, selected, profile))
            authored_uses(db, eid, recipes, children)
        counts = dict(
            db.execute(
                "select kind,count(*) from entities where edition_id=? group by kind",
                (eid,),
            )
        )
        row = {
            "book_id": eid,
            "calibre_id": edition["calibre_id"],
            "source_sha256": payload(edition)["source_sha256"],
            "profile": VERSION if profile else None,
            "entity_counts": counts,
            "state": "candidate markup interpretation"
            if profile
            else "requires source interpretation",
            "unresolved_reason": "Markup profile belongs to different source bytes"
            if mismatch
            else config["special_books"].get(bid),
            "rejected_headings": rejected,
            "complete_recipe_recall": "not_assessed",
        }
        report.append(row)
        coverage = payload(
            db.execute(
                "select payload from coverage where edition_id=?", (eid,)
            ).fetchone()
        )
        coverage.update(
            semantic_state="partial" if counts else "not_assessed",
            entity_counts=counts,
            parsed_fields="Candidate ingredient/instruction occurrences; simple quantities only; complex quantities and formulation ownership remain unparsed",
            supporting_work="Authored preparation/source references captured; requiredness, scope and unlinked uses remain unresolved",
            recipe_interpretation={
                k: v
                for k, v in row.items()
                if k
                not in {
                    "book_id",
                    "source_sha256",
                    "rejected_headings",
                    "entity_counts",
                }
            },
            rejected_recipe_heading_count=len(rejected),
        )
        db.execute(
            "update coverage set payload=? where edition_id=?",
            (json.dumps(coverage), eid),
        )
        db.commit()
        progress(
            {
                "calibre_id": edition["calibre_id"],
                "entity_counts": counts,
                "rejected_headings": len(rejected),
                "state": row["state"],
            }
        )
    return {
        "version": VERSION,
        "books": report,
        "recipe_books": sum(r["entity_counts"].get("recipe", 0) > 0 for r in report),
        "limitations": [
            "Candidate structure is not reviewed completeness",
            "No independent recall claim; rejected and unprofiled books require source review",
            "No inferred dietary suitability",
            "No OCR or inference; image and page-layout content require a separate protected reading pass",
            "References do not establish requiredness or whole-preparation scope",
        ],
    }


def project_entities(db):
    """Refresh semantic projections while retaining every native source search unit."""
    db.execute("delete from search_units where kind!='source'")
    for row in db.execute("select * from entities order by id").fetchall():
        entity = payload(row)
        spans = (
            entity.get("content_span_ids")
            or entity.get("source_span_ids")
            or entity["evidence_span_ids"]
        )
        title = (
            entity.get("title")
            or entity.get("label")
            or entity.get("ingredient_name")
            or {}
        ).get("value") or ""
        text = source_text(db, spans)
        for ordinal, start in enumerate(range(0, len(text), 18000)):
            db.execute(
                "insert into search_units values(?,?,?,?,?,?,?)",
                (
                    key(row["id"], ordinal, "whole-book-search-v1"),
                    row["edition_id"],
                    row["id"],
                    row["kind"],
                    entity["state"],
                    title,
                    text[start : start + 18000],
                ),
            )
    db.commit()


def interpretation_build(build, output, progress=print):
    """Clone verified source/model artifacts into a new immutable interpretation."""
    build, output = Path(build).resolve(), Path(output).resolve()
    if output.exists():
        raise IntegrityError("interpretation build output must be new")
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
    if MODEL_PATH not in inputs:
        raise IntegrityError("interpretation requires canonical whole-book capture")
    output.mkdir(mode=0o700, parents=True)
    pub = uuid.uuid4().hex
    index_path, model_path = output / "index.sqlite", output / "whole-books.sqlite"
    shutil.copyfile(inputs["runtime/index.sqlite"], index_path)
    shutil.copyfile(inputs[MODEL_PATH], model_path)
    with sqlite3.connect(index_path) as index:
        index.execute("update info set publication_id=?", (pub,))
    profile_sha = digest_file(PROFILE_PATH)[0]
    implementation = hashlib.sha256(
        Path(__file__).read_bytes() + PROFILE_PATH.read_bytes()
    ).hexdigest()
    with sqlite3.connect(model_path) as db:
        db.row_factory = sqlite3.Row
        db.execute("pragma cache_size=-65536")
        old = payload(db.execute("select payload from model_info").fetchone())
        if old["publication_id"] != manifest.publication_id:
            raise IntegrityError("base whole-book publication mismatch")
        info = {
            **old,
            "publication_id": pub,
            "model_snapshot": {
                **old["model_snapshot"],
                "id": key(pub, implementation, "interpretation-snapshot-v1"),
                "source_publication_id": manifest.publication_id,
                "interpretation_version": VERSION,
                "interpretation_implementation_sha256": implementation,
                "markup_profiles_sha256": profile_sha,
            },
        }
        db.execute("update model_info set payload=?", (json.dumps(info),))
        for row in db.execute("select id,payload from editions").fetchall():
            meta = payload(row)
            meta["publication_id"] = pub
            db.execute(
                "update editions set payload=? where id=?",
                (json.dumps(meta), row["id"]),
            )
        audit = interpret(db, progress=progress)
        project_entities(db)
    validation = validate_model(model_path, pub, index_path)
    previous = json.loads(inputs[REPORT_PATH].read_bytes())
    report = {
        **previous,
        **info,
        "validation": validation,
        "recipe_interpretation": audit,
    }
    atomic_write(output / "whole-books.json", canonical(report))
    atomic_write(output / "recipe-interpretation.json", canonical(audit))
    atomic_write(output / "ocr-review.json", canonical(make_report(pub, [])))
    inputs.update(
        {
            "runtime/index.sqlite": index_path,
            MODEL_PATH: model_path,
            REPORT_PATH: output / "whole-books.json",
            QUALITY_PATH: output / "ocr-review.json",
        }
    )
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
