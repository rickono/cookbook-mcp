"""Serving-only research probe: real HTTP/JWT/CAS, synthetic storage/provider wait.

Run with pytest -s; aggregate rows contain no credentials, content or paths.
Injected delays explain operation costs; they do not estimate hosted latency.
"""

import asyncio
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import pytest
from starlette.testclient import TestClient
from test_reader_http import login, reader_env  # noqa: F401
from test_reader_session_races import expire

from cookbook.reader import Reader
from cookbook.storage import Conflict, LocalStore


@pytest.mark.parametrize(
    "scenario",
    [
        "passive",
        "active",
        "conflict",
        "exhausted",
        "renewal",
        "refused",
        "siblings",
        "storage_fault",
    ],
)
def test_session_stage_probe(reader_env, monkeypatch, mint, capsys, scenario):  # noqa: F811
    factory, identity, clock = reader_env
    readers = []
    init = Reader.__init__

    def capture(self, *args, **kwargs):
        init(self, *args, **kwargs)
        readers.append(self)

    monkeypatch.setattr(Reader, "__init__", capture)
    rows = []
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        reader = readers[0]
        original_read, original_put = LocalStore.read_version, LocalStore.put_bytes
        original_verify = reader.verifier.verify_token
        original_renew = identity.renew
        lock = Lock()
        counts = {}
        waits = {}
        enabled = False
        conflicts_left = 0

        def count(name, elapsed=0):
            with lock:
                counts[name] = counts.get(name, 0) + 1
                waits[name] = waits.get(name, 0) + elapsed

        def read(self, key):
            if not enabled or not key.startswith("reader/owners/"):
                return original_read(self, key)
            started = time.perf_counter()
            try:
                time.sleep(0.02)
                if scenario == "storage_fault":
                    raise OSError("synthetic storage fault")
                return original_read(self, key)
            finally:
                count("read", time.perf_counter() - started)

        def put(self, key, *args, **kwargs):
            nonlocal conflicts_left
            if not enabled or not key.startswith("reader/owners/"):
                return original_put(self, key, *args, **kwargs)
            started = time.perf_counter()
            try:
                time.sleep(0.02)
                with lock:
                    conflict = conflicts_left > 0
                    conflicts_left -= int(conflict)
                if conflict:
                    raise Conflict("synthetic precondition")
                return original_put(self, key, *args, **kwargs)
            except Conflict:
                count("conflict")
                raise
            finally:
                count("put", time.perf_counter() - started)

        async def verify(*args, **kwargs):
            started = time.perf_counter()
            try:
                return await original_verify(*args, **kwargs)
            finally:
                count("verify", time.perf_counter() - started)

        async def renew(token):
            started = time.perf_counter()
            try:
                await asyncio.sleep(0.08)
                return await original_renew(token)
            finally:
                count("provider", time.perf_counter() - started)

        monkeypatch.setattr(LocalStore, "read_version", read)
        monkeypatch.setattr(LocalStore, "put_bytes", put)
        monkeypatch.setattr(reader.verifier, "verify_token", verify)
        monkeypatch.setattr(identity, "renew", renew)
        for _ in range(5):
            # Restore real JWT time for login; only the serving decision is timed.
            monkeypatch.undo()
            monkeypatch.setattr(Reader, "__init__", capture)
            monkeypatch.setattr(LocalStore, "read_version", read)
            monkeypatch.setattr(LocalStore, "put_bytes", put)
            monkeypatch.setattr(reader.verifier, "verify_token", verify)
            monkeypatch.setattr(identity, "renew", renew)
            enabled = False
            identity.refused = False
            identity.tokens = {
                "access_token": mint(),
                "refresh_token": "synthetic-refresh",
            }
            assert login(a).status_code == 303
            b.cookies.set("__Host-reader", a.cookies.get("__Host-reader"))
            clock[0] += 1
            if scenario in {"renewal", "refused", "siblings"}:
                expire(clock, monkeypatch)
                identity.renewed_tokens = {
                    "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
                    "refresh_token": "synthetic-rotated",
                }
                identity.refused = scenario == "refused"
            counts.clear()
            waits.clear()
            conflicts_left = (
                1 if scenario == "conflict" else 3 if scenario == "exhausted" else 0
            )
            capsys.readouterr()
            enabled = True
            wall, cpu = time.perf_counter(), time.process_time()
            path = (
                "/reader/session"
                if scenario in {"passive", "siblings"}
                else "/reader/catalog"
            )
            if scenario == "siblings":
                with ThreadPoolExecutor(2) as pool:
                    futures = [pool.submit(client.get, path) for client in (a, b)]
                    responses = [f.result() for f in futures]
            else:
                responses = [a.get(path)]
            elapsed, used_cpu = time.perf_counter() - wall, time.process_time() - cpu
            enabled = False
            traces = [
                json.loads(line)
                for line in capsys.readouterr().out.splitlines()
                if line.startswith('{"event":"reader_request"')
            ]
            expected = (
                503
                if scenario in {"exhausted", "storage_fault"}
                else 401
                if scenario == "refused"
                else 200
            )
            assert [r.status_code for r in responses] == [expected] * len(responses)
            assert len(traces) == len(responses)
            for response in responses:
                if expected == 200:
                    if path == "/reader/session":
                        assert response.json()["authenticated"] is True
                    else:
                        assert "Beans" in response.text
                elif expected == 503:
                    category = (
                        "session_changed"
                        if scenario == "exhausted"
                        else "session_storage"
                    )
                    assert response.headers["x-reader-failure"].startswith(category)
            if scenario == "siblings":
                assert any(
                    t["stages"].get("renewal_wait", {}).get("n", 0) for t in traces
                )
            assert counts["read"] >= 1
            if scenario in {"passive", "storage_fault"}:
                assert counts.get("put", 0) == 0
            elif scenario in {"renewal", "siblings", "refused"}:
                assert counts["provider"] == 1
                assert counts["put"] == 2 + counts.get("conflict", 0)
            elif scenario == "exhausted":
                assert counts["put"] == counts["conflict"] == 3
                assert counts["read"] == 4
            elif scenario == "conflict":
                assert counts["put"] == 2 and counts["conflict"] == 1
            else:
                assert counts["put"] == 1
            stages = {}
            for trace in traces:
                for name, values in trace["stages"].items():
                    target = stages.setdefault(name, {"ms": 0, "n": 0, "conflicts": 0})
                    for field in target:
                        target[field] += values[field]
            rows.append(
                {
                    "wall_ms": elapsed * 1000,
                    "process_cpu_ms": used_cpu * 1000,
                    "calls": dict(counts),
                    "adapter_wall_ms": {k: v * 1000 for k, v in waits.items()},
                    "stages": stages,
                    "statuses": [r.status_code for r in responses],
                }
            )

    def summary(values):
        return {
            "median": round(statistics.median(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    result = {
        "scenario": scenario,
        "samples": len(rows),
        "injected_store_ms": 20,
        "injected_provider_ms": 80,
        "wall_ms": summary([r["wall_ms"] for r in rows]),
        "process_cpu_ms": summary([r["process_cpu_ms"] for r in rows]),
        "calls": {
            k: summary([r["calls"].get(k, 0) for r in rows])
            for k in {k for r in rows for k in r["calls"]}
        },
        "adapter_wall_ms": {
            k: summary([r["adapter_wall_ms"].get(k, 0) for r in rows])
            for k in {k for r in rows for k in r["adapter_wall_ms"]}
        },
        "stages": {
            k: {
                field: summary([r["stages"].get(k, {}).get(field, 0) for r in rows])
                for field in ("ms", "n", "conflicts")
            }
            for k in {k for r in rows for k in r["stages"]}
        },
        "statuses": rows[0]["statuses"],
    }
    with capsys.disabled():
        print("SESSION_PROBE " + json.dumps(result, sort_keys=True))
