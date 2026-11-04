"""Source-free regression checks for the private browser-trial summarizer."""

import runpy
from pathlib import Path

import pytest

summarize = runpy.run_path(
    str(
        Path(__file__).resolve().parents[1] / "scripts/summarize_reader_search_trial.py"
    )
)["summarize"]


def samples():
    return [
        {
            "case": case,
            "round": round,
            "side": side,
            "finished": True,
            "failedGroups": 0,
            "ms": round + 1,
            "resultHash": "synthetic-result",
            "domHash": "synthetic-dom",
            "requests": [
                {"path": "/reader/search/results", "status": 200, "monitor": False}
            ],
        }
        for case in range(5)
        for round in range(5)
        for side in ("baseline", "candidate")
    ]


@pytest.mark.parametrize("digest", [None, ""])
def test_missing_dom_digests_never_establish_equality(digest):
    trials = samples()
    for trial in trials:
        trial["domHash"] = digest
    assert all(not row["identical_dom"] for row in summarize(trials))


def test_complete_digests_and_request_outcomes_are_reported_separately():
    trials = samples()
    trials[0]["requests"].append(
        {"path": "/reader/session", "status": 503, "monitor": True}
    )
    row = summarize(trials)[0]
    assert row["identical_dom"] and row["identical_results"]
    assert row["baseline"]["successful"] == 5
    assert row["baseline"]["median_ms"] == 3
    assert row["baseline"]["monitor_http_errors"] == 1
    assert row["baseline"]["action_http_errors"] == 0
    trials[0]["domHash"] = "different-dom"
    assert summarize(trials)[0]["identical_dom"] is False


def test_unfinished_request_requires_reconciliation():
    trials = samples()
    trials[0]["requests"].append(
        {"path": "/reader/session", "status": None, "monitor": True}
    )
    with pytest.raises(ValueError, match="Reconcile unfinished requests"):
        summarize(trials)


def test_network_failure_without_http_status_is_counted():
    trials = samples()
    trials[0]["finished"] = False
    trials[0]["requests"][0].update(status=None, error="TimeoutError")
    row = summarize(trials)[0]["baseline"]
    assert row["successful"] == 4
    assert row["action_http_errors"] == 1
