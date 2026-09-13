import asyncio
import os
import signal
import sys
import threading
import time

import httpx
import pytest
from starlette.testclient import TestClient

from cookbook.hosted import PublicationUpdater, create_hosted_app, wait_for_activation
from cookbook.library import Library
from cookbook.publication import Runtime, publish
from cookbook.server import JWTVerifier
from cookbook.storage import IntegrityError
from cookbook.supervisor import supervise
from conftest import fixture_build


def eventually(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


def test_empty_boot_polling_auth_and_outage(published, tmp_path, keys, mint):
    m, _, store, _, _, first = published
    runtime = Runtime(store, tmp_path / "fresh")
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://service.example",
        subjects=["user-1"],
        public_key=keys[1],
    )
    headers = {"Authorization": "Bearer " + mint(aud="https://service.example")}
    with TestClient(
        create_hosted_app(runtime, verifier, poll_seconds=0.02),
        base_url="https://service.example",
    ) as client:
        eventually(lambda: runtime.active() is not None)
        ready = client.get("/readyz", headers=headers)
        assert ready.json()["manifest_sha256"] == first["manifest_sha256"]
        assert ready.json()["publication_id"] == m.publication_id
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 401
        challenge = client.get("/readyz").headers["www-authenticate"]
        assert (
            'resource_metadata="https://service.example/.well-known/oauth-protected-resource"'
            in challenge
        )
        assert client.get("/.well-known/oauth-protected-resource").status_code == 200
        assert (
            client.get("/.well-known/oauth-protected-resource").json()["resource"]
            == "https://service.example"
        )
        tools = client.post(
            "/mcp",
            headers={**headers, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200 and len(tools.json()["result"]["tools"]) == 9
        assert (
            client.post(
                "/mcp",
                headers={
                    **headers,
                    "Host": "untrusted.example",
                    "Accept": "application/json, text/event-stream",
                },
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ).status_code
            == 421
        )
        for bad in [
            mint(aud="https://service.example", sub="other"),
            mint(aud="https://service.example", scope="other"),
        ]:
            assert (
                client.get(
                    "/readyz", headers={"Authorization": "Bearer " + bad}
                ).status_code
                == 401
            )
        saved = store.read_version
        store.read_version = lambda *_: (_ for _ in ()).throw(
            OSError("secret contents must not be logged")
        )
        time.sleep(0.05)
        assert Library(runtime).search("beans")["results"]
        assert client.get("/readyz", headers=headers).status_code == 200
        assert client.get("/healthz").status_code == 200
        store.read_version = saved
        new, inputs = fixture_build(tmp_path / "new")
        _, version = saved("control/active.json")
        publish(store, new, inputs, expected_version=version, activate=lambda _: None)
        eventually(lambda: runtime.active()["publication_id"] == new.publication_id)
        assert Library(runtime).search("beans", publication_id=m.publication_id)[
            "results"
        ]


def test_failed_update_keeps_prior_and_recovers(published, tmp_path, capsys):
    m, _, store, runtime, lib, _ = published
    new, inputs = fixture_build(tmp_path / "new")
    _, version = store.read_version("control/active.json")
    publish(store, new, inputs, expected_version=version, activate=lambda _: None)
    entry = next(e for e in new.files if e.role == "runtime")
    original = store.path(entry.key).read_bytes()
    store.path(entry.key).write_bytes(b"private bad bytes")
    updater = PublicationUpdater(runtime)
    assert updater.tick() == "publication_update_failed"
    assert runtime.active()["publication_id"] == m.publication_id
    assert lib.search("beans")["results"]
    store.path(entry.key).write_bytes(original)
    assert updater.tick() == "publication_activated"
    assert runtime.active()["publication_id"] == new.publication_id
    assert "private bad bytes" not in capsys.readouterr().out


def test_restart_validates_cache_without_network_and_repairs_corruption(published):
    m, _, store, runtime, _, _ = published
    saved = store.read_version
    store.read_version = lambda *_: (_ for _ in ()).throw(OSError("offline"))
    restarted = Runtime(store, runtime.root)
    assert restarted.resume_cached() == m.publication_id
    assert PublicationUpdater(restarted).tick() == "publication_update_failed"
    assert Library(restarted).search("beans")["results"]
    (runtime.root / "versions" / m.publication_id / "runtime/index.sqlite").write_bytes(
        b"bad"
    )
    with pytest.raises(IntegrityError):
        restarted.resume_cached()
    assert restarted.active() is None
    store.read_version = saved
    assert PublicationUpdater(restarted).tick() == "publication_activated"
    assert Library(restarted).search("beans")["results"]


async def advance_clock(now, seconds):
    now[0] += seconds


def test_waiter_requires_exact_pointer_and_never_follows_redirects():
    pointer = {"publication_id": "a" * 32, "manifest_sha256": "b" * 64}
    now = [0.0]
    seen = []
    responses = [
        httpx.Response(302, headers={"location": "https://untrusted.example/"}),
        httpx.Response(401),
        httpx.Response(
            200, json={"status": "ready", **pointer, "manifest_sha256": "c" * 64}
        ),
        httpx.Response(200, json={"status": "ready", **pointer}),
    ]

    def handler(request):
        seen.append(request)
        return responses.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = wait_for_activation(
        pointer,
        "https://service.example/readyz",
        lambda: "sensitive-token",
        client=client,
        clock=lambda: now[0],
        sleep=lambda seconds: advance_clock(now, seconds),
    )
    assert result == pointer["publication_id"]
    assert len(seen) == 4 and all(r.url.host == "service.example" for r in seen)
    assert now[0] == 15


def test_ack_timeout_is_pending_and_can_resume():
    pointer = {"publication_id": "a" * 32, "manifest_sha256": "b" * 64}
    now = [0.0]
    response = [httpx.Response(503)]
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response[0]))
    args = dict(
        client=client,
        clock=lambda: now[0],
        sleep=lambda seconds: advance_clock(now, seconds),
    )
    assert (
        wait_for_activation(
            pointer, "https://service.example/readyz", lambda: "secret", **args
        )
        is None
    )
    assert now[0] == 300
    response[0] = httpx.Response(200, json={"status": "ready", **pointer})
    assert (
        wait_for_activation(
            pointer, "https://service.example/readyz", lambda: "refreshed", **args
        )
        == pointer["publication_id"]
    )


