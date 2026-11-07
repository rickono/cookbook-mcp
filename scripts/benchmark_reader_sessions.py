"""Opt-in live synthetic R2 versus local PostgreSQL reader comparison.

The R2 relay is timed separately. Raw R2 request time includes SSH overhead.
Never estimates hosted PostgreSQL latency or uses real identities/content.
"""

import argparse
import base64
import contextlib
import io
import json
import secrets
import selectors
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jwt
import psycopg
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from local_session_postgres import local_postgres
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import fixture_build
from test_reader_content import destination
from test_reader_http import login

from cookbook.hosted import create_hosted_app
from cookbook.publication import Runtime, publish
from cookbook.reader import Reader, ReaderConfig
from cookbook.server import JWTVerifier
from cookbook.storage import Conflict, LocalStore


class Relay:
    def __init__(self, app, prefix):
        script = base64.b64encode(
            (ROOT / "scripts/session_benchmark_r2_worker.py").read_bytes()
        ).decode()
        command = (
            "python -u -c \"import base64;exec(base64.b64decode('"
            + script
            + "'))\" "
            + prefix
        )
        self.process = subprocess.Popen(
            ["fly", "ssh", "console", "-a", app, "-q", "-C", command],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.lock = threading.Lock()
        try:
            self.ready = self.receive()
            assert self.ready.get("ready"), "Relay failed to start"
        except BaseException:
            self._stop()
            raise
        self.samples = []

    def receive(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            assert selector.select(40), "Relay timed out"
        line = self.process.stdout.readline()
        assert line, "Relay disconnected"
        return json.loads(line)

    def call(self, op, **fields):
        with self.lock:
            start = time.perf_counter()
            self.process.stdin.write(json.dumps({"op": op, **fields}) + "\n")
            self.process.stdin.flush()
            result = self.receive()
            self.samples.append(
                {
                    "op": op,
                    "rpc_ms": (time.perf_counter() - start) * 1000,
                    "worker_ms": result["worker_ms"],
                    "ok": result["ok"],
                }
            )
            if not result["ok"]:
                if result.get("conflict"):
                    raise Conflict("synthetic benchmark contention")
                raise OSError("synthetic R2 worker failed")
            return result

    def close(self):
        try:
            self.process.stdin.close()
            result = self.receive()
            assert result.get("cleanup_failures") == 0, "Synthetic R2 cleanup failed"
            self.process.wait(timeout=15)
            assert self.process.returncode == 0
        finally:
            self._stop()

    def _stop(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdout.close()


def close_relays(relays):
    failures = []
    for relay in relays:
        try:
            relay.close()
        except Exception as error:  # noqa: BLE001 - finish every independent cleanup before reporting failures
            failures.append(error)
    if failures:
        raise ExceptionGroup("Synthetic R2 cleanup failed", failures)


class RemoteOwnerStore:
    def __init__(self, local, relay):
        self.local, self.relay = local, relay

    def read_version(self, key):
        if not key.startswith("reader/owners/"):
            return self.local.read_version(key)
        r = self.relay.call("read", key=key)
        return (base64.b64decode(r["data"]) if r["data"] else None), r["version"]

    def put_bytes(self, key, data, *, expected=None):
        if not key.startswith("reader/owners/"):
            return self.local.put_bytes(key, data, expected=expected)
        return self.relay.call(
            "put", key=key, data=base64.b64encode(data).decode(), expected=expected
        )["version"]


def summary(values):
    return {
        "median": round(statistics.median(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-synthetic-writes", action="store_true")
    parser.add_argument("--fly-app", required=True)
    parser.add_argument("--postgres-bin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--journeys",
        nargs="+",
        choices=[
            "passive",
            "catalog",
            "search",
            "text",
            "original",
            "image",
            "two_tabs",
        ],
        default=[
            "passive",
            "catalog",
            "search",
            "text",
            "original",
            "image",
            "two_tabs",
        ],
    )
    args = parser.parse_args()
    if not args.live_synthetic_writes:
        parser.error("Requires --live-synthetic-writes")
    prefix = "research/session-134/benchmark-" + secrets.token_hex(16)
    relays = []
    results = []
    with (
        local_postgres(args.postgres_bin) as dsn,
        tempfile.TemporaryDirectory(prefix="reader-benchmark-") as folder,
        contextlib.ExitStack() as stack,
    ):
        root = Path(folder)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute((ROOT / "src/cookbook/reader_session_schema.sql").read_text())
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verifier = JWTVerifier(
            issuer="https://issuer.example/",
            audience="http://127.0.0.1:8765/mcp",
            subjects=["user-1"],
            public_key=private.public_key(),
        )
        now = time.time()
        token = jwt.encode(
            {
                "iss": verifier.issuer,
                "aud": verifier.audience,
                "sub": "user-1",
                "iat": int(now),
                "exp": int(now) + 3600,
                "scope": "library:read",
            },
            private,
            algorithm="RS256",
        )

        class Identity:
            async def exchange(self, *args):
                return {
                    "access_token": token,
                    "refresh_token": "synthetic-benchmark-refresh",
                }

            async def revoke(self, *args):
                pass

        library_store = LocalStore(root / "library")
        manifest, inputs = fixture_build(root / "build")
        runtime = Runtime(library_store, root / "runtime")
        publish(
            library_store,
            manifest,
            inputs,
            expected_version=None,
            activate=runtime.activate,
        )
        from cookbook.library import Library

        source = Library(runtime).search("salt")["results"][0]["citation"]["source_id"]
        at = destination(manifest.publication_id, source, section_id="section-0")
        config = ReaderConfig(
            "https://reader.example", "synthetic-client", "synthetic-secret"
        )
        cipher_key = Fernet.generate_key()
        clients = {}
        try:
            for _ in range(2):
                relay = Relay(args.fly_app, prefix)
                relays.append(relay)
                for _ in range(3):
                    relay.call("ping")
            with contextlib.redirect_stdout(io.StringIO()):
                for backend in ("r2", "postgres"):
                    clients[backend] = []
                    for i in range(2):
                        local = LocalStore(root / "oauth")
                        store = (
                            RemoteOwnerStore(local, relays[i])
                            if backend == "r2"
                            else local
                        )
                        reader = Reader(
                            config,
                            verifier,
                            store,
                            cipher_key,
                            identity=Identity(),
                            session_database=dsn if backend == "postgres" else None,
                        )
                        client = stack.enter_context(
                            TestClient(
                                create_hosted_app(runtime, verifier, reader=reader),
                                base_url="https://reader.example",
                            )
                        )
                        clients[backend].append(client)
                    assert login(clients[backend][0]).status_code == 303
                    clients[backend][1].cookies.set(
                        "__Host-reader",
                        clients[backend][0].cookies.get("__Host-reader"),
                    )
            csrf = {}
            with contextlib.redirect_stdout(io.StringIO()):
                for name, pair in clients.items():
                    csrf[name] = pair[0].get("/reader/session").json()["csrf"]
            paths = {
                "catalog": ("/reader/catalog", {}),
                "text": ("/reader/read", {"at": at}),
                "original": ("/reader/original", {"at": at, "image": "image-0"}),
                "image": ("/reader/image", {"at": at, "image": "image-0"}),
                "passive": ("/reader/session", {}),
            }

            def journey(name, backend):
                c = clients[backend][0]
                if name == "search":
                    r = c.post(
                        "/reader/search/results",
                        json={"csrf": csrf[backend], "query": "salt"},
                        headers={"Origin": "https://reader.example"},
                    )
                    assert (
                        r.status_code == 200
                        and r.json()["groups"]["section"]["results"]
                    )
                elif name == "two_tabs":
                    with ThreadPoolExecutor(2) as pool:
                        futures = [
                            pool.submit(client.get, "/reader/catalog")
                            for client in clients[backend]
                        ]
                        for f in futures:
                            r = f.result()
                            assert r.status_code == 200 and "Beans" in r.text
                    return
                else:
                    path, params = paths[name]
                    r = c.get(path, params=params)
                    assert r.status_code == 200
                    if name == "image":
                        assert r.content[:2] == b"\xff\xd8"
                    elif name == "passive":
                        assert r.json()["authenticated"]
                    elif name == "text":
                        assert "Synthetic bean recipe" in r.text
                    elif name == "original":
                        assert "data-original-image" in r.text
                    else:
                        assert "Beans" in r.text

            for name in args.journeys:
                # Warm both sides outside the measured repetitions.
                with contextlib.redirect_stdout(io.StringIO()):
                    for backend in clients:
                        journey(name, backend)
                for lap in range(5):
                    for backend in (
                        ("r2", "postgres") if lap % 2 == 0 else ("postgres", "r2")
                    ):
                        before = [len(r.samples) for r in relays]
                        capture = io.StringIO()
                        started = time.perf_counter()
                        try:
                            with contextlib.redirect_stdout(capture):
                                journey(name, backend)
                            error = False
                        except Exception:  # noqa: BLE001 - count failures; never include private error text
                            error = True
                        elapsed = (time.perf_counter() - started) * 1000
                        traces = [
                            json.loads(line)
                            for line in capture.getvalue().splitlines()
                            if line.startswith('{"event":"reader_request"')
                        ]
                        calls = [
                            s for r, n in zip(relays, before) for s in r.samples[n:]
                        ]
                        results.append(
                            {
                                "journey": name,
                                "backend": backend,
                                "lap": lap,
                                "wall_ms": elapsed,
                                "error": error,
                                "statuses": [t["status"] for t in traces],
                                "stages": {
                                    stage: sum(
                                        t["stages"].get(stage, {}).get("ms", 0)
                                        for t in traces
                                    )
                                    for stage in (
                                        "session_read",
                                        "session_write",
                                        "token_verify",
                                    )
                                },
                                "r2_calls": calls,
                            }
                        )
                print(name + " complete", file=sys.stderr, flush=True)
            # Confirm real PostgreSQL state and prevent a no-op timing result.
            with psycopg.connect(dsn) as conn:
                row = conn.execute(
                    "SELECT count(*), max(seen-created) FROM reader_device_sessions"
                ).fetchone()
                assert row[0] == 1 and row[1] > 0
            report = {
                "samples": results,
                "worker_images": [r.ready.get("image") for r in relays],
                "ping_ms": [s for r in relays for s in r.samples if s["op"] == "ping"],
                "cleanup_failures": None,
                "scope": "Synthetic HTTP. R2 via Fly SSH relay; PostgreSQL local socket. No hosted speedup claim.",
            }
        finally:
            # Close HTTP clients before deleting synthetic owner records.
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    stack.close()
            finally:
                close_relays(relays)
        report["cleanup_failures"] = 0
        report["summary"] = {
            name: {
                backend: {
                    "failures": sum(
                        s["error"]
                        for s in results
                        if s["journey"] == name and s["backend"] == backend
                    ),
                    "wall_ms": summary(
                        [
                            s["wall_ms"]
                            for s in results
                            if s["journey"] == name
                            and s["backend"] == backend
                            and not s["error"]
                        ]
                    )
                    if any(
                        s["journey"] == name
                        and s["backend"] == backend
                        and not s["error"]
                        for s in results
                    )
                    else None,
                }
                for backend in clients
            }
            for name in dict.fromkeys(s["journey"] for s in results)
        }
        args.output.write_text(json.dumps(report, indent=2))
        print(
            json.dumps(
                {
                    "failures": sum(r["error"] for r in results),
                    "requests": len(results),
                    "cleanup_failures": 0,
                }
            )
        )
        return int(any(r["error"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
