"""Score pilot pages against the frozen reference: page read alone vs after crop vote.

Same matching as the probe rescorer: NFKC/casefold/dash/whitespace normalisation,
table rows match when every cell appears on one line. Ambiguous, continuation and
ownership items are excluded (they are not transcription text). Only pages with a frozen
reference count (the 39 pilot pages), so a full-book pages dir scores the same pages.
This is a cheap screen: the references were also used while tuning the assembler, so it
does not replace the per-book evaluator grade.
"""

import collections
import json
import re
import unicodedata
from pathlib import Path

from pipeline import EXP


def norm(s):
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"-\s+", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def reference_pages():
    return sorted(
        (b, json.loads(line)["physical_page"])
        for b in (6, 79, 81)
        for line in (EXP / f"evaluation/references/{b}/reference.jsonl")
        .read_text()
        .splitlines()
    )


def items(b, p):
    for line in (
        (EXP / f"evaluation/references/{b}/reference.jsonl").read_text().splitlines()
    ):
        d = json.loads(line)
        if d["physical_page"] == p:
            return [
                i
                for i in d["items"]
                if not i.get("ambiguous")
                and i["field"] not in ("continuation", "ownership")
            ]
    return []


def hits(text, its):
    text = (text or "").replace("\t", " | ")
    lines = [norm(x) for x in text.splitlines()]
    hay = norm(text)
    res = []
    for it in its:
        t = it["exact_text"].removeprefix("column headers: ")
        if " | " in t:
            cells = [norm(c) for c in t.split(" | ")]
            ok = any(all(c in ln for c in cells) for ln in lines)
        else:
            ok = norm(t) in hay
        res.append(ok)
    return res


def score(pages_dir):
    """Returns ({book: Counter}, [detail lines]). Counter keys: n, before, after (items), qn,
    qbefore, qafter (quantity lines), pages, missing, seconds, corrections."""
    per_book = collections.defaultdict(collections.Counter)
    detail = []
    for book, page in reference_pages():
        its = items(book, page)
        if not its:
            continue
        f = Path(pages_dir) / f"b{book}-p{page:03d}.json"
        # a page the reader lost scores zero; it is never dropped from the denominator
        r = (
            json.loads(f.read_text())
            if f.exists()
            else {
                "book": book,
                "page": page,
                "page_read": {"text": ""},
                "final_text": "",
                "corrections": [],
                "missing": True,
            }
        )
        per_book[book]["missing"] += bool(r.get("missing"))
        before = hits(r["page_read"]["text"], its)
        after = hits(r["final_text"], its)
        qty = [i["field"] in ("ingredient_line", "amount") for i in its]
        c = per_book[r["book"]]
        c["n"] += len(its)
        c["before"] += sum(before)
        c["after"] += sum(after)
        c["qn"] += sum(qty)
        c["qbefore"] += sum(b for b, q in zip(before, qty) if q)
        c["qafter"] += sum(a for a, q in zip(after, qty) if q)
        c["seconds"] += r.get("seconds") or 0
        c["pages"] += 1
        c["corrections"] += len(r["corrections"])
        for it, b, a in zip(its, before, after):
            if b != a or not a:
                detail.append(
                    f"b{r['book']}p{r['page']} {'FIXED' if a and not b else 'BROKE' if b and not a else 'miss '} "
                    f"[{it['field']}] {it['exact_text'][:110]}"
                )
    return dict(per_book), detail


def report(pages_dir, show_detail=True):
    per_book, detail = score(pages_dir)
    tot = collections.Counter()
    for b, c in sorted(per_book.items()):
        print(
            f"book {b}: pages {c['pages']}  items {c['before']}/{c['n']} -> {c['after']}/{c['n']}  "
            f"quantity lines {c['qbefore']}/{c['qn']} -> {c['qafter']}/{c['qn']}  "
            f"corrections {c['corrections']}  missing pages {c['missing']}  avg {c['seconds'] / max(1, c['pages']):.0f}s/page"
        )
        tot.update(c)
    print(
        f"ALL: items {tot['before']}/{tot['n']} -> {tot['after']}/{tot['n']}  "
        f"quantity lines {tot['qbefore']}/{tot['qn']} -> {tot['qafter']}/{tot['qn']}"
    )
    if show_detail:
        print("\n".join(detail))
    return tot
