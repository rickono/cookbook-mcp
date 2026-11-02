#!/usr/bin/env python3
"""Refresh the library from agent reports: triage, regenerate the ledger, republish (Mac only).

Run by hand; nothing schedules it. One run:

  1. reads the stored transcription reports (a local reports store, or the reports
     bucket with the Mac's own reports key) and finds those without a decision;
  2. if any are pending, runs the OCR sandbox admission check (scripts/ocr_sandbox.py
     doctor) and stops before triage if it fails;
  3. blind-triages up to --limit of them (scripts/triage_reports.py). A failed crop or a
     timed-out reading leaves its report pending, a usage or rate limit leaves it pending
     and ends triage, and a content-filter refusal goes to the owner queue as it is;
  4. regenerates the correction ledger (ledger.jsonl) from every decision;
  5. if the ledger changes what the active publication serves, rebuilds it from the
     snapshot, approved selection and candidate set that publication recorded, with the
     new ledger (src/cookbook/refresh.py);
  6. publishes and activates the rebuild through the existing lifecycle, then prints the
     build report: applied, stale and ambiguous corrections and new owner-queue items.

The owner queue is --out/owner-queue.md: each report the re-read did not settle, and
each accepted correction the build could not place, with its report, readings and
reason. A failed build or publish leaves the active publication unchanged; earlier
publications are kept. Publishing uses the Mac's publisher credential, which never goes
to Fly.

  uv run python scripts/refresh_library.py --reports DIR --store DIR --runtime DIR
  uv run python scripts/refresh_library.py --reports-s3 --s3 --state-directory DIR \\
      --readiness-url https://HOST/readyz --browser-login
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import triage_reports as tr

from cookbook import ledger
from cookbook.refresh import RefreshError, republish
from cookbook.storage import canonical, file_lock

DATA = Path(os.environ.get("COOKBOOK_DATA", Path.home() / "cookbook-mcp-data"))


def _keys(out):
    return {item["key"] for item in tr.owner_items(out)} if out.exists() else set()


def refresh(
    reports,
    out: Path,
    *,
    store,
    activate,
    work: Path,
    ocr_cache=None,
    log=print,
    **triage_options,
):
    """One refresh run; the caller holds the publisher lock. Returns its JSON summary.

    ``triage_options`` (limit, reader, and the injectable admission, books, crop and
    call) go to triage_reports.run unchanged; its defaults apply.
    """
    before = _keys(out)
    triage = tr.run(reports, out, log=log, **triage_options)
    rows = ledger.read(out / ledger.FILE)
    published = republish(
        store,
        rows,
        work,
        activate=activate,
        ocr_cache=ocr_cache,
        progress=lambda event: log(json.dumps(event)),
    )
    report = published.get("build_report") or {}
    if published["status"] == "active":
        # The owner queue follows what the newly active publication could not place.
        (out / tr.AMBIGUOUS).write_bytes(
            b"".join(canonical(q) + b"\n" for q in report.get("owner_queue", []))
        )
    (out / "owner-queue.md").write_text(tr.owner_queue_page(out))
    after = _keys(out)
    status = {"active": "published"}.get(published["status"], published["status"])
    return {
        "status": status,
        "publication_id": published["publication_id"],
        "previous_publication_id": published.get("previous_publication_id"),
        "triage": triage,
        "corrections": report.get("corrections"),
        "owner_queue": {
            "new": len(after - before),
            "total": len(after),
            "file": str(out / "owner-queue.md"),
        },
        "build": published.get("build"),
    }


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
    ap.add_argument("--out", type=Path, default=tr.OUT, help="triage decisions")
    ap.add_argument("--work", type=Path, default=DATA / "refresh", help="rebuilds")
    ap.add_argument("--limit", type=int, default=20, help="most new decisions per run")
    ap.add_argument("--reader", default=tr.READER)
    ap.add_argument(
        "--ledger",
        type=Path,
        default=DATA / "recovery.sqlite3",
        help="shared owner-wide recovery ledger",
    )
    ap.add_argument("--actor", default="report-triage")
    ap.add_argument(
        "--ocr-cache", type=Path, help="default: the one the active build recorded"
    )
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--store", type=Path, help="a local publication store")
    target.add_argument(
        "--s3",
        action="store_true",
        help="the hosted library bucket (publish-s3's S3_*/AWS_* env)",
    )
    ap.add_argument("--runtime", type=Path, help="local runtime (with --store)")
    ap.add_argument("--state-directory", type=Path, help="publisher state (with --s3)")
    ap.add_argument("--readiness-url", help="hosted /readyz (with --s3)")
    auth = ap.add_mutually_exclusive_group()
    auth.add_argument("--token-file", type=Path)
    auth.add_argument("--browser-login", action="store_true")
    a = ap.parse_args()
    os.umask(0o077)
    tr.rd.parse(a.reader)
    if a.store:
        if not a.runtime:
            ap.error("--store needs --runtime")
        from cookbook.publication import Runtime
        from cookbook.storage import LocalStore

        store = LocalStore(a.store)
        activate = Runtime(store, a.runtime).activate
        lock = a.store / ".publisher.lock"
    else:
        if not (a.state_directory and a.readiness_url):
            ap.error("--s3 needs --state-directory and --readiness-url")
        if not (a.token_file or a.browser_login):
            ap.error("--s3 needs --token-file or --browser-login")
        from cookbook.cli import hosted_activator, recording
        from cookbook.hosted import store_from_environment

        store = store_from_environment()
        activate = recording(
            a.state_directory,
            hosted_activator(
                a.readiness_url, token_file=a.token_file, browser_login=a.browser_login
            ),
        )
        a.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = a.state_directory / ".publisher.lock"
    with file_lock(lock):
        try:
            result = refresh(
                tr.reports_store(a),
                a.out,
                store=store,
                activate=activate,
                work=a.work,
                limit=a.limit,
                reader=a.reader,
                ocr_cache=a.ocr_cache,
                ledger=tr.RecoveryLedger(a.ledger),
                actor={"kind": "agent", "id": a.actor},
                log=lambda line: print(line, flush=True),
            )
        except RefreshError as error:
            sys.exit(json.dumps({"error": "refresh_refused", "message": str(error)}))
    print(json.dumps(result))
    if result["status"] == "pending_activation":
        raise SystemExit(4)


if __name__ == "__main__":
    main()
