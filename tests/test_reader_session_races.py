"""Synthetic HTTP races across independent applications sharing LocalStore."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

from starlette.testclient import TestClient
from test_reader_http import login, reader_env  # noqa: F401

from cookbook.storage import LocalStore


def test_same_cookie_activity_pair_both_succeed(reader_env, monkeypatch):  # noqa: F811
    app, _, clock = reader_env
    with (
        TestClient(app(), base_url="https://reader.example") as a,
        TestClient(app(), base_url="https://reader.example") as b,
    ):
        login(a)
        b.cookies.set("__Host-reader", a.cookies.get("__Host-reader"))
        clock[0] += 1
        barrier, lock = Barrier(2), Lock()
        original = LocalStore.put_bytes
        count = 0

        def paired(self, key, *args, **kwargs):
            nonlocal count
            if key.startswith("reader/owners/"):
                with lock:
                    count += 1
                    ordinal = count
                if ordinal <= 2:
                    barrier.wait(timeout=5)
            return original(self, key, *args, **kwargs)

        monkeypatch.setattr(LocalStore, "put_bytes", paired)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(a.get, "/reader/catalog")
            second = pool.submit(b.get, "/reader/catalog")
            responses = [first.result(), second.result()]
        assert sorted(r.status_code for r in responses) == [200, 200]


import asyncio
import hashlib
import json
from datetime import UTC, datetime

import pytest

from cookbook.reader import Reader
from cookbook.storage import Conflict, canonical


@pytest.fixture
def world(reader_env, monkeypatch):  # noqa: F811
    app, identity, clock = reader_env
    readers = []
    original = Reader.__init__

    def capture(self, *args, **kwargs):
        original(self, *args, **kwargs)
        readers.append(self)

    monkeypatch.setattr(Reader, "__init__", capture)
    with (
        TestClient(app(), base_url="https://reader.example") as a,
        TestClient(app(), base_url="https://reader.example") as b,
    ):
        login(a)
        b.cookies.set("__Host-reader", a.cookies.get("__Host-reader"))
        yield a, b, readers[0], identity, clock


def record(reader):
    key = "reader/owners/" + hashlib.sha256(b"user-1").hexdigest()
    raw, version = reader.store.read_version(key)
    return key, json.loads(reader.cipher.decrypt(raw)), version


def change(reader, fn):
    key, owner, version = record(reader)
    fn(owner)
    reader.store.put_bytes(
        key, reader.cipher.encrypt(canonical(owner)), expected=version
    )


def expire(clock, monkeypatch):
    clock[0] += 601

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(clock[0], UTC)

    monkeypatch.setattr("jwt.api_jwt.datetime", Later)


@pytest.mark.parametrize("phase", ["activity", "lease", "settle", "removal"])
def test_committed_conflict_is_idempotent(world, monkeypatch, mint, phase):
    a, _, reader, identity, clock = world
    revoked = []

    async def revoke(token):
        revoked.append(token)

    identity.revoke = revoke
    if phase in {"lease", "settle"}:
        expire(clock, monkeypatch)
        identity.renewed_tokens = {
            "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
            "refresh_token": "new-refresh",
        }
    else:
        clock[0] += 1
    original = LocalStore.put_bytes
    fired = []

    def self_conflict(self, key, data, **kwargs):
        result = original(self, key, data, **kwargs)
        if key.startswith("reader/owners/") and not fired:
            sessions = json.loads(reader.cipher.decrypt(data))["sessions"]
            leased = any("renewing" in s for s in sessions.values())
            selected = (
                phase == "activity"
                or phase == "lease"
                and leased
                or phase == "settle"
                and not leased
                or phase == "removal"
                and not sessions
            )
            if selected:
                fired.append(True)
                raise Conflict("synthetic committed 412")
        return result

    monkeypatch.setattr(LocalStore, "put_bytes", self_conflict)
    if phase == "removal":
        csrf = a.get("/reader/session").json()["csrf"]
        r = a.post(
            "/reader/logout",
            json={"scope": "device", "csrf": csrf},
            headers={"Origin": "https://reader.example"},
        )
        assert revoked == ["synthetic-refresh"]
    else:
        r = a.get("/reader/catalog")
        assert "new-refresh" not in revoked
        assert a.get("/reader/session").status_code == 200
    assert r.status_code == 200
    assert fired


def test_ambiguous_logout_never_acknowledges(world, monkeypatch):
    a, b, _, identity, _ = world
    csrf = a.get("/reader/session").json()["csrf"]
    revoked = []

    async def revoke(token):
        revoked.append(token)

    identity.revoke = revoke
    original = LocalStore.put_bytes

    def ambiguous(self, key, *args, **kwargs):
        result = original(self, key, *args, **kwargs)
        if key.startswith("reader/owners/"):
            raise TimeoutError("PRIVATE-STORAGE-SENTINEL")
        return result

    monkeypatch.setattr(LocalStore, "put_bytes", ambiguous)
    r = a.post(
        "/reader/logout",
        json={"scope": "device", "csrf": csrf},
        headers={"Origin": "https://reader.example"},
    )
    assert r.status_code == 503
    assert r.headers["x-reader-failure"].startswith(
        "session_storage; stage=session_end"
    )
    assert not revoked
    assert b.get("/reader/session").status_code == 401


def test_passive_no_write_and_exact_idle(world, monkeypatch):
    a, _, reader, _, clock = world
    clock[0] += 1
    original = LocalStore.put_bytes
    writes = []

    def count(self, key, *args, **kwargs):
        writes.append(key)
        return original(self, key, *args, **kwargs)

    monkeypatch.setattr(LocalStore, "put_bytes", count)
    assert a.get("/reader/session").status_code == 200
    assert not writes
    # An invalid destination still counts as activity.
    assert a.get("/reader/read").status_code == 400
    seen = next(iter(record(reader)[1]["sessions"].values()))["seen"]
    assert seen == clock[0]
    clock[0] = seen + 7 * 86400 - 1
    assert a.get("/reader/session").status_code == 200
    clock[0] += 1
    assert a.get("/reader/session").status_code == 401


def test_cancelled_renewal_leaves_lease_and_never_replays(world, monkeypatch):
    a, b, reader, identity, clock = world
    expire(clock, monkeypatch)
    calls = []
    cancelled = []

    async def renew(token):
        calls.append(token)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    identity.renew = renew
    monkeypatch.setattr("cookbook.reader.DEADLINE", 0.03)
    r = a.get("/reader/session")
    assert r.status_code == 503
    assert r.headers["x-reader-failure"].startswith("deadline; stage=provider_renew")
    assert cancelled == [True]
    assert "renewing" in next(iter(record(reader)[1]["sessions"].values()))
    r = b.get("/reader/session")
    assert r.status_code == 503
    assert r.headers["x-reader-failure"].startswith("renewal_pending;")
    assert len(calls) == 1
    clock[0] += 10
    assert b.get("/reader/session").status_code == 401
    assert not record(reader)[1]["sessions"]


@pytest.mark.parametrize(
    "path,category,stage",
    [
        ("/reader/catalog", "library", "library_search"),
        ("/reader/personal", "personal_state", "personal_state"),
        ("/reader/content", "content", "content_deliver"),
        ("/reader/search/results", "library", "library_search"),
        ("/reader/reports", "reports", "report_intake"),
    ],
)
def test_work_fault_headers_and_redaction(
    world, monkeypatch, capsys, path, category, stage
):
    a, _, _, _, _ = world

    async def failed(*args, **kwargs):
        raise RuntimeError("PRIVATE-PAYLOAD-SENTINEL")

    if path == "/reader/catalog":

        def bad(*args, **kwargs):
            raise RuntimeError("PRIVATE-PAYLOAD-SENTINEL")

        monkeypatch.setattr("cookbook.library.Library.search", bad)
    else:
        targets = {
            "/reader/personal": "cookbook.reader_personal.endpoint",
            "/reader/content": "cookbook.reader.deliver",
            "/reader/search/results": "cookbook.reader_search.results",
            "/reader/reports": "cookbook.owner_reports.intake",
        }
        monkeypatch.setattr(targets[path], failed)
    r = a.request(
        "POST" if path in {"/reader/reports", "/reader/search/results"} else "GET",
        path + "?q=PRIVATE-QUERY-SENTINEL",
    )
    assert r.status_code == 503
    assert r.headers["x-reader-failure"].startswith(f"{category}; stage={stage}")
    assert "PRIVATE-" not in r.text
    output = capsys.readouterr().out
    assert "PRIVATE-" not in output


def test_route_returned_failure_and_all_routes_have_ids(world):
    a, _, _, _, _ = world
    r = a.get("/reader/personal")
    assert r.status_code == 503
    assert r.json()["error"] == "personal_unavailable"
    assert r.headers["x-reader-failure"].startswith("personal_state;")
    for route in a.app.routes:
        if getattr(route, "path", "").startswith("/reader"):
            method = "GET" if "GET" in route.methods else "POST"
            response = a.request(method, route.path, follow_redirects=False)
            assert len(response.headers["x-reader-request"]) == 16


@pytest.mark.parametrize("legacy", [True, False])
def test_held_lease_compatibility_and_staleness(world, monkeypatch, legacy):
    a, _, reader, identity, clock = world
    now = clock[0]

    def lease(owner):
        entry = next(iter(owner["sessions"].values()))
        if legacy:
            entry["renewing"] = now
        else:
            entry["lease"] = "orphan-nonce"

    change(reader, lease)
    calls = []

    async def renew(token):
        calls.append(token)
        raise AssertionError("must not renew")

    identity.renew = renew
    monkeypatch.setattr("cookbook.reader.DEADLINE", 0.02)
    r = a.get("/reader/session")
    assert r.status_code == (503 if legacy else 200)
    assert not calls
    if legacy:
        clock[0] += 10
        assert a.get("/reader/session").status_code == 401


def test_renewal_siblings_exchange_once(world, monkeypatch, mint):
    from threading import Event

    a, b, _, identity, clock = world
    expire(clock, monkeypatch)
    entered, release = Event(), Event()
    calls = []

    async def renew(token):
        calls.append(token)
        entered.set()
        await asyncio.to_thread(release.wait, 3)
        return {
            "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
            "refresh_token": "new-refresh",
        }

    identity.renew = renew
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(a.get, "/reader/session")
        assert entered.wait(3)
        # Give the sibling a deterministic observation of the held lease before release.
        observed = Event()
        original = LocalStore.read_version

        def read(self, key):
            result = original(self, key)
            if key.startswith("reader/owners/"):
                observed.set()
            return result

        monkeypatch.setattr(LocalStore, "read_version", read)
        second = pool.submit(b.get, "/reader/catalog")
        assert observed.wait(3)
        release.set()
        assert first.result().status_code == 200
        assert second.result().status_code == 200
    assert len(calls) == 1


def test_bounded_contention_is_truthful(world, monkeypatch):
    a, _, reader, _, clock = world
    clock[0] += 1
    original = LocalStore.put_bytes
    attempts = []

    def competing(self, key, data, **kwargs):
        if key.startswith("reader/owners/"):
            attempts.append(True)
            _, owner, version = record(reader)
            owner["other-device-counter"] = len(attempts)
            original(
                self, key, reader.cipher.encrypt(canonical(owner)), expected=version
            )
            raise Conflict("private contention")
        return original(self, key, data, **kwargs)

    monkeypatch.setattr(LocalStore, "put_bytes", competing)
    r = a.get("/reader/catalog")
    assert r.status_code == 503
    assert (
        r.headers["x-reader-failure"]
        == "session_changed; stage=session_write; attempts=3"
    )
    assert len(attempts) == 3
    assert next(iter(record(reader)[1]["sessions"].values()))["seen"] < clock[0]


def test_first_callbacks_race_preserves_both(reader_env, monkeypatch):  # noqa: F811
    from urllib.parse import parse_qs, urlsplit

    app, _, _ = reader_env
    with (
        TestClient(app(), base_url="https://reader.example") as a,
        TestClient(app(), base_url="https://reader.example") as b,
    ):
        params = []
        for client in (a, b):
            q = parse_qs(
                urlsplit(
                    client.get("/reader/login", follow_redirects=False).headers[
                        "location"
                    ]
                ).query
            )
            params.append(
                {
                    "code": "synthetic-code",
                    "iss": "https://issuer.example/",
                    "state": q["state"][0],
                }
            )
        original = LocalStore.put_bytes
        barrier, lock = Barrier(2), Lock()
        count = 0

        def paired(self, key, *args, **kwargs):
            nonlocal count
            if key.startswith("reader/owners/"):
                with lock:
                    count += 1
                    n = count
                if n <= 2:
                    barrier.wait(3)
            return original(self, key, *args, **kwargs)

        monkeypatch.setattr(LocalStore, "put_bytes", paired)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(
                a.get, "/reader/callback", params=params[0], follow_redirects=False
            )
            second = pool.submit(
                b.get, "/reader/callback", params=params[1], follow_redirects=False
            )
            assert first.result().headers["location"] == "/reader/catalog"
            assert second.result().headers["location"] == "/reader/catalog"
        assert a.cookies.get("__Host-reader") != b.cookies.get("__Host-reader")
        assert a.get("/reader/session").status_code == 200
        assert b.get("/reader/session").status_code == 200


def test_location_failure_stage_and_inner_timeout(world, monkeypatch):
    from cookbook.reader_content import encode_location

    a, _, _, _, _ = world

    def failed(*args, **kwargs):
        raise TimeoutError("PRIVATE-LOCATION-SENTINEL")

    monkeypatch.setattr("cookbook.reader_updates.resolve_current", failed)
    at = encode_location(
        {"publication_id": "a" * 32, "book_id": "synthetic", "source_id": "synthetic"}
    )
    r = a.get("/reader/updates", params={"at": at})
    assert r.status_code == 503
    assert r.headers["x-reader-failure"].startswith("library; stage=library_resolve;")
    assert r.json()["error"] == "library"
    assert "category" not in r.json()


def test_waiter_rechecks_current_expiry(world, monkeypatch):
    a, _, reader, _, clock = world
    now = clock[0]

    def lease(owner):
        next(iter(owner["sessions"].values())).update(renewing=now - 9.5, lease="other")

    change(reader, lease)
    original = asyncio.sleep

    async def advance(delay):
        clock[0] += 0.5
        await original(0)

    monkeypatch.setattr("cookbook.reader_sessions.asyncio.sleep", advance)
    assert a.get("/reader/session").status_code == 401


@pytest.mark.parametrize("active_first", [True, False])
def test_passive_and_activity_order(world, monkeypatch, active_first):
    from threading import Event

    a, b, reader, _, clock = world
    clock[0] += 1
    entered, release = Event(), Event()
    original = LocalStore.put_bytes
    writes = []

    def held(self, key, *args, **kwargs):
        if key.startswith("reader/owners/"):
            writes.append(True)
            entered.set()
            assert release.wait(3)
        return original(self, key, *args, **kwargs)

    monkeypatch.setattr(LocalStore, "put_bytes", held)
    with ThreadPoolExecutor(1) as pool:
        if not active_first:
            assert b.get("/reader/session").status_code == 200
        active = pool.submit(a.get, "/reader/catalog")
        assert entered.wait(3)
        if active_first:
            assert b.get("/reader/session").status_code == 200
        release.set()
        assert active.result().status_code == 200
    assert len(writes) == 1
    assert next(iter(record(reader)[1]["sessions"].values()))["seen"] == clock[0]


def test_token_boundary_and_safe_representations():
    from cookbook.reader_sessions import NewSession, ProviderTokens

    for raw in ({}, {"access_token": None}, {"access_token": "a", "refresh_token": 5}):
        with pytest.raises(ValueError):
            ProviderTokens.parse(raw)
    tokens = ProviderTokens.parse(
        {"access_token": "PRIVATE-ACCESS", "refresh_token": "PRIVATE-REFRESH"}
    )
    assert "PRIVATE-" not in repr(tokens)
    assert "PRIVATE-" not in repr(NewSession("PRIVATE-COOKIE"))


def test_revision_and_at_sentinels_are_never_logged(world, capsys, monkeypatch):
    from cookbook.reader_content import encode_location

    a, _, _, _, _ = world
    monkeypatch.setenv("FLY_IMAGE_REF", "PRIVATE-ENV-SENTINEL")
    at = encode_location(
        {
            "publication_id": "a" * 32,
            "book_id": "PRIVATE-BOOK",
            "source_id": "PRIVATE-SOURCE",
        }
    )
    a.get("/reader/updates", params={"at": at, "q": "PRIVATE-QUERY"})
    traces = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if '"reader_request"' in line
    ]
    assert traces
    for trace in traces:
        assert "PRIVATE-" not in json.dumps(trace)
        assert at not in json.dumps(trace)
        assert trace["revision"] is None
        assert len(trace["stages"]) <= 21


def test_missing_cookie_has_no_storage_io(reader_env, monkeypatch):  # noqa: F811
    app, _, _ = reader_env
    application = app()

    def no_io(*args, **kwargs):
        raise AssertionError("missing cookie must not read session storage")

    monkeypatch.setattr(LocalStore, "read_version", no_io)
    with TestClient(application, base_url="https://reader.example") as a:
        assert a.get("/reader/session").status_code == 401


def test_expiry_committed_conflict_still_revokes(world, monkeypatch):
    a, _, _, identity, clock = world
    clock[0] += 7 * 86400
    original = LocalStore.put_bytes
    revoked = []

    async def revoke(token):
        revoked.append(token)

    identity.revoke = revoke

    def committed(self, key, *args, **kwargs):
        result = original(self, key, *args, **kwargs)
        if key.startswith("reader/owners/"):
            raise Conflict("committed removal")
        return result

    monkeypatch.setattr(LocalStore, "put_bytes", committed)
    assert a.get("/reader/session").status_code == 401
    assert revoked == ["synthetic-refresh"]


def test_ambiguous_settlement_does_not_revoke_stored_refresh(world, monkeypatch, mint):
    a, b, reader, identity, clock = world
    expire(clock, monkeypatch)
    identity.renewed_tokens = {
        "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
        "refresh_token": "new-refresh",
    }
    original = LocalStore.put_bytes
    revoked = []

    async def revoke(token):
        revoked.append(token)

    identity.revoke = revoke

    def ambiguous(self, key, data, **kwargs):
        result = original(self, key, data, **kwargs)
        if key.startswith("reader/owners/"):
            entries = json.loads(reader.cipher.decrypt(data))["sessions"]
            if any(s.get("refresh") == "new-refresh" for s in entries.values()):
                raise TimeoutError("PRIVATE-SETTLEMENT")
        return result

    monkeypatch.setattr(LocalStore, "put_bytes", ambiguous)
    assert a.get("/reader/session").status_code == 503
    assert "new-refresh" not in revoked
    assert b.get("/reader/session").status_code == 200
