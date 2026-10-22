"""Turn voted page transcriptions into a benchmark candidate (the eight files in BOOK-BRIEF.md).

Stage 1 (model calls, resumable): for every page, the same reader labels the page's numbered
lines with the section they belong to, the part kind, the printed folio and authored
cross-references. The model never retypes text; every part's text is copied from the voted
page transcription by line range, so sectioning cannot paraphrase or invent wording.

Stage 2 (code only): join labelled blocks into sections across pages (continuations by title),
then write sections.jsonl, page-ledger.jsonl, quantity-review.jsonl (one row per guarded crop
actually read), corrections.jsonl (voting changes), unresolved.jsonl (tied votes, failed
labels), progress.json, report.md, freeze.json.

This is assembler v4 (2026-10-20): quantity-review rows list a line as reviewed only when the
voted crop reading stands in the text; ties and rejected corrections go to unresolved.jsonl.
Called by `bench.py assemble`.
"""

import concurrent.futures as cf
import difflib
import hashlib
import json
import re
import sys
import unicodedata

import pipeline as fp
import readers as rd

EXP = fp.EXP
ASSEMBLER = "v4"
SECTION_KINDS = {
    "chapter",
    "recipe",
    "passage",
    "technique",
    "reference_entry",
    "contents",
    "index",
    "frontmatter",
}
PROMPT = """Below is the transcription of one page of a cookbook, with numbered lines. Lines from the
previous and next page are shown only as context, so you can tell when something continues across
pages. Do not label context lines.

Assign every numbered line to the authored section it belongs to. Reply with JSON only:
{"printed_page": "folio exactly as printed, or null",
 "page_kinds": ["recipe" | "chapter_opener" | "photograph" | "passage" | "menu" | "timeline" | "index" | "contents" | "frontmatter" | "reference"],
 "blocks": [{"from": 1, "to": 4, "section_title": "...", "section_kind": "...", "continues_previous_page": false, "part": "..."}],
 "references": [{"line": 7, "label": "the exact referring words", "printed_target": "42 or null"}]}

Rules:
- blocks cover every numbered line exactly once, in order; from/to are inclusive line numbers.
- section_title is the authored title of the recipe, chapter or passage the block belongs to, copied
  exactly as printed, never a subheading such as INGREDIENTS or METHOD. Components with their own
  heading inside a recipe (for example a stock or sauce made for that dish) belong to the dish.
  Use null only when no title applies.
- continues_previous_page is true when the block continues a section that started on an earlier page;
  then give that section's title as best the context shows.
- section_kind is one of: recipe, chapter, passage, technique, reference_entry, contents, index, frontmatter.
- part is one of: title, headnote, ingredients, instructions, table, note, variation, assembly,
  heading, text, menu, timeline, index_entries, contents, caption, footer (running heads and folios).
- references lists only authored cross-references in this page's numbered lines (e.g. "see page 42",
  "(see above)", "see Basic recipes"); printed_target is the referenced folio if printed, else null.
- A page with no numbered lines gets "blocks": [].

PREVIOUS PAGE (context, last lines):
{prev}

THIS PAGE (label these):
{this}

NEXT PAGE (context, first lines):
{next}
"""


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").casefold()
    return re.sub(
        r"[^a-z0-9]+", " ", "".join(c for c in s if not unicodedata.combining(c))
    ).strip()


def slug(s):
    return norm(s).replace(" ", "-")[:60]


def lines_of(rec):
    if rd.has_refusal(rec):
        return []
    return [l for l in (rec.get("final_text") or "").splitlines() if l.strip()]


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    i, j = text.find("{"), text.rfind("}")
    return json.loads(text[i : j + 1])


def check(label, n):
    want = 1
    for b in label["blocks"]:
        if int(b["from"]) != want or int(b["to"]) < int(b["from"]) or int(b["to"]) > n:
            raise ValueError(
                f"block {b.get('from')}-{b.get('to')} expected start {want}"
            )
        want = int(b["to"]) + 1
    if want != n + 1:
        raise ValueError(f"blocks end at {want - 1} of {n}")


