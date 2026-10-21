"""Build source-backed candidate ranges from bounded native EPUB block captures.

Private input/output only. No OCR, local model, remote inference, or image reading.
Publisher markup profiles are hypotheses about boundaries, not verified recipes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
from pathlib import Path
from urllib.parse import unquote, urlsplit

TITLE_CLASSES = {
    4: {"recipe_title"},
    5: {"section"},
    7: {"head", "head1"},
    10: {"recipes_rh"},
    13: {"recipe-title", "subrecipe-title"},
    17: {"recipe_title"},
    18: {"h3", "h3a", "h3b", "h3d", "h3f"},
    25: {"rt-supb-pg", "rt"},
    28: {"h2a3", "h3bc", "h3bc1"},
    38: {"rt-chap-pg"},
    39: {"rt-supb-pg"},
    50: {"recipetitle", "sbrecipetitle"},
    67: {"recipe_rt", "recipe_rt1a", "recipe_rt1", "recipe_srt", "srecipe_srt"},
    71: {"chapter-title", "recipe-title5", "recipe-titlea"},
    75: {"recipe_title", "recipe_title1", "recipe_title2"},
}
INGREDIENT_CLASSES = {
    4: {"il_item", "il_item1"},
    5: {"textbox"},
    7: {"list"},
    10: {"recipes_ing", "recipes_ing1"},
    13: {"ingred"},
    17: {"IL_item", "ingreident1"},
    18: {"hang", "hangb"},
    25: {"ril", "rilf", "rill"},
    28: {"noindenta"},
    38: {"ril", "rilf"},
    39: {"ril", "rilf"},
    50: {"list"},
    67: {"recipe_i", "recipe_i-spc", "srecipe_i"},
    71: {"ingredient"},
    75: {"ingredients1", "ingredients"},
}
METHOD_CLASSES = {
    4: {"method_nonindent", "method_indent"},
    5: {"extract", "extract1"},
    7: {"step"},
    10: {"recipes_sidetxfl", "recipes_recipe-tx"},
    13: {"step"},
    17: {"method_step", "method_step1", "process"},
    18: {"noindenta", "indent", "noindentf"},
    25: {"rpf", "rp", "rpl"},
    28: {"indent", "noindentt1", "noindentt3"},
    38: {"rpf", "rp"},
    39: {"rpf", "rp"},
    50: {"step", "step_top", "stepfirst"},
    67: {
        "recipe_rsteps",
        "recipe_rsteps1",
        "srecipe_rsteps",
        "srecipe_rsteps1",
        "noindentt",
    },
    71: {"step"},
    75: {"instruction1"},
}
STOP_CLASSES = {
    4: {"headerfm", "headerfm1", "headerfm3", "headera", "headera_box", "section"},
    5: {"chapter"},
    7: {"plant", "head2", "indexa", "index_alpha"},
    10: {"h", "h1", "h2", "chapter-number", "chapter-title", "h2a", "h3", "h2-v"},
    13: {"hidden", "fm-section-title", "fm-section-title1", "toc-hed"},
    17: {"chapter_number", "chapter_title", "glossary", "fmtitle", "contents"},
    18: {"h2c", "h2b", "h2b1", "h2f"},
    25: {"h3-supb-pg", "h3aft", "h1-supb-pg", "h1", "bmh1", "indexdiv", "bmt-glo-pg"},
    28: {"h2a", "h2a1", "h2a2", "h2aa", "h1a", "h1c", "h2a2a", "h3b", "h3r"},
    38: {"aph1", "bmh1", "Contents-Head", "apt-app-pg", "apst"},
    39: {"h1-supb-pg", "h1", "apt-app-pg", "bmh1", "bmh2", "bmt-idx-pg"},
    50: {
        "chaptitle",
        "chaptitle_fb",
        "mattertitle",
        "mattertitle_y",
        "index",
        "about_the_author",
        "how-to",
    },
    67: {"a-head", "b-head", "c-head", "d-head", "sidebar_st", "ind-head", "e-head"},
    71: {"part-title", "part-number", "sect1", "sect2", "preface-title"},
    75: {"chapter", "chapter6", "section", "section1", "section0", "foreword", "toc"},
}
PROFILE_VERSION = "native-epub-catalog-profile-v2"
TRAILING_NOTE_CLASSES = {
    "recipe_yield",
    "ry",
    "yield",
    "yield_1",
    "yield_l",
    "serving_size",
    "recipe_n-copy",
    "recipe_n-2-copy",
    "recipenotetext",
    "notehed",
    "rpn",
    "noindent1",
    "nonindent4",
    "notes",
    "note-n",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]


def is_title(bid, block):
    if block.get("class") not in TITLE_CLASSES[bid]:
        return False
    if bid == 5:
        return block["tag"] in {"h3", "h4"}
    return True


def profile_book(book):
    bid = book["calibre_id"]
    assert Path(book["path"]).suffix == ".epub", "Only native EPUB captures admitted"
    docs = book["documents"]
    flat = [(di, q) for di, doc in enumerate(docs) for q in doc["blocks"]]
    titles = [i for i, (_, q) in enumerate(flat) if is_title(bid, q)]
    # A title may be authored over adjacent paragraphs. Retain the entire title.
    starts = [
        i
        for i in titles
        if i == 0 or not (i - 1 in titles and flat[i - 1][0] == flat[i][0])
    ]
    candidates, rejected = [], []
    for ni, start in enumerate(starts):
        end = starts[ni + 1] if ni + 1 < len(starts) else len(flat)
        title_end = start + 1
        while (
            title_end < end
            and title_end in titles
            and flat[title_end][0] == flat[start][0]
        ):
            title_end += 1
        for i in range(title_end, end):
            _, q = flat[i]
            # Every authored section boundary limits the window, including prose
            # headings that do not qualify as a recipe title for this publisher.
            if q.get("class") in STOP_CLASSES[bid] or (bid == 5 and q["tag"] == "h2"):
                end = i
                break
        # Do not absorb unrelated essays, a following photo's caption, or back
        # matter just because the next recipe title is several documents away.
        recipe_content = INGREDIENT_CLASSES[bid] | METHOD_CLASSES[bid]
        last = next(
            (
                i
                for i in range(end - 1, title_end - 1, -1)
                if flat[i][1].get("class") in recipe_content
            ),
            None,
        )
        if last is not None:
            boundary = flat[last][1]["xpath"]
            clipped = last + 1
            while clipped < end:
                di, q = flat[clipped]
                if di != flat[last][0] or not (
                    q["xpath"].startswith(boundary + "/")
                    or q.get("class") in TRAILING_NOTE_CLASSES
                    or q["tag"] in {"td", "th"}
                ):
                    break
                clipped += 1
            end = clipped
        core = flat[start:end]
        ingredient_blocks = [
            q for _, q in core if q.get("class") in INGREDIENT_CLASSES[bid]
        ]
        method_blocks = [q for _, q in core if q.get("class") in METHOD_CLASSES[bid]]
        title = " ".join(q["text"] for _, q in flat[start:title_end])
        if not ingredient_blocks or not method_blocks:
            rejected.append(
                {
                    "book": bid,
                    "title": title,
                    "document": docs[flat[start][0]]["path"],
                    "reason": "No paired ingredient and method markup in bounded window",
                }
            )
            continue
        lo, hi = flat[start][0], flat[end - 1][0]
        # Keep image-only/empty continuation documents between text documents.
        if end < len(flat) and flat[end][1]["i"] == 0:
            hi = max(hi, flat[end][0] - 1)
        parts = []
        for di in range(lo, hi + 1):
            qs = [q for d, q in core if d == di]
            parts.append(
                {
                    "document": docs[di]["path"],
                    "start_xpath": qs[0]["xpath"] if di == lo else None,
                    "end_xpath": qs[-1]["xpath"] if di == hi and qs else None,
                    "whole_document": not qs,
                }
            )
        identity = [book["sha256"], parts, PROFILE_VERSION]
        candidates.append(
            {
                "id": digest(identity),
                "book": bid,
                "book_id": book["id"],
                "book_title": book["title"],
                "source_id": book["source_id"],
                "source_sha256": book["sha256"],
                "title": title,
                "document": parts[0]["document"],
                "start_xpath": parts[0]["start_xpath"],
                "end_xpath": parts[-1]["end_xpath"],
                "parts": parts,
                "text": "\n".join(q["text"] for _, q in core),
                "blocks": [{**q, "document": docs[d]["path"]} for d, q in core],
                "references": [],
                "profile_version": PROFILE_VERSION,
                "evidence": {
                    "ingredient_markup_blocks": len(ingredient_blocks),
                    "method_markup_blocks": len(method_blocks),
                },
                "status": "candidate boundaries; supporting work and image text unchecked",
            }
        )
    return candidates, rejected


def references(candidates, books):
    # Locate authored links without turning them into assumed required work.
    bydoc = {}
    for candidate in candidates:
        for part in candidate.get("parts", [{"document": candidate["document"]}]):
            bydoc.setdefault((candidate["book"], part["document"]), []).append(
                candidate
            )
    for candidate in candidates:
        if candidate.get("profile_version") != PROFILE_VERSION:
            continue
        book = books[candidate["book"]]
        docs = {d["path"]: d for d in book["documents"]}
        for q in candidate["blocks"]:
            role = (
                "ingredient"
                if q.get("class") in INGREDIENT_CLASSES[candidate["book"]]
                else "method"
                if q.get("class") in METHOD_CLASSES[candidate["book"]]
                else "context_or_variation"
            )
            for link in q["links"]:
                uri = urlsplit(link["href"])
                docpath = (
                    posixpath.normpath(
                        posixpath.join(
                            posixpath.dirname(q["document"]), unquote(uri.path)
                        )
                    )
                    if uri.path
                    else q["document"]
                )
                anchor = unquote(uri.fragment)
                ref = {
                    "label": link["label"],
                    "href": link["href"],
                    "source_role": role,
                    "source_text": q["text"],
                    "source_document": q["document"],
                    "target_document": docpath,
                    "target_anchor": anchor,
                }
                if uri.scheme or uri.netloc:
                    ref["resolution"] = "external_link_not_fetched"
                elif docpath not in docs:
                    ref["resolution"] = "unresolved_document"
                else:
                    doc = docs[docpath]
                    target = doc.get("anchors", {}).get(
                        anchor, 0 if not anchor else None
                    )
                    matches = (
                        [
                            r
                            for r in bydoc.get((candidate["book"], docpath), [])
                            if any(
                                z["i"] == target
                                and z.get("document", r["document"]) == docpath
                                for z in r["blocks"]
                            )
                        ]
                        if target is not None
                        else []
                    )
                    if matches:
                        chosen = matches[0]
                        ref.update(
                            resolution="same_recipe"
                            if chosen["id"] == candidate["id"]
                            else "bounded_recipe",
                            target_recipe_id=chosen["id"],
                            target_title=chosen["title"],
                        )
                        if chosen["id"] != candidate["id"]:
                            ref["target_text"] = chosen["text"]
                    else:
                        ref["resolution"] = (
                            "source_target_requires_review"
                            if target is not None
                            else "unresolved_anchor"
                        )
                candidate["references"].append(ref)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=Path, required=True)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = json.loads(args.blocks.read_text())
    books = {b["calibre_id"]: b for b in data["books"]}
    candidates = json.loads(args.prior.read_text())
    old_ids = {r["book"] for r in candidates}
    rejected, counts = [], []
    for bid, book in books.items():
        if bid not in old_ids:
            found, excluded = profile_book(book)
            assert found, f"No recipe candidates for selected book {bid}"
            candidates.extend(found)
            rejected.extend(excluded)
        rows = [r for r in candidates if r["book"] == bid]
        counts.append(
            {
                "book": bid,
                "title": book["title"],
                "candidate_count": len(rows),
                "source_sha256": book["sha256"],
                "profile_state": "candidate, not independent accuracy evaluation",
            }
        )
    references(candidates, books)
    assert len({r["id"] for r in candidates}) == len(candidates)
    (args.output / "recipe-candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2)
    )
    (args.output / "rejected-headings.json").write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2)
    )
    report = {
        "recipe_books": len(counts),
        "candidate_count": len(candidates),
        "books": counts,
        "source_publication_id": data["publication_id"],
        "limitations": [
            "Publisher profiles require review; no held-out accuracy or recall claim.",
            "Ingredient/method markup is evidence, not completeness approval.",
            "Subrecipes/variations can remain inside a parent or be separately authored preparations.",
            "Unlinked supporting work and image text remain unchecked.",
        ],
        "execution": "Native EPUB markup only; no OCR/inference/network",
    }
    (args.output / "catalog-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "recipe_books": len(counts),
                "candidate_count": len(candidates),
                "counts": {b["book"]: b["candidate_count"] for b in counts},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
