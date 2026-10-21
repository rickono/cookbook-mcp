#!/usr/bin/env python3
"""Decide agent transcription reports by a blind re-read of the original page (Mac only).

An agent that reads the library compares a scanned quantity with the original page and
files a report (report_transcription_issue). A report is a claim, not an edit. This
script settles each one without trusting it:

  1. the report's region (or, without one, the whole page) is cut from the registered
     source by the guarded pdf_helper crop, inside scripts/ocr_sandbox.py;
  2. the reader (default Haiku 5.5) reads the crop three times. The prompt is the
     benchmark's crop or page prompt, and contains neither the library text nor the
     proposed text;
  3. each reading votes for the proposed text, for the current library text, or for
     neither. Two of three readings decide; a failed reading counts against both:
       proposed (>=2)  -> correction (source_reviewed by an agent reviewer)
       current  (>=2)  -> rejected
       otherwise       -> owner queue

Decisions are written once per report under --out (outside Git) and never redone.
corrections.jsonl and owner-queue.jsonl are rebuilt from the decisions on every run;
the next scanned-book publication applies corrections.jsonl (cookbook.ledger rows, in
decision order). A correction binds to the source digest and physical page, not to the
publication the report was filed against, so reports against older publications still
apply; a correction decided again from a later report is kept once, at its first
decision. The library itself is not touched here, and nothing is uploaded: reports are
only read.

  python3 scripts/triage_reports.py --reports DIR            # a local reports store
  python3 scripts/triage_reports.py --reports-s3             # REPORTS_* env, the Mac's key
  python3 scripts/triage_reports.py --reports DIR --dry-run  # list what would be decided
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts/reader_bench"))
sys.path.insert(0, str(REPO / "src"))

import pipeline as fp
import readers as rd

from cookbook import ledger
from cookbook.reports import list_reports

DATA = Path(os.environ.get("COOKBOOK_DATA", Path.home() / "cookbook-mcp-data"))
OUT = DATA / "report-triage"
READER = "claude:claude-haiku-5-5"
SAMPLES = 3
NEEDED = 2  # strict majority of three

_FRACTION = re.compile(r"(\d)([¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞])")


def tokens(text):
    """Words, numbers and symbols, with vulgar fractions spelled out (1½ -> 1 1/2)."""
    text = unicodedata.normalize("NFKC", _FRACTION.sub(r"\1 \2", text))
    return re.findall(r"\w+|[^\w\s]", text.replace("⁄", "/").casefold())


def find(hay, needle):
    """Start offsets where needle occurs as a contiguous token run in hay."""
    n = len(needle)
    return [i for i in range(len(hay) - n + 1) if n and hay[i : i + n] == needle]


def ballot(reading, current, proposed):
    """'proposed', 'current' or None for one blind reading."""
    if reading is None:
        return None
    hay = tokens(reading)
    cur, new = tokens(current), tokens(proposed)
    # Test the longer claim first, so a quote inside the other claim isn't counted twice.
    first, second = (("proposed", new), ("current", cur))[
        :: 1 if len(new) >= len(cur) else -1
    ]
    at = find(hay, first[1])
    if at:
        # The shorter text seen outside the longer one's occurrences makes the reading ambiguous.
        inside = {i + j for i in at for j in range(len(first[1]))}
        stray = [i for i in find(hay, second[1]) if i not in inside]
        return None if stray else first[0]
    return second[0] if find(hay, second[1]) else None


def decide(report, readings):
    votes = {"proposed": 0, "current": 0, "neither": 0}
    for r in readings:
        votes[
            ballot(r, report["quoted_text"], report["proposed_text"]) or "neither"
        ] += 1
    if votes["proposed"] >= NEEDED:
        return "correction", votes
    if votes["current"] >= NEEDED:
        return "rejected", votes
    return "owner_queue", votes


def registered_books():
    """sha256 -> helper book id, from the private guarded helper's frozen manifest."""
    manifest = json.loads((fp.HELPER.parents[1] / "manifest.json").read_text())
    return {b["sha256"]: b["book_id"] for b in manifest["books"]}