def label_page(reader, out, pages, page, cache):
    if pages[page].get("failed") or rd.has_refusal(pages[page]):
        return {
            "page": page,
            "label": {
                "printed_page": None,
                "page_kinds": [],
                "blocks": [],
                "references": [],
            },
            "errors": [],
            "calls": [],
        }
    dest = cache / f"p{page:03d}.json"
    if dest.exists():
        saved = json.loads(dest.read_text())
        if rd.has_refusal(saved):
            saved["label"] = None
        return saved
    ls = lines_of(pages[page])
    prev = lines_of(pages.get(page - 1, {}))[-12:]
    nxt = lines_of(pages.get(page + 1, {}))[:8]
    prompt = (
        PROMPT.replace("{prev}", "\n".join(prev) or "(none)")
        .replace(
            "{this}",
            "\n".join(f"{i}: {l}" for i, l in enumerate(ls, 1)) or "(no lines)",
        )
        .replace("{next}", "\n".join(nxt) or "(none)")
    )
    rec, errors, calls = None, [], []
    for attempt in range(3):
        text, meta = rd.call(out, reader, prompt, None, attempts=2, timeout=300)
        calls.append(meta)
        if rd.refused(meta):
            errors.append("provider refused section labelling")
            break
        if rd.STOP.is_set():
            return None
        try:
            lab = parse_json(text)
            if not ls:
                lab["blocks"] = []
            check(lab, len(ls))
            rec = lab
            break
        except Exception as e:  # noqa: BLE001 - malformed label is evidence; retry
            errors.append(repr(e)[:200])
    out_rec = {"page": page, "label": rec, "errors": errors, "calls": calls}
    dest.write_text(json.dumps(out_rec, ensure_ascii=False, indent=1))
    return out_rec


def frozen_images(book):
    return json.loads((EXP / f"inputs/books/{book}/images.json").read_text())


