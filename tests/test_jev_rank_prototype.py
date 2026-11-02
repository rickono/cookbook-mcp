"""Synthetic hosted-call scheduling checks; no books, OCR or inference."""

import importlib.util
import threading
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "jev_rank_prototype",
    Path(__file__).parents[1] / "src/cookbook/jev_rank.prototype.py",
)
prototype = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prototype)


class SyntheticCorpus:
    def retrieve(self, *_args):
        return {
            "items": [
                {
                    "id": str(i),
                    "title": f"Synthetic candidate {i}",
                    "book": "Synthetic book",
                    "kind": "recipe",
                    "source_state": "supported",
                    "supporting_work_state": "reviewed",
                    "uninterpreted_images": 0,
                    "citations": [],
                    "text": "Synthetic text",
                }
                for i in range(8)
            ],
            "terms": ["synthetic"],
            "note": "Synthetic retrieval",
        }


def complete(experiment, ident):
    deadline = time.monotonic() + 3
    while experiment.active and time.monotonic() < deadline:
        time.sleep(0.005)
    assert experiment.active is None
    return experiment.jobs[ident]


def answer(payload):
    index = int(payload["state"]["candidate"]["id"])
    value = index % 5
    return {
        "model": prototype.MODEL,
        "answers": {
            "fit": {
                "type": "score",
                "score": value,
                "confidence": 1,
                "probabilities": {str(i): int(i == value) for i in range(5)},
            }
        },
        "usage": {"input_tokens": 10},
    }, False


def test_independent_calls_overlap_with_a_bounded_pool(tmp_path):
    experiment = prototype.Experiment(SyntheticCorpus(), tmp_path, True)
    lock = threading.Lock()
    active = peak = 0
    seen = []

    def delayed(payload):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            seen.append(payload["state"]["candidate"]["id"])
        try:
            time.sleep(0.04)
            return answer(payload)
        finally:
            with lock:
                active -= 1

    experiment.call = delayed
    job = complete(
        experiment, experiment.start({"query": "synthetic", "mode": "score"})
    )
    assert peak == 4
    assert sorted(seen) == list(map(str, range(8)))
    assert job["state"] == "done"
    assert job["completed"] == 8
    assert job["input_tokens"] == 80
    assert [row["value"] for row in job["results"]] == [4, 3, 2, 2, 1, 1, 0, 0]


def test_cancel_does_not_schedule_beyond_current_calls(tmp_path):
    experiment = prototype.Experiment(SyntheticCorpus(), tmp_path, True)
    release = threading.Event()
    full = threading.Event()
    lock = threading.Lock()
    started = []

    def blocked(payload):
        with lock:
            started.append(payload["state"]["candidate"]["id"])
            if len(started) == 4:
                full.set()
        assert release.wait(2)
        return answer(payload)

    experiment.call = blocked
    ident = experiment.start({"query": "synthetic", "mode": "score"})
    try:
        assert full.wait(1)
        with experiment.lock:
            experiment.jobs[ident]["cancelled"] = True
    finally:
        release.set()
    job = complete(experiment, ident)
    assert len(started) == 4
    assert job["completed"] == 4
    assert job["state"] == "cancelled"


def test_candidate_failure_retains_other_results(tmp_path):
    experiment = prototype.Experiment(SyntheticCorpus(), tmp_path, True)

    def sometimes_fails(payload):
        if payload["state"]["candidate"]["id"] == "2":
            raise ValueError("Synthetic oversized package")
        return answer(payload)

    experiment.call = sometimes_fails
    job = complete(
        experiment, experiment.start({"query": "synthetic", "mode": "score"})
    )
    assert job["state"] == "partial"
    assert job["completed"] == 8
    assert len(job["results"]) == 7
    assert job["errors"] == ["Synthetic candidate 2: Synthetic oversized package"]


def test_hosted_disabled_never_calls_inference(tmp_path):
    experiment = prototype.Experiment(SyntheticCorpus(), tmp_path, False)

    def forbidden(_payload):
        pytest.fail("Hosted call admitted without authorization")

    experiment.call = forbidden
    job = complete(experiment, experiment.start({"query": "synthetic"}))
    assert job["state"] == "prepared"
    assert not job["results"]
