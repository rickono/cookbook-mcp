"""Synthetic checks of report triage: blind ballots, decisions and outputs; no crops or models."""

import importlib.util
import json
from pathlib import Path

import pytest

from cookbook.recovery import RecoveryLedger

spec = importlib.util.spec_from_file_location(
    "triage_reports", Path(__file__).parents[1] / "scripts/triage_reports.py"
)
triage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)


@pytest.mark.parametrize(
    ("reading", "current", "proposed", "vote"),
    [
        ("Salt\n12 g fine salt", "2 g fine salt", "12 g fine salt", "proposed"),
        ("Salt\n2 g fine salt", "2 g fine salt", "12 g fine salt", "current"),
        ("1½ cups lentils", "1 cup lentils", "1 1/2 cups lentils", "proposed"),
        ("1 ⅓ cups flour", "1⅓ cups flour", "1½ cups flour", "current"),
        ("3 g salt", "2 g salt", "12 g salt", None),
        # The current quote sits inside the proposed text: still a vote for the proposal.
        ("1 cup sugar, sifted", "cup sugar", "1 cup sugar", "proposed"),
        # Both readings appear separately on the crop: ambiguous, no vote.
        ("2 tsp salt\n2 tbsp salt", "2 tsp salt", "2 tbsp salt", None),
        (None, "2 tsp salt", "2 tbsp salt", None),
    ],
)
def test_ballot(reading, current, proposed, vote):
    assert triage.ballot(reading, current, proposed) == vote


REPORT = {
    "report_id": "a" * 64,
    "publication_id": "pub",
    "book_id": "book-1",
    "source_id": "pdf:" + "b" * 64,
    "source_sha256": "b" * 64,
    "format": "PDF",
    "physical_page": 12,
    "section_id": None,
    "kind": "quantity",
    "quoted_text": "2 tsp salt",
    "proposed_text": "2 tbsp salt",
    "region": [0, 0.3, 1, 0.6],
}


def run(tmp_path, readings, report=REPORT, crop=None, errors=None):
    seen = []

    def fake_crop(out, book, page, sha, box, n):
        seen.append((book, page, sha, box))
        return crop or {"image": "/tmp/crop.png", "sha256": "c" * 64, "long_edge": 4000}

    replies = iter(readings)

    def fake_call(out, reader, prompt, image):
        seen.append(prompt)
        text = next(replies)
        return text, {
            "model": reader,
            "errors": [] if text else (errors or ["timeout 300s"]),
        }

    d = triage.triage(
        report,
        tmp_path,
        books={"b" * 64: 18},
        crop=fake_crop,
        call=fake_call,
        ledger=RecoveryLedger(tmp_path / "recovery.sqlite3"),
    )
    return d, seen


def test_blind_majority_corrects(tmp_path):
    d, seen = run(tmp_path, ["2 tbsp salt", "2 tbsp salt", "2 tsp salt"])
    assert d["outcome"] == "correction"
    assert seen[0] == (18, 12, "b" * 64, [0, 0.3, 1, 0.6])
    # The reader is never shown the claim it is checking.
    for prompt in seen[1:]:
        assert prompt == triage.fp.CROP_PROMPT and "tbsp" not in prompt
    (tmp_path / "decisions").mkdir()
    (tmp_path / "decisions" / "x.json").write_text(json.dumps(d))
    assert triage.rebuild(tmp_path) == {
        "correction": 1,
        "rejected": 0,
        "owner_queue": 0,
    }
    [c] = [
        json.loads(x) for x in (tmp_path / "corrections.jsonl").read_text().splitlines()
    ]
    assert (c["from_text"], c["to_text"], c["state"]) == (
        "2 tsp salt",
        "2 tbsp salt",
        "source_reviewed",
    )
    assert c["reviewer"] == {
        "kind": "agent",
        "id": "blind-reread:claude:claude-haiku-5-5 x3",
    }


def test_blind_majority_rejects(tmp_path):
    d, _ = run(tmp_path, ["2 tsp salt", "2 tsp salt", "2 tbsp salt"])
    assert d["outcome"] == "rejected" and not triage.unsettled(d)