def build(
    book, pages, labels, cfg, model, outdir, images=None, *, review_failures=False
):
    """images: the book's page image records; by default the frozen benchmark's images.json.

    Review derivatives opt into explicit missing-crop checks. Refused page reads
    are excluded in every path, including historical fallback-derived caches.
    This function never retries a crop or makes a model call.
    """
    pages = {
        p: (
            {"final_text": "", "crops": [], "corrections": [], "failed": True}
            if rd.has_refusal(rec)
            else rec
        )
        for p, rec in pages.items()
    }
    labels = {
        p: (None if pages.get(p, {}).get("failed") or rd.has_refusal(label) else label)
        for p, label in labels.items()
    }
    images = {p["physical_page"]: p for p in images or frozen_images(book)}
    sections, order, ids = {}, [], set()
    page_sections = {p: [] for p in images}
    printed = {}
    unresolved, n_unres = [], 0

    def new_section(title, kind, page):
        base = f"{book}:{slug(title) or f'untitled-p{page:03d}'}"
        sid, k = base, 2
        while sid in ids:
            sid, k = f"{base}-{k}", k + 1
        ids.add(sid)
        s = {
            "id": sid,
            "kind": kind if kind in SECTION_KINDS else "passage",
            "title": title,
            "physical_pages": [],
            "printed_pages": [],
            "status": "complete_in_book",
            "parts": [],
            "references": [],
            "unresolved": [],
        }
        sections[sid] = s
        order.append(sid)
        return s

    def find(title, page, cont):
        if (
            title and cont
        ):  # title printed on the previous page (e.g. a title-only page labelled footer)
            for sid in reversed(page_sections.get(page - 1, [])):
                s = sections[sid]
                if not s["title"] and norm(title) in norm(
                    " ".join(p["text"] or "" for p in s["parts"])
                ):
                    s["title"] = title
                    return s
        if title:
            for sid in reversed(order):
                s = sections[sid]
                if s["physical_pages"] and page - s["physical_pages"][-1] > 8:
                    continue
                if s["title"] and (
                    norm(s["title"]) == norm(title)
                    or difflib.SequenceMatcher(
                        None, norm(s["title"]), norm(title)
                    ).ratio()
                    >= 0.88
                ):
                    if (
                        s["physical_pages"]
                        and s["physical_pages"][-1] < page
                        and not cont
                        and page - s["physical_pages"][-1] > 2
                    ):
                        continue
                    return s
        if cont:
            for q in range(page - 1, max(0, page - 4), -1):
                own = [
                    sid
                    for sid in page_sections.get(q, [])
                    if sections[sid]["kind"] != "chapter"
                ] or page_sections.get(q, [])
                if own:
                    s = sections[own[-1]]
                    # a titled block never continues an untitled holder of only footers/graphics (a photo
                    # or folio page); differently-titled sections are kept, as continuation titles vary
                    if (
                        title
                        and not s["title"]
                        and not any(
                            p["kind"] not in ("footer", "graphic") for p in s["parts"]
                        )
                    ):
                        return None
                    return s
        return None

    def add_page(s, page):
        if page not in s["physical_pages"]:
            s["physical_pages"].append(page)
            s["printed_pages"].append(printed.get(page))
        if s["id"] not in page_sections[page]:
            page_sections[page].append(s["id"])

    line_owner = {}
    for page in sorted(images):
        rec, lab = pages.get(page), (labels.get(page) or {}).get("label")
        ls = lines_of(rec or {})
        printed[page] = (lab or {}).get("printed_page")
        if printed[page] is not None:
            printed[page] = str(printed[page])
        if not rec or not rec.get("final_text"):
            n_unres += 1
            unresolved.append(
                {
                    "id": f"u{n_unres}",
                    "section_id": None,
                    "physical_page": page,
                    "source_fragment": None,
                    "field": "other",
                    "reason": "page transcription failed",
                    "proposed_value": None,
                }
            )
        if lab is None and ls:
            n_unres += 1
            unresolved.append(
                {
                    "id": f"u{n_unres}",
                    "section_id": None,
                    "physical_page": page,
                    "source_fragment": ls[0][:120],
                    "field": "ownership",
                    "reason": "section labelling failed; page kept as one untitled block",
                    "proposed_value": None,
                }
            )
            lab = {
                "blocks": [
                    {
                        "from": 1,
                        "to": len(ls),
                        "section_title": None,
                        "section_kind": "passage",
                        "continues_previous_page": False,
                        "part": "text",
                    }
                ],
                "references": [],
            }
        blocks = (lab or {}).get("blocks") or []
        footers = [b for b in blocks if b.get("part") == "footer"]
        body = [b for b in blocks if b.get("part") != "footer"]
        for b in body:
            title = (b.get("section_title") or "").strip() or None
            cont = bool(b.get("continues_previous_page"))
            s = find(title, page, cont) or new_section(
                title, b.get("section_kind"), page
            )
            add_page(s, page)
            text = "\n".join(ls[int(b["from"]) - 1 : int(b["to"])])
            s["parts"].append(
                {
                    "kind": b.get("part") or "text",
                    "source_page": page,
                    "text": text,
                    "table": None,
                    "unresolved": [],
                }
            )
            for i in range(int(b["from"]), int(b["to"]) + 1):
                line_owner[(page, i)] = s["id"]
        if (
            footers or not body
        ):  # running heads/folios and image-only pages need an owner too
            if page_sections[page]:
                s = sections[page_sections[page][-1]]
            else:
                s = new_section(None, "passage", page)
            add_page(s, page)
            for b in footers:
                s["parts"].append(
                    {
                        "kind": "footer",
                        "source_page": page,
                        "text": "\n".join(ls[int(b["from"]) - 1 : int(b["to"])]),
                        "table": None,
                        "unresolved": [],
                    }
                )
                for i in range(int(b["from"]), int(b["to"]) + 1):
                    line_owner[(page, i)] = s["id"]
            if not body and not footers:
                s["parts"].append(
                    {
                        "kind": "graphic",
                        "source_page": page,
                        "text": None,
                        "table": None,
                        "unresolved": [],
                        "description": "no printed text transcribed",
                    }
                )
        for r in (lab or {}).get("references") or []:
            try:
                sid = line_owner.get((page, int(r.get("line"))))
            except (TypeError, ValueError):
                sid = None
            sid = sid or (page_sections[page] or [None])[0]
            if sid:
                sections[sid]["references"].append(
                    {
                        "source_page": page,
                        "label": r.get("label"),
                        "printed_target": None
                        if r.get("printed_target") is None
                        else str(r["printed_target"]),
                        "target_section_id": None,
                        "scope": "authored reference",
                    }
                )

    by_printed = {v: k for k, v in printed.items() if v}
    for s in sections.values():
        for r in s["references"]:
            q = by_printed.get(r["printed_target"])
            if q:
                cands = [
                    sid for sid in page_sections[q] if sections[sid]["kind"] == "recipe"
                ] or page_sections[q]
                r["target_section_id"] = cands[0] if cands else None

    def owner_of(page, line_text):
        ls = lines_of(pages.get(page) or {})
        for i, l in enumerate(ls, 1):
            if l.strip() == (line_text or "").strip():
                return line_owner.get((page, i))
        return None

    reviews, corrections = [], []
    for page in sorted(images):
        rec = pages.get(page)
        if not rec:
            continue
        qty_secs = (
            sorted(
                {
                    sid
                    for sid in page_sections[page]
                    if any(
                        p["source_page"] == page
                        and p["kind"] in ("ingredients", "table")
                        for p in sections[sid]["parts"]
                    )
                }
            )
            or page_sections[page]
        )
        # v4: a tied line, or one whose correction failed the per-quantity check, left the page read in
        # place; record the page's current line as unreviewed rather than a crop reading it never took
        rejected = {
            (c.get("to") or "").strip()
            for c in rec.get("corrections") or []
            if c.get("rejected")
        }
        page_lines = lines_of(rec)
        for n, c in enumerate(rec.get("crops") or []):
            if review_failures and (
                "image" not in c or len(c.get("readings") or {}) < 2
            ):
                # A failed render or insufficient readings never confirms a
                # quantity. Review derivatives retain that missing check without
                # retrying it or inventing a crop-image receipt.
                for sid in qty_secs or [None]:
                    n_unres += 1
                    unresolved.append(
                        {
                            "id": f"u{n_unres}",
                            "section_id": sid,
                            "physical_page": page,
                            "source_fragment": None,
                            "field": "amount",
                            "reason": "quantity crop unavailable or unconfirmed; page read kept",
                            "proposed_value": None,
                            "box": c.get("box") or [0, 0, 1, 1],
                        }
                    )
            if "image" not in c:
                continue
            reviewed, uncertain = [], []
            for v in c.get("voted") or []:
                tied = v.get("tie") or v["support"] * 2 <= v["of"]
                same_words = [
                    l
                    for l in page_lines
                    if fp.similar(fp.key(fp.clean_line(l)), v["key"])
                ]
                landed = (
                    v["line"]
                    if v["line"] in page_lines
                    else next(  # a confirmed vote's quantities are
                        (l for l in same_words if fp.qty(l) == fp.qty(v["line"])), None
                    )
                )  # in the text
                if not tied and v["line"].strip() not in rejected and landed:
                    reviewed.append(
                        landed
                    )  # as it stands in the text, not the crop's formatting
                    continue
                # repeated ingredient lines (salt, oil) make a wording-only match ambiguous: only name one line
                current = same_words[0] if len(same_words) == 1 else None
                readings = sorted(set((v.get("readings") or {}).values())) or [
                    v["line"]
                ]
                uncertain.append(current or v["line"])
                n_unres += 1
                unresolved.append(
                    {
                        "id": f"u{n_unres}",
                        "section_id": owner_of(page, current),
                        "physical_page": page,
                        "source_fragment": current,
                        "field": "amount",
                        "reason": (
                            "crop readers did not reach a majority"
                            if tied
                            else "crop majority not confirmed per quantity; page read kept"
                            if v["line"].strip() in rejected
                            else "crop majority not matched to a page-read line; not applied"
                        ),
                        "proposed_value": None,
                        "crop_readings": readings,
                    }
                )
            reviews.append(
                {
                    "id": f"{book}:p{page:03d}:crop{n}",
                    "physical_page": page,
                    "request": {
                        "physical_page": page,
                        "field_scope": qty_secs,
                        "file": c.get("request"),
                        "box": c.get("box"),
                    },
                    "returned_image": c["image"],
                    "returned_sha256": c["sha256"],
                    "fields_reviewed": reviewed,
                    "remaining_uncertainty": uncertain,
                    "tool": "pdf_helper.detail (guarded crop), read by "
                    + ", ".join(sorted(c.get("readings") or {})),
                }
            )
        for k, c in enumerate(rec.get("corrections") or []):
            corrections.append(
                {
                    "id": f"{book}:p{page:03d}:c{k}",
                    "physical_page": page,
                    "section_id": owner_of(page, c.get("to")),
                    **c,
                }
            )

    ledger = []
    for page in sorted(images):
        im = images[page]
        kinds = ((labels.get(page) or {}).get("label") or {}).get("page_kinds") or []
        ledger.append(
            {
                "physical_page": page,
                "image": im["image"],
                "sha256": im["sha256"],
                "source_sha256": im["source_sha256"],
                "printed_page": printed.get(page),
                "kinds": kinds,
                "section_ids": page_sections[page],
                "inspected": True,
                "tool": f"{model} x3 voting pipeline (page read + guarded crops)",
                "unresolved": [
                    u["id"] for u in unresolved if u["physical_page"] == page
                ],
            }
        )

    outdir.mkdir(parents=True, exist_ok=True)

    def jl(name, rows):
        (outdir / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        )

    jl("sections.jsonl", [sections[sid] for sid in order])
    jl("page-ledger.jsonl", ledger)
    jl("quantity-review.jsonl", reviews)
    jl("corrections.jsonl", corrections)
    jl("unresolved.jsonl", unresolved)
    (outdir / "progress.json").write_text(
        json.dumps(
            {
                "config_id": cfg,
                "book_id": book,
                "status": "complete",
                "physical_pages_total": len(images),
                "pages_inspected": [[min(images), max(images)]],
                "next_page": None,
                "open_continuations": [],
                "pending_detail_reviews": [],
                "detail_calls": len(reviews),
            },
            indent=2,
        )
    )
    (outdir / "report.md").write_text(
        f"# {cfg} book {book}\n\nScripted pipeline, not an agent run. Each page: one {model} page read, three "
        f"{model} region-box calls, guarded pdf_helper crops of the agreed regions, three {model} crop "
        "readings per crop, per-line majority vote patched into the page read. Sectioning: one text-only "
        f"{model} call per page labels line ranges (section, part, folio, references); text is copied from "
        "the voted transcription by line range, never retyped. Sections are joined across pages by title.\n\n"
        f"Pages {len(images)}, sections {len(order)}, quantity reviews {len(reviews)}, corrections "
        f"{len(corrections)}, unresolved {len(unresolved)}.\n"
    )
    files = {}
    for name in [
        "sections.jsonl",
        "page-ledger.jsonl",
        "quantity-review.jsonl",
        "corrections.jsonl",
        "unresolved.jsonl",
        "progress.json",
        "report.md",
    ]:
        b = (outdir / name).read_bytes()
        files[name] = {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
    (outdir / "freeze.json").write_text(
        json.dumps(
            {
                "config_id": cfg,
                "book_id": book,
                "status": "complete",
                "source_sha256": next(iter(images.values()))["source_sha256"],
                "coverage": [[min(images), max(images)]],
                "files": files,
            },
            indent=2,
        )
    )
    return {
        "sections": len(order),
        "reviews": len(reviews),
        "corrections": len(corrections),
        "unresolved": len(unresolved),
    }


def assemble(
    reader, name, pipe, book, outdir, cfg, workers=4, allow_missing=False, images=None
):
    """reader: the sample label that sections (READERS[0]); name: how report.md names the reader.
    allow_missing only after the page run's retry pass has finished. images: as in build."""
    images = images or frozen_images(book)
    pages = {}
    for p in images:
        f = pipe / "pages" / f"b{book}-p{p['physical_page']:03d}.json"
        if f.exists():
            saved = json.loads(f.read_text())
            if not rd.has_refusal(saved):
                pages[p["physical_page"]] = saved
    missing = [p["physical_page"] for p in images if p["physical_page"] not in pages]
    if missing and not allow_missing:
        sys.exit(
            f"book {book}: {len(missing)} pages not transcribed yet, e.g. {missing[:10]}"
        )
    for p in (
        missing
    ):  # page read failed after retries: recorded as unresolved, never invented
        pages[p] = {"final_text": "", "crops": [], "corrections": [], "failed": True}
    cache = pipe / "sections" / str(book)
    cache.mkdir(parents=True, exist_ok=True)
    (pipe / "empty").mkdir(exist_ok=True)
    labels = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {
            ex.submit(label_page, reader, pipe, pages, p, cache): p
            for p in sorted(pages)
        }
        for f in cf.as_completed(futs):
            labels[futs[f]] = f.result()
    if rd.STOP.is_set():
        sys.exit("stopped on usage/rate limit; rerun to resume")
    failed = [
        p for p, r in labels.items() if r and r["label"] is None and lines_of(pages[p])
    ]
    print(
        json.dumps({"book": book, "labelled": len(labels), "label_failures": failed}),
        flush=True,
    )
    result = {"book": book, **build(book, pages, labels, cfg, name, outdir, images)}
    print(json.dumps(result), flush=True)
    return result
