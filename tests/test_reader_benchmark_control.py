"""Offline cleanup checks; never connects to Fly or R2."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("psycopg")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_reader_sessions import close_relays


def test_cleanup_attempts_every_worker_before_reporting_failure():
    closed = []

    class Worker:
        def __init__(self, name, fail=False):
            self.name, self.fail = name, fail

        def close(self):
            closed.append(self.name)
            if self.fail:
                raise OSError("synthetic failed cleanup")

    with pytest.raises(ExceptionGroup):
        close_relays([Worker("first", fail=True), Worker("second")])
    assert closed == ["first", "second"]
