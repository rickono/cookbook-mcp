"""Page pipeline: stateless page read + zoomed quantity vote, frozen at the 2026-10-19 benchmark.

Per page (READERS = three sample labels, usually one spec three times):
  A. full-page transcription by READERS[0]
  B. quantity-region boxes from all three readers, clustered (>=2 readers agree)
  C. guarded detail crop of each region via the shared pdf_helper (no local imaging)
  D. all three readers transcribe each crop; lines are voted
  E. page lines whose wording matches a voted crop line take the voted quantities
     (strict majority per quantity, missing readings count against); voted lines the
     page read missed are appended. A reader's crop reading supersedes its own page read.

Prompts, clustering, crop sizing and voting are the benchmark protocol: changing any of
them makes new results incomparable with baseline.json (bench.py records PROTOCOL_SHA).
Ported unchanged from free_pipeline.py + paid_pipeline.py; only the reader backend moved.
"""

import collections
import concurrent.futures as cf
import difflib
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

import readers as rd

DATA = Path(os.environ.get("COOKBOOK_DATA", Path.home() / "cookbook-mcp-data"))
EXP = (
    DATA / "batches/model-comparison-three-books-20261015"
)  # frozen inputs + references
HELPER = (
    DATA / "batches/pdf-library-18-20261014/helper/pdf_helper.py"
)  # runs scripts/ocr_sandbox.py

READERS = []  # set by bench.py: e.g. ["claude:claude-haiku-5-5#1", "...#2", "...#3"]
FALLBACK = (
    None  # Historical config metadata only; refusals never dispatch another reader.
)

PAGE_PROMPT = (
    "Transcribe every word printed on the attached cookbook page image exactly as printed, "
    "top to bottom, keeping ingredient lines and quantities exactly (fractions, units, "
    "punctuation). Write each ingredient on one line. Write table rows as 'name | col1 | col2'. "
    "Plain text only, no commentary. Do not use any tools. If you cannot actually see the "
    "image, reply only NO_IMAGE."
)
REGION_PROMPT = (
    "Look at the attached cookbook page. Find every block that contains ingredient quantities "
    "or a quantity table (ingredient lists, scaling tables, measurements). Reply with JSON only: "
    '{"regions":[{"label":"short name","box":[left,top,right,bottom]}]} where box values are '
    "fractions of page width/height from 0 to 1 (0,0 = top-left). Be generous: include the whole "
    'block with a little margin. If none, {"regions":[]}. No tools.'
)
CROP_PROMPT = (
    "This is a zoomed crop of a cookbook page containing ingredient quantities. Transcribe every "
    "line exactly as printed, one ingredient per line (join wrapped continuation lines). Write "
    "table rows as 'name | col1 | col2 | ...', header row first. Read every fraction glyph "
    "carefully (e.g. ¼ ⅓ ½ ⅔ ¾ ⅛) and copy it exactly. Skip words cut off at the crop edge. "
    "Plain text only, no commentary, no tools."
)

_log_lock = threading.Lock()


# ---------- text normalisation / voting ----------

FRACTIONS = "¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞"


def norm(s):
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"-\s+", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_line(s):
    s = s.strip().strip("`").replace("\t", " | ")
    s = re.sub(
        r"^\s*[-•]\s+", "", s
    )  # markdown bullets only; keep numbering and asterisks
    return re.sub(r"\s*\|\s*", " | ", s).strip(" |") if "|" in s else s


