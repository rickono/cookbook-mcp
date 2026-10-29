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
All dispatched routes, failures and interruptions also remain in the shared --ledger.
corrections.jsonl and owner-queue.jsonl are rebuilt from the decisions on every run;
the next scanned-book publication applies corrections.jsonl. The library itself is not
touched here, and nothing is uploaded: reports are only read.

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

from cookbook.recovery import RecoveryLedger
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


def _triage(report, out, *, books, reader, crop, call, ledger, attempt):
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
    if image.get("unavailable") is True:
        return {
            **base,
            "outcome": "owner_queue",
            "review_status": "terminal_unavailable",
            "reason": image.get("reason", "source cannot support recovery"),
            "crop": image,
        }
    if "image" not in image:
        return {
            **base,
            "outcome": "owner_queue",
            "reason": "guarded crop failed",
            "crop": image,
        }
    ledger.record(
        attempt,
        "extraction",
        purpose="initial source extraction or recovery crop",
        output=image,
    )
    prompt = fp.CROP_PROMPT if report["region"] else fp.PAGE_PROMPT
    readings, calls = [], []
    for k in range(1, SAMPLES + 1):
        text, c = call(out, f"{reader}#{k}", prompt, image["image"])
        readings.append(text)
        calls.append(c)
        ledger.record(attempt, "review", sample=k, output={"text": text, "call": c})
        if text is None and (
            rd.filtered(c) or any("refusal:" in e for e in c.get("errors", []))
        ):
            return {
                **base,
                "outcome": "owner_queue",
                "reason": "terminal reader refusal",
                "review_status": "terminal_unavailable",
                "readings": readings,
                "calls": calls,
            }
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


def triage(
    report,
    out,
    *,
    books,
    reader=READER,
    crop=fp.guarded_crop,
    call=rd.call,
    ledger=None,
    actor=None,
):
    """Administrative recovery boundary; injected crop/readers permit synthetic checks.

    Production uses one owner-wide ledger independent of --out. A predefined route
    contains the existing three blind samples; further routes consume recovery budget.
    """
    ledger = ledger or RecoveryLedger(DATA / "recovery.sqlite3")
    scope = {
        "source": report["source_sha256"],
        "page": report["physical_page"],
        "box": report["region"] or [0, 0, 1, 1],
        "book": report["book_id"],
    }
    attempt, refused = ledger.admit(
        **scope,
        actor=actor or {"kind": "agent", "id": reader},
        tool=reader,
        configuration={
            "samples": SAMPLES,
            "needed": NEEDED,
            "prompt": fp.CROP_PROMPT if report["region"] else fp.PAGE_PROMPT,
        },
        inputs=report,
        purpose="blind report review",
    )
    if refused:
        return {
            "report_id": report["report_id"],
            "report": report,
            "outcome": "owner_queue",
            "reason": refused,
            "review_status": refused,
            "recovery": ledger.status(**scope),
        }
    try:
        result = _triage(
            report,
            out,
            books=books,
            reader=reader,
            crop=crop,
            call=call,
            ledger=ledger,
            attempt=attempt,
        )
        status = result.get("review_status") or (
            "technical_failure"
            if unsettled(result)
            else "content_uncertain"
            if result["outcome"] == "owner_queue"
            else "review_completed"
        )
    except BaseException as exc:
        status = (
            "interrupted"
            if not isinstance(exc, Exception)
            else (
                "timeout"
                if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired))
                else "technical_failure"
            )
        )
        ledger.record(attempt, "outcome", status=status, reason=repr(exc))
        if not isinstance(exc, Exception):
            raise
        result = {
            "report_id": report["report_id"],
            "report": report,
            "outcome": "owner_queue",
            "reason": repr(exc),
        }
    else:
        ledger.record(attempt, "outcome", status=status, evidence=result)
    return {**result, "review_status": status, "recovery": ledger.status(**scope)}


def unsettled(d):
    """A technical failure may be retried within the durable recovery allowance.

    A provider filter refusal is a real result: it is never retried or worked around.
    """
    if d.get("review_status") in {"terminal_unavailable", "budget_exhausted"}:
        return False
    if d.get("review_status") in {"technical_failure", "timeout", "interrupted"}:
        return True
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


def rebuild(out):
    decisions = [
        json.loads(p.read_text()) for p in sorted((out / "decisions").glob("*.json"))
    ]
    groups = {"correction": [], "rejected": [], "owner_queue": []}
    for d in decisions:
        groups[d["outcome"]].append(d)
    lines = {
        "corrections.jsonl": [correction(d) for d in groups["correction"]],
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
    ap.add_argument(
        "--ledger",
        type=Path,
        default=DATA / "recovery.sqlite3",
        help="shared owner-wide recovery ledger; retain across output directories",
    )
    ap.add_argument("--actor", default="report-triage")
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
        ledger = RecoveryLedger(a.ledger)
        for r in pending:
            print(
                json.dumps(
                    {
                        **{
                            k: r[k]
                            for k in (
                                "report_id",
                                "book_id",
                                "physical_page",
                                "kind",
                                "region",
                            )
                        },
                        "recovery": ledger.status(
                            source=r["source_sha256"],
                            page=r["physical_page"],
                            box=r["region"] or [0, 0, 1, 1],
                            book=r["book_id"],
                        ),
                    }
                )
            )
        print(json.dumps({"pending": len(pending)}))
        return
    if pending:
        doctor()
        books = registered_books()
    for r in pending:
        d = triage(
            r,
            a.out,
            books=books,
            reader=a.reader,
            ledger=RecoveryLedger(a.ledger),
            actor={"kind": "agent", "id": a.actor},
        )
        if rd.STOP.is_set() or unsettled(d):
            print(
                json.dumps(
                    {
                        "report_id": r["report_id"],
                        "outcome": "retry later",
                        "reason": d["reason"],
                        "recovery": d["recovery"],
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
                    "review_status": d["review_status"],
                    "recovery": d["recovery"],
                }
            ),
            flush=True,
        )
    print(json.dumps({"decided": len(pending), "totals": rebuild(a.out)}))


if __name__ == "__main__":
    main()
