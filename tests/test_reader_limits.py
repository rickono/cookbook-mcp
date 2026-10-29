"""Provider limits stop the actual reader/label path without more calls."""

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts/reader_bench"))

import assemble
import readers


@pytest.mark.parametrize(
    "error",
    [
        "You've hit your session limit · resets 12:30pm (America/Chicago)",
        "usage limit reached",
        "rate limit reached",
    ],
)
def test_provider_limit_stops_reader_and_label_without_retry(
    tmp_path, monkeypatch, error
):
    calls = []

    def backend(*args):
        calls.append(args)
        return "", None, None, error

    monkeypatch.setattr(readers, "STOP", threading.Event())
    monkeypatch.setitem(readers.BACKENDS, "claude", backend)
    monkeypatch.setattr(readers.time, "sleep", lambda seconds: None)
    text, record = readers.call(tmp_path, "haiku#1", "Synthetic label prompt", None)
    assert text is None and readers.STOP.is_set()
    assert len(calls) == 1 and error in record["errors"]
    assert (
        assemble.label_page(
            "haiku#1", tmp_path, {1: {"final_text": "Synthetic heading"}}, 1, tmp_path
        )
        is None
    )
    assert len(calls) == 1 and not (tmp_path / "p001.json").exists()


def test_authored_session_limit_words_are_not_a_provider_error(tmp_path, monkeypatch):
    text = "A synthetic chapter discusses session limits.\n2 synthetic items"
    monkeypatch.setattr(readers, "STOP", threading.Event())
    monkeypatch.setitem(
        readers.BACKENDS, "claude", lambda *args: (text, None, None, None)
    )
    result, record = readers.call(tmp_path, "haiku#1", "Synthetic prompt", None)
    assert result == text and record["errors"] == [] and not readers.STOP.is_set()