def test_a_failed_reading_counts_against_and_is_retried(tmp_path):
    d, _ = run(tmp_path, ["2 tbsp salt", None, "2 tsp salt"])
    assert d["outcome"] == "owner_queue" and triage.unsettled(d)
    # A provider filter refusal is a result, not something to retry around.
    d, _ = run(
        tmp_path,
        ["2 tbsp salt", None, "2 tsp salt"],
        errors=["API Error: Output blocked by content filtering policy"],
    )
    assert d["outcome"] == "owner_queue" and not triage.unsettled(d)


def test_whole_page_read_without_region(tmp_path):
    d, seen = run(
        tmp_path, ["…\n2 tbsp salt\n…"] * 3, report={**REPORT, "region": None}
    )
    assert seen[0][3] == [0.0, 0.0, 1.0, 1.0] and seen[1] == triage.fp.PAGE_PROMPT
    assert d["outcome"] == "correction" and d["prompt"] == "page"


def test_unregistered_or_failed_crop_goes_to_owner(tmp_path):
    d, seen = run(tmp_path, [], report={**REPORT, "source_sha256": "f" * 64})
    assert d["outcome"] == "owner_queue" and seen == [] and not triage.unsettled(d)
    d, _ = run(tmp_path, [], crop={"error": "PDF helper refused"})
    assert d["outcome"] == "owner_queue" and triage.unsettled(d)


def test_recovery_budget_survives_worker_restart_and_split_regions(tmp_path):
    # Initial predefined three-read route is separate from two additional routes.
    for worker in ("one", "two", "three"):
        d, _ = run(tmp_path, [None] * 3)
        assert (
            d["recovery"]["region_remaining"]
            == {"one": 2, "two": 1, "three": 0}[worker]
        )
        assert d["review_status"] == "technical_failure"
    split = {**REPORT, "report_id": "e" * 64, "region": [0, 0.3, 0.5, 0.45]}
    d, seen = run(tmp_path, [], report=split)
    assert d["review_status"] == "budget_exhausted"
    assert seen == []
    assert len(d["recovery"]["attempts"]) == 3
    assert d["recovery"]["page_remaining"] == 4


def test_terminal_refusal_stops_samples_and_source_replacement(tmp_path):
    d, seen = run(tmp_path, [None], errors=["refusal: cannot transcribe this source"])
    assert d["review_status"] == "terminal_unavailable"
    assert not triage.unsettled(d)
    assert len(seen) == 2  # crop and one reader dispatch
    replacement = {**REPORT, "source_sha256": "c" * 64, "region": None}
    d, seen = run(tmp_path, [], report=replacement)
    assert d["review_status"] == "terminal_unavailable" and seen == []
    assert d["recovery"]["terminal_attempts"][0]["source"] == "b" * 64


def test_interrupted_attempt_is_charged_and_inspectable_after_restart(tmp_path):
    def interrupt(*args):
        raise KeyboardInterrupt("synthetic worker cancellation")

    with pytest.raises(KeyboardInterrupt):
        triage.triage(
            REPORT,
            tmp_path,
            books={"b" * 64: 18},
            crop=interrupt,
            ledger=RecoveryLedger(tmp_path / "recovery.sqlite3"),
        )
    d, _ = run(tmp_path, ["illegible"] * 3)
    assert d["review_status"] == "content_uncertain"
    assert d["recovery"]["region_remaining"] == 1
    first = d["recovery"]["attempts"][0]
    assert first["events"][-1]["status"] == "interrupted"
    assert first["route"] == "initial"
    assert first["inputs"] == REPORT


