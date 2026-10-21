"""Score frozen private scan references inside the resource-isolated launcher.

Manual source boundaries are an oracle control, not an automatic recipe parser.
This does not approve transcription or change a publication.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata


def normalized(text):
    text = re.sub(
        r"[¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]",
        lambda m: " " + unicodedata.normalize("NFKC", m[0]),
        text,
    )
    text = unicodedata.normalize("NFKC", text).replace("⁄", "/")
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "–": "-", "—": "-"}))
    return " ".join(text.lower().split())


def present(text, reference):
    candidate = normalized(text)
    expected = normalized(reference)
    for match in re.finditer(
        r"(?<![\w/])" + re.escape(expected) + r"(?![\w/])", candidate
    ):
        # A half must not match the fractional tail of one-and-a-half.
        if re.match(r"\d+/\d+\b", expected) and re.search(
            r"(?:^|\s)\d+\s+$", candidate[: match.start()]
        ):
            continue
        return True
    return False


def index(rows):
    db = sqlite3.connect(":memory:")
    db.execute(
        "create virtual table search using fts5(id UNINDEXED,title,text, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    db.executemany(
        "insert into search values (?,?,?)",
        [(row["id"], row.get("title", ""), row["text"]) for row in rows],
    )
    return db


def hits(db, query):
    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    if not terms:
        return []
    expression = " AND ".join('"' + term + '"' for term in terms)
    return [
        row[0]
        for row in db.execute(
            "select id from search where search match ? order by bm25(search),id limit 10",
            (expression,),
        )
    ]


def cell_text(words, width, height, box):
    left, top, right, bottom = box
    selected = [
        word
        for word in words
        if left <= (word["left"] + word["width"] / 2) / width < right
        and top <= (word["top"] + word["height"] / 2) / height < bottom
    ]
    # Frozen table cells are single-line values; glyph tops vary by character.
    selected.sort(key=lambda w: (w["left"], w["top"]))
    return " ".join(word["text"] for word in selected)


def check_scorer():
    # These check benchmark failure modes, not OCR enforcement.
    assert present("½ teaspoon", "1/2 teaspoon")
    assert not present("11/2 teaspoon", "1/2 teaspoon")
    assert not present("1½ teaspoon", "1/2 teaspoon")
    assert present("Serves 4\n4 lamb's tongues", "4 lamb's tongues")
    db = index(
        [
            {"id": "a", "text": "lemon"},
            {"id": "b", "text": "paprika"},
            {"id": "joined", "text": "lemon paprika"},
        ]
    )
    assert hits(db, "lemon paprika") == ["joined"]
    db.close()
    assert (
        cell_text(
            [
                {"left": 10, "top": 10, "width": 10, "height": 10, "text": "2"},
                {"left": 60, "top": 10, "width": 10, "height": 10, "text": "9"},
            ],
            100,
            100,
            [0, 0, 0.5, 0.5],
        )
        == "2"
    )


def compare(reference_path, candidates_path, output, exclusions_path=None):
    from cookbook.ocr_limits import require_ocr_limits

    require_ocr_limits()
    check_scorer()
    reference_bytes = reference_path.read_bytes()
    ref = json.loads(reference_bytes)
    reference_hash = hashlib.sha256(reference_bytes).hexdigest()
    exclusions = {}
    if exclusions_path is not None:
        amendment = json.loads(exclusions_path.read_text())
        if amendment["reference_sha256"] != reference_hash:
            raise ValueError("Exclusion amendment has a different reference identity")
        exclusions = amendment["excluded_queries"]
        if not set(exclusions).issubset(q["id"] for q in ref["queries"]):
            raise ValueError("Exclusion amendment names an unknown query")
    candidates = {}
    for path in sorted(candidates_path.glob("*/candidate.json")):
        candidate = json.loads(path.read_text())
        if candidate["page"] in candidates:
            raise ValueError("Duplicate page candidate")
        candidates[candidate["page"]] = candidate
    sources = {
        f"{source['book_id']}-{source['physical_page']}": source
        for source in ref["sources"]
    }
    if set(candidates) != set(sources):
        raise ValueError("Candidate/reference page coverage differs")
    for page, candidate in candidates.items():
        if candidate["source"] != sources[page]:
            raise ValueError("Candidate source identity differs")
    units = ref["units"]
    membership = defaultdict(list)
    reference_pages = defaultdict(list)
    for unit in units:
        for page in dict.fromkeys(part["page"] for part in unit["parts"]):
            membership[page].append(unit["id"])
        for part in unit["parts"]:
            reference_pages[part["page"]].append(part["text"])
    for page, text in ref["distractors"].items():
        reference_pages[page].append(text)
    if set(reference_pages) != set(sources):
        raise ValueError("Reference pages incomplete")

    def page_rows(field):
        return [
            {
                "id": page,
                "title": f"Page {sources[page]['physical_page']}",
                "text": "\n".join(reference_pages[page])
                if field == "reference"
                else candidates[page][field],
                "units": membership[page],
                "pages": [page],
            }
            for page in sorted(sources)
        ]

    def assembled(rows):
        page_map = {row["id"]: row for row in rows}
        result = []
        for unit in units:
            pages = list(dict.fromkeys(part["page"] for part in unit["parts"]))
            # No corrected reference title is injected into candidate indexes.
            result.append(
                {
                    "id": unit["id"],
                    "text": "\n".join(page_map[p]["text"] for p in pages),
                    "units": [unit["id"]],
                    "pages": pages,
                }
            )
        result.extend(row for row in rows if not row["units"])
        return result

    arms = {}
    for prefix, field in (
        ("production", "production_text"),
        ("direct_ocr", "direct_text"),
        ("reference", "reference"),
    ):
        arms[prefix + "_pages"] = page_rows(field)
        arms[prefix + "_recipes"] = assembled(arms[prefix + "_pages"])
    # Naive overlapping windows demonstrate cooccurrence across unrelated recipes.
    direct = arms["direct_ocr_pages"]
    window_rows = list(direct)
    for first, second in zip(direct, direct[1:]):
        a, b = sources[first["id"]], sources[second["id"]]
        if (
            a["book_id"] == b["book_id"]
            and b["physical_page"] == a["physical_page"] + 1
        ):
            window_rows.append(
                {
                    "id": first["id"] + "+" + second["id"],
                    "text": first["text"] + "\n" + second["text"],
                    "units": list(dict.fromkeys(first["units"] + second["units"])),
                    "pages": first["pages"] + second["pages"],
                }
            )
    arms["direct_ocr_adjacent_windows"] = window_rows
    results = {}
    for name, rows in arms.items():
        db = index(rows)
        rowmap = {row["id"]: row for row in rows}
        details = []
        for query in ref["queries"]:
            found = hits(db, query["query"])
            found_units = list(
                dict.fromkeys(unit for row in found for unit in rowmap[row]["units"])
            )
            relevant = set(query["relevant"])
            rank = next(
                (i + 1 for i, target in enumerate(found_units) if target in relevant),
                None,
            )
            details.append(
                {
                    **query,
                    "rows": found,
                    "found_units": found_units,
                    "hit": bool(relevant.intersection(found_units)),
                    "reciprocal_rank": 1 / rank if rank else 0,
                    "excluded_reason": exclusions.get(query["id"]),
                }
            )
        positive = [q for q in details if q["relevant"] and not q["excluded_reason"]]
        negative = [
            q for q in details if not q["relevant"] and not q["excluded_reason"]
        ]
        groups = {}
        for field in ("category", "split"):
            for value in sorted({q.get(field, "none") for q in positive}):
                selected = [q for q in positive if q.get(field, "none") == value]
                groups[f"{field}:{value}"] = {
                    "hits": sum(q["hit"] for q in selected),
                    "total": len(selected),
                }
        results[name] = {
            "rows": len(rows),
            "hits": sum(q["hit"] for q in positive),
            "total": len(positive),
            "recall_at_10": sum(q["hit"] for q in positive) / len(positive),
            "mean_reciprocal_rank": sum(q["reciprocal_rank"] for q in positive)
            / len(positive),
            "negative_controls_with_any_hit": sum(bool(q["rows"]) for q in negative),
            "negative_controls_with_recipe_hit": sum(
                bool(q["found_units"]) for q in negative
            ),
            "negative_total": len(negative),
            "groups": groups,
            "queries": details,
        }
        db.close()
    # Check reference query grounding and uniqueness before trusting scores.
    if results["reference_recipes"]["hits"] != results["reference_recipes"]["total"]:
        raise ValueError("A positive query is not grounded in its reference recipe")
    if results["reference_recipes"]["negative_controls_with_recipe_hit"]:
        raise ValueError("A negative query matches a reference recipe")
    if len({q["id"] for q in ref["queries"]}) != len(ref["queries"]):
        raise ValueError("Duplicate query identity")

    reading = {}
    for field in ("production_text", "direct_text"):
        details = []
        for unit in units:
            for number, part in enumerate(unit["parts"]):
                if part["kind"] not in ("ingredient", "instruction", "table_row"):
                    continue
                candidate = candidates[part["page"]][field]
                details.append(
                    {
                        "unit": unit["id"],
                        "part": number,
                        "page": part["page"],
                        "kind": part["kind"],
                        "reference": part["text"],
                        "exact_phrase": present(candidate, part["text"]),
                        "instruction_anchor": present(candidate, part["anchor"])
                        if part.get("anchor")
                        else None,
                    }
                )
        summary = {}
        for kind in ("ingredient", "instruction", "table_row"):
            selected = [p for p in details if p["kind"] == kind]
            summary[kind] = {
                "exact_phrase": sum(p["exact_phrase"] for p in selected),
                "total": len(selected),
            }
            if kind == "instruction":
                summary[kind]["anchors"] = sum(
                    p["instruction_anchor"] for p in selected
                )
        fraction_parts = [
            p
            for p in details
            if p["kind"] == "ingredient" and re.search(r"\d+/\d+", p["reference"])
        ]
        summary["fraction_ingredient"] = {
            "exact_phrase": sum(p["exact_phrase"] for p in fraction_parts),
            "total": len(fraction_parts),
        }
        reading[field] = {"summary": summary, "details": details}
    geometry = ref["table_geometry"]
    page = candidates[geometry["page"]]
    width, height = page["image_size"]
    xs, ys = geometry["column_boundaries"], geometry["row_boundaries"]
    cells = []
    for unit in units:
        for row in unit["parts"]:
            if row["kind"] != "table_row":
                continue
            i = row["row"]
            for j, value in enumerate(row["cells"]):
                # Column zero is the ingredient label; values start at one.
                text = cell_text(
                    page["direct_words"],
                    width,
                    height,
                    [xs[j + 1], ys[i], xs[j + 2], ys[i + 1]],
                )
                cells.append(
                    {
                        "ingredient": row["label"],
                        "formulation": [2, 6, 20, 75][j],
                        "reference": value,
                        "candidate": text,
                        "exact": normalized(text) == normalized(value),
                    }
                )
    citation_count = sum(
        len(set(part["page"] for part in unit["parts"])) for unit in units
    )
    report = {
        "reference_sha256": reference_hash,
        "excluded_queries": exclusions,
        "scope": ref["scope"],
        "recipe_count": len(units),
        "page_count": len(sources),
        "search": results,
        "reading": reading,
        "table_cells": {
            "correct": sum(cell["exact"] for cell in cells),
            "total": len(cells),
            "manual_layout": True,
            "details": cells,
        },
        "source_identity_checks": {
            "pages": len(sources),
            "recipe_page_links": citation_count,
            "all_verified": True,
        },
        "caveats": [
            "Purposive small sample, not whole-library recall or direct EPUB parity.",
            "Manual recipe and cell boundaries; no automatic assembly accuracy claim.",
            "Short instruction anchors do not prove complete instructions.",
            "Exact phrase failures include punctuation/line-order differences as well as recognition errors.",
            "Reference transcriptions are unapproved research controls.",
            "All-text search retains menu/prose blocks; recipe-negative source matches are reported separately.",
        ],
    }
    output.mkdir(exist_ok=True)
    (output / "results.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    for name, rows in arms.items():
        (output / (name + ".json")).write_text(
            json.dumps(rows, indent=2, ensure_ascii=False)
        )
    print(
        json.dumps(
            {
                "recipes": len(units),
                "pages": len(sources),
                "retrieval": {
                    name: {
                        k: value[k]
                        for k in ("hits", "total", "negative_controls_with_recipe_hit")
                    }
                    for name, value in results.items()
                },
                "reading": {
                    field: value["summary"] for field, value in reading.items()
                },
                "table_cells": {
                    "correct": report["table_cells"]["correct"],
                    "total": len(cells),
                },
            }
        )
    )


def main():
    from cookbook.ocr_limits import require_ocr_limits

    require_ocr_limits()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("/output"))
    parser.add_argument("--exclusions", type=Path)
    args = parser.parse_args()
    compare(args.reference, args.candidates, args.output, args.exclusions)


if __name__ == "__main__":
    main()
