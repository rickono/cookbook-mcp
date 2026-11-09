"""Private diagnostic input must not escape through the research summary."""

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "summary", Path(__file__).parents[1] / "scripts/summarize_reader_sessions.py"
)
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


def test_private_payloads_and_failed_latencies_stay_out():
    secret = "PRIVATE-SENTINEL"
    event = {
        "event": "reader_request",
        "route": "/reader/session",
        "status": 200,
        "ms": 20,
        "request": secret,
        "payload": secret,
        "stages": {
            "session_read": {"ms": 19, "n": 1, "conflicts": 0},
            secret: {"ms": 1},
        },
    }
    failed = {**event, "status": 503, "ms": 9000}
    raw = (
        json.dumps({"message": json.dumps(event)}, indent=2)
        + json.dumps(failed)
        + json.dumps({**event, "route": secret})
    )
    result = summary.summarize(raw)
    assert secret not in json.dumps(result)
    group = result["/reader/session"]
    assert group["statuses"] == {"200": 1, "503": 1}
    assert group["successful_wall_ms"] == {"n": 1, "median": 20, "min": 20, "max": 20}
    assert group["stages_observed_on_success"]["session_read"]["ms"]["median"] == 19


def test_absent_and_invalid_stage_values_are_unknown():
    event = {
        "event": "reader_request",
        "route": "/reader/session",
        "status": 200,
        "ms": float("nan"),
        "stages": {"token_verify": {"ms": "PRIVATE", "n": True, "conflicts": -1}},
    }
    group = summary.summarize(json.dumps(event))["/reader/session"]
    assert group["successful_wall_ms"] is None
    assert group["stages_observed_on_success"]["token_verify"] == {
        "ms": None,
        "n": None,
        "conflicts": None,
    }
    assert "session_write" not in group["stages_observed_on_success"]