def test_shared_page_limit_and_concurrent_workers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from cookbook.recovery import RecoveryLedger

    ledger_path = tmp_path / "owner.sqlite3"

    def request(region, worker):
        # Separate output runs and reader/actor identities share one owner ledger.
        return triage.triage(
            {**REPORT, "region": region},
            tmp_path,
            books={"b" * 64: 18},
            reader=f"synthetic:{worker}",
            actor={"kind": "agent", "id": worker},
            ledger=RecoveryLedger(ledger_path),
            crop=lambda *a: {"image": "synthetic", "sha256": "c" * 64},
            call=lambda *a: (None, {"errors": ["timeout 300s"]}),
        )

    for n in range(3):
        box = [0, n * 0.3, 1, n * 0.3 + 0.2]
        request(box, "initial")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(lambda w, box=box: request(box, w), ["a", "b", "c", "d"])
            )
        assert sum(r["review_status"] == "budget_exhausted" for r in results) == 2
    # A fourth region has an initial route, but no additional page allowance.
    box = [0, 0.92, 1, 1]
    request(box, "initial")
    refused = request(box, "new-reader")
    assert refused["review_status"] == "budget_exhausted"
    assert refused["recovery"]["page_remaining"] == 0
    assert len(refused["recovery"]["attempts"]) == 10
    assert {a["actor"]["id"] for a in refused["recovery"]["attempts"]} >= {
        "initial",
        "a",
    }


def test_timeout_is_retained_and_success_is_review_without_approval(tmp_path):
    def timeout(*args):
        raise TimeoutError("synthetic timeout")

    d = triage.triage(
        REPORT,
        tmp_path,
        books={"b" * 64: 18},
        crop=timeout,
        ledger=RecoveryLedger(tmp_path / "recovery.sqlite3"),
    )
    assert d["review_status"] == "timeout" and triage.unsettled(d)
    d, _ = run(tmp_path, ["2 tbsp salt"] * 3)
    assert d["outcome"] == "correction" and d["review_status"] == "review_completed"
    assert d["recovery"]["region_remaining"] == 1
    events = d["recovery"]["attempts"][-1]["events"]
    assert [e["event"] for e in events] == [
        "extraction",
        "review",
        "review",
        "review",
        "outcome",
    ]
    assert triage.correction(d)["state"] == "source_reviewed"


def test_unrecoverable_source_stops_before_reader_and_stays_terminal(tmp_path):
    d, seen = run(
        tmp_path,
        [],
        crop={"unavailable": True, "reason": "scan has no recoverable marks"},
    )
    assert d["review_status"] == "terminal_unavailable"
    assert len(seen) == 1
    d, seen = run(tmp_path, [])
    assert d["review_status"] == "terminal_unavailable" and seen == []


def test_killed_worker_leaves_durable_dispatch_without_claiming_review(tmp_path):
    import subprocess
    import sys

    script = f"""
import importlib.util, os
from pathlib import Path
spec = importlib.util.spec_from_file_location("triage", "scripts/triage_reports.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.triage({REPORT!r}, Path({str(tmp_path)!r}), books={{"b" * 64: 18}},
         crop=lambda *a: os._exit(17),
         ledger=m.RecoveryLedger(Path({str(tmp_path)!r}) / "recovery.sqlite3"))
"""
    proc = subprocess.run([sys.executable, "-c", script], check=False)
    assert proc.returncode == 17
    d, _ = run(tmp_path, ["unreadable"] * 3)
    first = d["recovery"]["attempts"][0]
    assert first["dispatch_status"] == "unfinished"
    assert first["events"] == []
    assert d["recovery"]["region_remaining"] == 1


def test_admin_dry_run_exposes_shared_history_without_processing(tmp_path):
    import subprocess
    import sys

    from cookbook.reports import VERSION, report_id
    from cookbook.storage import LocalStore

    run(tmp_path, [None] * 3)
    report = {**REPORT, "version": VERSION, "created_at": "2026-10-28T00:00:00Z"}
    report["report_id"] = report_id(report)
    store = LocalStore(tmp_path / "reports")
    store.put_bytes("reports/pub/report.json", json.dumps(report).encode())
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/triage_reports.py",
            "--reports",
            str(tmp_path / "reports"),
            "--out",
            str(tmp_path / "other-run"),
            "--ledger",
            str(tmp_path / "recovery.sqlite3"),
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    status = json.loads(proc.stdout.splitlines()[0])["recovery"]
    assert status["region_remaining"] == 2
    assert status["attempts"][0]["events"][-1]["status"] == "technical_failure"
