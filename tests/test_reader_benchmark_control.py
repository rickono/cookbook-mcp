"""Offline cleanup checks; never connects to Fly or R2."""

import json
import signal
import subprocess
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


@pytest.mark.parametrize("interruption", [signal.SIGHUP, signal.SIGTERM])
def test_worker_signal_deletes_synthetic_objects(tmp_path, interruption):
    worker = (
        Path(__file__).resolve().parents[1] / "scripts/session_benchmark_r2_worker.py"
    )
    driver = tmp_path / "worker_driver.py"
    driver.write_text("""
import runpy, sys
from types import SimpleNamespace
import cookbook.hosted
class Store:
    def __init__(self):
        self.values = {}
        self.client = SimpleNamespace(close=lambda: None)
    def put_bytes(self,key,data,expected=None):
        self.values[key] = data
        return 'synthetic-version'
    def read_version(self,key):
        return self.values.get(key), 'synthetic-version' if key in self.values else None
    def delete(self,key):
        del self.values[key]
        print('deleted-synthetic-object',file=sys.stderr,flush=True)
store=Store()
cookbook.hosted.s3_store=lambda *args: store
sys.argv=[sys.argv[1], 'research/session-134/benchmark-offline-signal']
runpy.run_path(sys.argv[0], run_name='__main__')
""")
    import os

    env = {
        **os.environ,
        **{
            name: "synthetic"
            for name in [
                "READER_S3_ENDPOINT_URL",
                "READER_S3_BUCKET",
                "READER_AWS_ACCESS_KEY_ID",
                "READER_AWS_SECRET_ACCESS_KEY",
            ]
        },
    }
    process = subprocess.Popen(
        [sys.executable, "-u", str(driver), str(worker)],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert json.loads(process.stdout.readline())["ready"]
        process.stdin.write(
            json.dumps(
                {
                    "op": "put",
                    "key": "reader/owners/synthetic",
                    "data": "c3ludGhldGlj",
                    "expected": None,
                }
            )
            + "\n"
        )
        process.stdin.flush()
        assert json.loads(process.stdout.readline())["ok"]
        process.send_signal(interruption)
        stdout, stderr = process.communicate(timeout=10)
        assert json.loads(stdout)["cleanup_failures"] == 0
        assert "deleted-synthetic-object" in stderr
        assert process.returncode == 128 + interruption
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