def doctor():
    p = subprocess.run(
        [sys.executable, str(REPO / "scripts/ocr_sandbox.py"), "doctor"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    if p.returncode:
        sys.exit(
            "scripts/ocr_sandbox.py doctor refused; guarded crops are unavailable, so triage "
            "was not started:\n" + (p.stdout + p.stderr)[-1500:]
        )


def triage(report, out, *, books, reader=READER, crop=fp.guarded_crop, call=rd.call):
    """One decision record. crop and call are injectable for synthetic tests."""
    base = {
        "report_id": report["report_id"],
        "report": report,
        "reader": f"{reader} x{SAMPLES}",
        "decided_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    book = books.get(report["source_sha256"])
    if report["format"] != "PDF" or book is None:
        return {
            **base,
            "outcome": "owner_queue",
            "reason": "source is not registered with the guarded helper",
        }
    box = report["region"] or [0.0, 0.0, 1.0, 1.0]
    image = crop(
        out,
        book,
        report["physical_page"],
        report["source_sha256"],
        box,
        report["report_id"][:12],
    )
    if "image" not in image:
        return {
            **base,
            "outcome": "owner_queue",
            "reason": "guarded crop failed",
            "crop": image,
        }
    prompt = fp.CROP_PROMPT if report["region"] else fp.PAGE_PROMPT
    readings, calls = [], []
    for k in range(1, SAMPLES + 1):
        text, c = call(out, f"{reader}#{k}", prompt, image["image"])
        readings.append(text)
        calls.append(c)
    outcome, votes = decide(report, readings)
    return {
        **base,
        "outcome": outcome,
        "reason": f"blind re-read votes {votes}",
        "votes": votes,
        "readings": readings,
        "calls": calls,
        "crop": {k: image[k] for k in ("sha256", "long_edge", "request") if k in image},
        "prompt": "crop" if report["region"] else "page",
    }


def unsettled(d):
    """An owner-queue result caused by a failed crop or a timeout is retried, not recorded.

    A provider filter refusal is a real result: it is never retried or worked around.
    """
    if d["outcome"] != "owner_queue":
        return False
    if d["reason"] == "guarded crop failed":
        return True
    return any(
        t is None and not rd.filtered(c)
        for t, c in zip(d.get("readings", []), d.get("calls", []))
    )


def correction(d):
    r = d["report"]
    readings = json.dumps(d["readings"], ensure_ascii=False).encode()
    return {
        "id": r["report_id"],
        "decided_at": d["decided_at"],
        "report_id": r["report_id"],
        "publication_id": r["publication_id"],
        "book_id": r["book_id"],
        "source_id": r["source_id"],
        "source_sha256": r["source_sha256"],
        "physical_page": r["physical_page"],
        "section_id": r["section_id"],
        "region": r["region"],
        "kind": r["kind"],
        "from_text": r["quoted_text"],
        "to_text": r["proposed_text"],
        "state": "source_reviewed",
        "reviewer": {"kind": "agent", "id": f"blind-reread:{d['reader']}"},
        "evidence": {
            "crop_sha256": d["crop"].get("sha256"),
            "readings_sha256": hashlib.sha256(readings).hexdigest(),
            "votes": d["votes"],
        },
    }


def corrections(decisions):
    """Ledger rows for the correction decisions, in decision order, each correction once."""
    rows, seen = [], set()
    for row in sorted(map(correction, decisions), key=ledger.order):
        if ledger.key(row) not in seen:
            seen.add(ledger.key(row))
            rows.append(row)
    return ledger.check(rows)


def rebuild(out):
    decisions = sorted(
        (json.loads(p.read_text()) for p in (out / "decisions").glob("*.json")),
        key=lambda d: (d["decided_at"], d["report_id"]),
    )
    groups = {"correction": [], "rejected": [], "owner_queue": []}
    for d in decisions:
        groups[d["outcome"]].append(d)
    (out / "corrections.jsonl").write_bytes(
        ledger.dump(corrections(groups["correction"]))
    )
    lines = {
        "owner-queue.jsonl": [
            {
                "report_id": d["report_id"],
                "reason": d["reason"],
                "report": d["report"],
                "readings": d.get("readings"),
            }
            for d in groups["owner_queue"]
        ],
    }
    for name, rows in lines.items():
        (out / name).write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
        )
    return {k: len(v) for k, v in groups.items()}


def reports_store(a):
    if a.reports:
        from cookbook.storage import LocalStore

        return LocalStore(a.reports)
    from cookbook.hosted import s3_store

    names = (
        "REPORTS_S3_ENDPOINT_URL",
        "REPORTS_S3_BUCKET",
        "REPORTS_AWS_ACCESS_KEY_ID",
        "REPORTS_AWS_SECRET_ACCESS_KEY",
    )
    if any(not os.environ.get(n) for n in names):
        sys.exit(
            "--reports-s3 needs " + ", ".join(names) + " (the Mac's own reports key)"
        )
    return s3_store(*(os.environ[n] for n in names))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--reports", type=Path, help="a local reports store directory")
    src.add_argument(
        "--reports-s3",
        action="store_true",
        help="the reports bucket, from REPORTS_* env",
    )
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--reader", default=READER)
    ap.add_argument("--publication", help="only reports against this publication id")
    ap.add_argument(
        "--limit", type=int, default=20, help="at most this many new decisions per run"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="list pending reports; no crops or model calls",
    )
    a = ap.parse_args()
    rd.parse(a.reader)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "decisions").mkdir(exist_ok=True)
    (a.out / "empty").mkdir(exist_ok=True)  # the reader CLIs run in an empty cwd
    pending = [
        r
        for r in list_reports(reports_store(a), a.publication)
        if not (a.out / "decisions" / f"{r['report_id']}.json").exists()
    ][: a.limit]
    if a.dry_run:
        for r in pending:
            print(
                json.dumps(
                    {
                        k: r[k]
                        for k in (
                            "report_id",
                            "book_id",
                            "physical_page",
                            "kind",
                            "region",
                        )
                    }
                )
            )
        print(json.dumps({"pending": len(pending)}))
        return
    if pending:
        doctor()
        books = registered_books()
    for r in pending:
        d = triage(r, a.out, books=books, reader=a.reader)
        if rd.STOP.is_set() or unsettled(d):
            print(
                json.dumps(
                    {
                        "report_id": r["report_id"],
                        "outcome": "retry later",
                        "reason": d["reason"],
                    }
                )
            )
            if rd.STOP.is_set():
                break
            continue
        (a.out / "decisions" / f"{r['report_id']}.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=1)
        )
        print(
            json.dumps(
                {
                    "report_id": r["report_id"],
                    "outcome": d["outcome"],
                    "reason": d["reason"],
                }
            ),
            flush=True,
        )
    print(json.dumps({"decided": len(pending), "totals": rebuild(a.out)}))


if __name__ == "__main__":
    main()