def worker_script(tmp_path):
    started = tmp_path / "pids"
    script = tmp_path / "worker.py"
    script.write_text(
        "import os,time\nwith open("
        + repr(str(started))
        + ", 'a') as f: f.write(str(os.getpid())+'\\n')\nwhile True: time.sleep(1)\n"
    )
    return started, script


@pytest.mark.parametrize("failure", ["crash", "hang"])
def test_real_worker_restart_and_shutdown(tmp_path, failure):
    started, script = worker_script(tmp_path)
    stop = threading.Event()
    fail_health = threading.Event()
    thread = threading.Thread(
        target=supervise,
        args=([sys.executable, str(script)], "http://127.0.0.1:1/healthz", stop),
        kwargs={
            "interval": 0.05,
            "startup_grace": 0,
            "probe": lambda _: not fail_health.is_set(),
        },
    )
    thread.start()

    def pids():
        return started.read_text().splitlines() if started.exists() else []

    try:
        eventually(lambda: len(pids()) >= 1)
        first = int(pids()[0])
        if failure == "crash":
            os.kill(first, signal.SIGKILL)
        else:
            fail_health.set()
        eventually(lambda: len(pids()) >= 2)
        fail_health.clear()
        assert int(pids()[1]) != first
        with pytest.raises(ProcessLookupError):
            os.kill(first, 0)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    for pid in pids():
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid), 0)


def test_watchdog_startup_grace(tmp_path):
    started, script = worker_script(tmp_path)
    stop = threading.Event()
    calls = []

    def probe(_):
        calls.append(time.monotonic())
        return False

    thread = threading.Thread(
        target=supervise,
        args=([sys.executable, str(script)], "unused", stop),
        kwargs={"interval": 0.04, "startup_grace": 0.3, "probe": probe},
    )
    thread.start()
    try:
        eventually(lambda: len(calls) >= 4)
        assert len(started.read_text().splitlines()) == 1
        eventually(lambda: len(started.read_text().splitlines()) >= 2)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_ack_total_timeout_includes_slow_response():
    async def slow(request):
        await asyncio.sleep(5)
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    started = time.monotonic()
    assert (
        wait_for_activation(
            {"publication_id": "a" * 32, "manifest_sha256": "b" * 64},
            "https://service.example/readyz",
            lambda: "secret",
            timeout=0.05,
            client=client,
        )
        is None
    )
    assert time.monotonic() - started < 1


def test_remote_publish_pending_retry_and_success_history(
    published, tmp_path, monkeypatch, capsys
):
    import json
    from cookbook import cli, hosted
    from cookbook.storage import atomic_write, canonical

    _, _, store, runtime, _, first = published
    build = tmp_path / "remote-build"
    new, inputs = fixture_build(build)
    atomic_write(build / "manifest.json", canonical(new.model_dump()))
    atomic_write(
        build / "inputs.json", canonical({k: str(v) for k, v in inputs.items()})
    )
    token = tmp_path / "token"
    token.write_text("private-oauth-token")
    token.chmod(0o600)
    state = tmp_path / "publisher-state"
    monkeypatch.setenv("COOKBOOK_AUDIENCE", "https://service.example")
    monkeypatch.setattr(hosted, "store_from_environment", lambda: store)
    monkeypatch.setattr(hosted, "wait_for_activation", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cookbook",
            "publish-s3",
            "--build",
            str(build),
            "--state-directory",
            str(state),
            "--readiness-url",
            "https://service.example/readyz",
            "--token-file",
            str(token),
        ],
    )
    with pytest.raises(SystemExit) as pending:
        cli._main()
    assert pending.value.code == 4
    pointer = json.loads((state / "pending-activation.json").read_bytes())
    assert pointer["publication_id"] == new.publication_id
    assert runtime.active()["publication_id"] == first["publication_id"]
    monkeypatch.setattr(
        hosted, "wait_for_activation", lambda pointer, *args: runtime.activate(pointer)
    )
    cli._main()
    assert runtime.active()["publication_id"] == new.publication_id
    history = json.loads(store.read("control/successful.json"))
    assert history[0] == pointer
    output = capsys.readouterr().out
    assert "pending_activation" in output and "private-oauth-token" not in output
    monkeypatch.setenv("COOKBOOK_AUDIENCE", "https://wrong.example")
    with pytest.raises(ValueError, match="readiness target"):
        cli._main()


def test_missing_publication_is_live_but_not_ready(tmp_path, keys, mint):
    from cookbook.storage import LocalStore

    runtime = Runtime(LocalStore(tmp_path / "empty"), tmp_path / "runtime")
    v = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://service.example",
        subjects=["user-1"],
        public_key=keys[1],
    )
    with TestClient(create_hosted_app(runtime, v, poll_seconds=0.02)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 401
        response = client.get(
            "/readyz",
            headers={"Authorization": "Bearer " + mint(aud="https://service.example")},
        )
        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "publication_id": None,
            "manifest_sha256": None,
        }
