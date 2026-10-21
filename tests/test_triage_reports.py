"""Synthetic checks of report triage: blind ballots, decisions and outputs; no crops or models."""

import importlib.util
import json
from pathlib import Path

import pytest

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
        report, tmp_path, books={"b" * 64: 18}, crop=fake_crop, call=fake_call
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
    [c] = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert (c["from_text"], c["to_text"], c["state"]) == (
        "2 tsp salt",
        "2 tbsp salt",
        "source_reviewed",
    )
    assert c["reviewer"] == {
        "kind": "agent",
        "id": "blind-reread:claude:claude-haiku-5-5 x3",
    }


def decided(tmp_path, name, at, **report):
    d, _ = run(tmp_path, ["2 tbsp salt"] * 3, report=REPORT | report)
    d["decided_at"] = at
    (tmp_path / "decisions").mkdir(exist_ok=True)
    (tmp_path / "decisions" / f"{name}.json").write_text(json.dumps(d))
    return d


def test_ledger_is_in_decision_order_and_binds_to_source_and_page(tmp_path):
    from cookbook import ledger

    # File names sort against decision time; the ledger must not follow them.
    decided(tmp_path, "a", "2026-10-20T10:00:02Z", report_id="1" * 64, physical_page=13)
    decided(tmp_path, "b", "2026-10-20T10:00:01Z", report_id="2" * 64)
    # The same correction, reported again against a later publication: kept once, earliest.
    decided(
        tmp_path, "c", "2026-10-20T10:00:03Z", report_id="3" * 64, publication_id="new"
    )
    assert triage.rebuild(tmp_path)["correction"] == 3
    rows = ledger.read(tmp_path / "ledger.jsonl")
    assert [(r["id"], r["decided_at"]) for r in rows] == [
        ("2" * 64, "2026-10-20T10:00:01Z"),
        ("1" * 64, "2026-10-20T10:00:02Z"),
    ]
    assert [(r["source_sha256"], r["physical_page"]) for r in rows] == [
        ("b" * 64, 12),
        ("b" * 64, 13),
    ]
    assert rows[0]["publication_id"] == "pub"
    # The row id is the report id; the row does not repeat it.
    assert "report_id" not in rows[0]


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