def key(s):
    """Wording without quantities: what a line *is*, independent of its numbers."""
    s = unicodedata.normalize("NFKD", s).casefold()
    s = re.sub(rf"[\d{FRACTIONS}⁄/.,]+", " ", s)
    s = re.sub(r"[^a-z]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def qty(s):
    return re.findall(
        rf"[\d{FRACTIONS}][\d{FRACTIONS}⁄/.,]*", unicodedata.normalize("NFC", s)
    )


def similar(a, b):
    return a == b or (
        len(a) > 6 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.88
    )


def vote(readings):
    """readings: {model: text}. Group lines by wording key; majority exact line per group."""
    groups = []  # [key, {model: line}]
    for model, text in readings.items():
        for raw in text.splitlines():
            line = clean_line(raw)
            k = key(line)
            if not line or not k or not qty(line):
                continue
            for g in groups:
                if model not in g[1] and similar(g[0], k):
                    g[1][model] = line
                    break
            else:
                groups.append([k, {model: line}])
    voted = []
    for k, by_model in groups:
        if len(by_model) < 2:
            continue
        counts = collections.Counter(norm(v) for v in by_model.values())
        best, n = counts.most_common(1)[0]
        line = next(v for v in by_model.values() if norm(v) == best)
        voted.append(
            {
                "key": k,
                "line": line,
                "support": n,
                "of": len(readings),
                "readers": sorted(readings),
                "readings": by_model,
                "tie": n < 2,
            }
        )
    return voted


QTY_RE = re.compile(rf"[\d{FRACTIONS}][\d{FRACTIONS}⁄/.,]*")


def majority(values, voters):
    """Strict-majority value among `voters` ballots (abstentions count against), else None."""
    if not values:
        return None
    best, n = collections.Counter(values).most_common(1)[0]
    return best if n * 2 > voters else None


def put_qty(line, values):
    """Replace the quantity tokens of `line` positionally, leaving every other byte alone."""
    spans = [m.span() for m in QTY_RE.finditer(unicodedata.normalize("NFC", line))]
    line = unicodedata.normalize("NFC", line)
    for (a, b), v in reversed(list(zip(spans, values))):
        line = line[:a] + v + line[b:]
    return line


def patch(page_text, voted, page_model=None):
    """Lines are left byte-identical unless corrected.

    Ballots are per model. The page read is one more ballot only when its model did not
    also read the zoomed crop (a model's crop reading supersedes its own page read).
    Wording and each quantity position are voted separately, so formatting differences
    between readers ('2¾ lb (4)' vs '2¾ lb | (4)') no longer split a quantity vote.
    A change needs a strict majority of all ballots; missing readings count against."""
    return _patch(page_text, voted, page_model, reviewed=False)


def reviewed_patch(page_text, voted, page_model=None):
    """Replay saved votes for review, preserving headings and existing occurrences.

    This is separate from the frozen benchmark and production page reader. It makes
    no calls and writes nothing; reviewed derivatives need their own admission and
    provenance before a build can use them.
    """
    return _patch(page_text, voted, page_model, reviewed=True)


def patch_origins(page_text, voted, page_model=None, *, reviewed=False):
    """Replay with stable origins for nonblank output lines, without model calls.

    Each origin names an original page-read line or an appended crop vote. They
    let a review remap cached line labels by identity rather than fuzzy text matches.
    The ordinary patch API and its frozen behavior are unchanged.
    """
    origins = [("page", i) for i in range(len(page_text.splitlines()))]
    text, corrections = _patch(
        page_text, voted, page_model, reviewed=reviewed, origins=origins
    )
    return (
        text,
        corrections,
        [origin for origin, line in zip(origins, text.splitlines()) if line.strip()],
    )


def _patch(page_text, voted, page_model, *, reviewed, origins=None):
    lines = page_text.splitlines()
    used, corrections = set(), []
    for vote_index, v in enumerate(voted):
        by_model = v["readings"]
        page_votes = page_model not in v.get("readers", by_model)
        voters = v["of"] + page_votes
        for i, line in enumerate(lines):
            if (
                i in used
                or (reviewed and not qty(line))
                or not similar(key(clean_line(line)), v["key"])
            ):
                continue
            used.add(i)
            new, why = line, []
            words = [key(x) for x in by_model.values()] + [
                key(clean_line(line))
            ] * page_votes
            w = majority(words, voters)
            if w and w != key(clean_line(line)):
                new = next(x for x in by_model.values() if key(x) == w)
                why.append("wording")
            target = qty(new)
            tuples = [qty(x) for x in by_model.values()] + [qty(line)] * page_votes
            if all(len(t) == len(target) for t in tuples):
                cells = [
                    majority([t[k] for t in tuples], voters) or target[k]
                    for k in range(len(target))
                ]
            else:
                cells = list(majority([tuple(t) for t in tuples], voters) or target)
                if len(cells) != len(target):
                    cells = target
            if cells != target:
                new = put_qty(new, cells)
                why.append("quantity")
            if new != line:
                corrections.append(
                    {"from": line, "to": new, "voters": voters, "why": why}
                )
                lines[i] = new
            elif v["line"] != line and qty(v["line"]) != qty(line):
                corrections.append(
                    {
                        "from": line,
                        "to": v["line"],
                        "voters": voters,
                        "rejected": "no strict majority per quantity",
                    }
                )
            break
        else:
            # Overlapping crops can vote for the same source occurrence. Once its
            # existing amount line has been used, or the crop shows only part of
            # an existing paragraph, another vote is not evidence of missing text.
            # Keep authored repetitions already present in `lines`.
            if reviewed and (
                any(
                    qty(line) and similar(key(clean_line(line)), v["key"])
                    for line in lines
                )
                or re.search(
                    r"(?<!\w)" + re.escape(norm(v["line"])) + r"(?!\w)",
                    norm(" ".join(lines)),
                )
            ):
                continue
            if not v["tie"] and v["support"] * 2 > voters - page_votes:
                corrections.append(
                    {
                        "from": None,
                        "to": v["line"],
                        "support": v["support"],
                        "added": True,
                    }
                )
                lines.append(v["line"])
                if origins is not None:
                    origins.append(("vote", vote_index))
    return "\n".join(lines), corrections


# ---------- regions / guarded crops ----------


def parse_regions(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        regions = json.loads(m.group(0))["regions"] if m else []
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for r in regions:
        try:
            l, t, rr, b = (float(x) for x in r["box"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= l < rr <= 1 and 0 <= t < b <= 1:
            out.append((l, t, rr, b))
    return out


def overlap(a, b):
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    area = lambda x: (x[2] - x[0]) * (x[3] - x[1])
    return iw * ih / min(area(a), area(b))


def cluster(boxes_by_model, pad=0.02):
    items = [(m, b) for m, bs in boxes_by_model.items() for b in bs]
    clusters = []
    for m, b in items:
        hit = [c for c in clusters if any(overlap(b, x) > 0.4 for _, x in c)]
        merged = [(m, b)] + [x for c in hit for x in c]
        clusters = [c for c in clusters if c not in hit] + [merged]
    out = []
    for c in clusters:
        if len({m for m, _ in c}) < 2:
            continue
        l = min(b[0] for _, b in c)
        t = min(b[1] for _, b in c)
        r = max(b[2] for _, b in c)
        bt = max(b[3] for _, b in c)
        out.append(
            [
                round(max(0, l - pad), 3),
                round(max(0, t - pad), 3),
                round(min(1, r + pad), 3),
                round(min(1, bt + pad), 3),
            ]
        )
    return sorted(out, key=lambda x: (x[1], x[0]))


def guarded_crop(out, book, page, source_sha, box, n):
    w, h = box[2] - box[0], box[3] - box[1]
    long_edge = int(min(6000, max(2301, 2400 / max(w * 0.72, h))))
    req = out / "detail-requests" / f"b{book}-p{page:03d}-r{n}.json"
    req.parent.mkdir(exist_ok=True)
    req.write_text(
        json.dumps(
            {
                "book_id": book,
                "source_sha256": source_sha,
                "physical_page": page,
                "region": box,
                "long_edge": long_edge,
                "reason": "free-pipeline quantity detail vote",
                "field_scope": [f"page-{page}.quantities"],
            }
        )
    )
    p = subprocess.run(
        [sys.executable, str(HELPER), "detail", str(book), str(req)],
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    try:
        img = json.loads(p.stdout)["images"][0]
        return {
            "image": img["image"],
            "sha256": img["sha256"],
            "pixels": img.get("pixels"),
            "long_edge": long_edge,
            "request": str(req),
        }
    except (ValueError, KeyError, IndexError):
        return {"error": (p.stdout + p.stderr)[-500:], "request": str(req)}


# ---------- per page ----------


def image_meta(book, page):
    for p in json.loads((EXP / f"inputs/books/{book}/images.json").read_text()):
        if p["physical_page"] == page:
            return p
    raise KeyError(page)


def run_page(out, book, page, meta=None):
    """meta: the page image record; by default the frozen benchmark's (production passes the
    guarded helper's render)."""
    dest = out / "pages" / f"b{book}-p{page:03d}.json"
    if dest.exists():
        saved = json.loads(dest.read_text())
        if rd.has_refusal(saved):
            saved.update(refused=True, failed=True, final_text="", corrections=[])
            saved["page_read"]["text"] = None
        return saved
    meta = meta or image_meta(book, page)
    t0 = time.time()
    rec = {
        "book": book,
        "page": page,
        "image": meta["image"],
        "image_sha256": meta["sha256"],
        "regions": {"by_model": {}, "calls": [], "merged": []},
        "crops": [],
    }

    def preserve_refusal():
        rec.update(refused=True, failed=True, final_text="", corrections=[])
        rec["page_read"]["text"] = None
        rec["seconds"] = round(time.time() - t0)
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        return rec

    text, c = rd.call(out, READERS[0], PAGE_PROMPT, meta["image"])
    tried = [c]
    rec["page_read"] = {"text": text, "calls": tried}
    if rd.refused(c):
        return preserve_refusal()
    boxes, calls = {}, []
    for m in READERS:
        t, c = rd.call(out, m, REGION_PROMPT, meta["image"])
        calls.append({**c, "raw": t})
        if rd.refused(c):
            rec["regions"] = {"by_model": boxes, "calls": calls, "merged": []}
            return preserve_refusal()
        boxes[m] = parse_regions(t)
    rec["regions"] = {"by_model": boxes, "calls": calls, "merged": cluster(boxes)}
    crops, voted_all = [], []
    for n, box in enumerate(rec["regions"]["merged"]):
        crop = guarded_crop(out, book, page, meta["source_sha256"], box, n)
        crop["box"] = box
        if "image" in crop:
            readings, ccalls = {}, []
            for m in READERS:
                t, c = rd.call(out, m, CROP_PROMPT, crop["image"])
                ccalls.append(c)
                if rd.refused(c):
                    crop["calls"] = ccalls
                    crops.append(crop)
                    rec["crops"] = crops
                    return preserve_refusal()
                if t:
                    readings[m] = t
            crop["readings"], crop["calls"] = readings, ccalls
            crop["voted"] = vote(readings) if len(readings) >= 2 else []
            voted_all += crop["voted"]
        crops.append(crop)
    rec["crops"] = crops
    page_model = (tried[-1] or {}).get("model") if text else None
    final, corrections = patch(text or "", voted_all, page_model)
    rec["final_text"], rec["corrections"] = final, corrections
    rec["seconds"] = round(time.time() - t0)
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


def run(out, jobs, workers=3):
    """jobs: [(book, page)]. Finished pages are cached in out/pages and skipped on rerun; a page
    whose page read failed, or that a STOP interrupted, is not cached so a rerun redoes it."""
    (out / "empty").mkdir(parents=True, exist_ok=True)

    def one(book, page):
        rec = run_page(out, book, page)
        if rd.STOP.is_set() or not rec["page_read"]["text"]:
            (out / "pages" / f"b{book}-p{page:03d}.json").unlink(missing_ok=True)
        return rec

    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(one, b, p): (b, p) for b, p in jobs}
        for f in cf.as_completed(futs):
            b, p = futs[f]
            try:
                r = f.result()
                with _log_lock:
                    print(
                        json.dumps(
                            {
                                "book": b,
                                "page": p,
                                "seconds": r.get("seconds"),
                                "regions": len(r["regions"]["merged"]),
                                "corrections": len(r["corrections"]),
                                "page_model": (r["page_read"]["calls"] or [{}])[-1].get(
                                    "model"
                                ),
                            }
                        ),
                        flush=True,
                    )
            except Exception as e:  # noqa: BLE001 - keep going; failure is evidence
                print(
                    json.dumps({"book": b, "page": p, "exception": repr(e)}), flush=True
                )
