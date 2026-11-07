"""Actual reader HTTP/JWT flow against an opt-in disposable PostgreSQL authority."""

import asyncio
import hashlib
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from test_reader_content import (  # noqa: F401 - run established journeys on this authority
    test_catalog_book_text_continuations_and_login_return,
)
from test_reader_http import (  # noqa: F401 - reuse the public HTTP contract
    login,
    test_denied_identity_cannot_create_reader_session,
    test_logout_scopes_and_csrf_even_when_provider_refuses,
    test_oauth_correlation_redirect_and_replay,
    test_passive_tabs_do_not_extend_idle_lifetime,
    test_reader_cookie_does_not_authenticate_mcp_and_bearer_does_not_create_session,
    test_renewal_and_refusal_via_public_session,
    test_renewed_tokens_must_preserve_resource_authorization,
    test_scripted_logout_acknowledges_before_browser_data_cleanup,
    test_session_idle_and_absolute_limits,
    test_sign_in_catalog_and_restart,
)
from test_reader_session_races import expire

from cookbook.reader import Reader
from cookbook.reader_sessions import LIFETIME

pytest_plugins = ["test_reader_http"]
psycopg = pytest.importorskip("psycopg")


@pytest.fixture(autouse=True)
def postgres_reader(reader_env, monkeypatch):
    conninfo = os.environ.get("READER_TRIAL_DATABASE")
    if not conninfo:
        pytest.skip("Use scripts/try_postgres_reader.py for disposable PostgreSQL")
    schema = (
        Path(__file__).resolve().parents[1] / "src/cookbook/reader_session_schema.sql"
    )
    with psycopg.connect(conninfo, autocommit=True) as conn:
        assert conn.execute(
            "SELECT current_setting('reader.local_trial',true)='on' AND inet_server_addr() IS NULL"
        ).fetchone() == (True,), (
            "Refusing to modify a database outside the disposable runner"
        )
        conn.execute(
            "DROP TABLE IF EXISTS reader_session_retirements,reader_device_sessions,reader_session_owners CASCADE"
        )
        conn.execute(schema.read_text())
    readers = []
    original = Reader.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs, session_database=conninfo)
        readers.append(self)

    monkeypatch.setattr(Reader, "__init__", init)
    yield SimpleNamespace(conninfo=conninfo, readers=readers)
    for reader in readers:
        asyncio.run(reader.close())


def query(trial, sql, params=()):
    with psycopg.connect(
        trial.conninfo, autocommit=True, row_factory=psycopg.rows.dict_row
    ) as conn:
        cursor = conn.execute(sql, params)
        return cursor.fetchall() if cursor.description else []


def rows(trial):
    return query(trial, "SELECT * FROM reader_device_sessions ORDER BY key")


def logout(client, scope="device"):
    csrf = client.get("/reader/session").json()["csrf"]
    return client.post(
        "/reader/logout",
        json={"scope": scope, "csrf": csrf},
        headers={"Origin": "https://reader.example"},
    )


def test_activity_changes_only_requesting_timestamp_and_never_r2_owner(
    reader_env, postgres_reader, monkeypatch
):
    factory, _, clock = reader_env
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        assert login(a).status_code == login(b).status_code == 303
        before = rows(postgres_reader)
        for reader in postgres_reader.readers:
            original_read = reader.store.read_version
            original_put = reader.store.put_bytes

            def read(key, original=original_read):
                assert not key.startswith("reader/owners/")
                return original(key)

            def put(key, *args, original=original_put, **kwargs):
                assert not key.startswith("reader/owners/")
                return original(key, *args, **kwargs)

            monkeypatch.setattr(reader.store, "read_version", read)
            monkeypatch.setattr(reader.store, "put_bytes", put)
        clock[0] += 1
        assert a.get("/reader/session").status_code == 200
        assert rows(postgres_reader) == before
        assert a.get("/reader/catalog").status_code == 200
        after = rows(postgres_reader)
        key = hashlib.sha256(a.cookies.get("__Host-reader").encode()).hexdigest()
        for old, new in zip(before, after, strict=True):
            changed = {column for column in old if old[column] != new[column]}
            assert changed == ({"seen"} if old["key"] == key else set())
        assert all(b"synthetic-refresh" not in r["refresh"] for r in after)
        assert after[0]["refresh_id"] == after[1]["refresh_id"]
        assert after[0]["refresh"] != after[1]["refresh"]


def test_concurrent_tabs_and_devices(reader_env, postgres_reader):
    factory, _, clock = reader_env
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        login(a)
        b.cookies.set("__Host-reader", a.cookies.get("__Host-reader"))
        clock[0] += 1
        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(c.get, "/reader/catalog") for c in (a, b)]
            assert [f.result().status_code for f in results] == [200, 200]
        login(b)
        clock[0] += 1
        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(c.get, "/reader/catalog") for c in (a, b)]
            assert [f.result().status_code for f in results] == [200, 200]
        assert all(r["seen"] == clock[0] for r in rows(postgres_reader))


def test_shared_refresh_last_reference_retired_once(reader_env, postgres_reader):
    factory, identity, _ = reader_env
    revoked = []

    async def revoke(token):
        revoked.append(token)

    identity.revoke = revoke
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        login(a)
        login(b)
        assert logout(a).status_code == 200
        assert revoked == []
        assert b.get("/reader/catalog").status_code == 200
        assert logout(b).status_code == 200
        assert revoked == ["synthetic-refresh"]
        assert query(
            postgres_reader, "SELECT completed FROM reader_session_retirements"
        ) == [{"completed": True}]
        # A provider must issue a fresh credential; a retired token cannot reappear.
        assert login(a).headers["location"] == "/reader/signin-failed"


def test_concurrent_last_references_do_not_lose_cleanup(reader_env, postgres_reader):
    factory, identity, _ = reader_env
    revoked, lock = [], Lock()

    async def revoke(token):
        with lock:
            revoked.append(token)

    identity.revoke = revoke
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        login(a)
        login(b)
        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(logout, c) for c in (a, b)]
            assert [f.result().status_code for f in results] == [200, 200]
        assert revoked == ["synthetic-refresh"]


def test_two_workers_renew_once(reader_env, postgres_reader, monkeypatch, mint):
    factory, identity, clock = reader_env
    entered, release = Event(), Event()
    calls = []

    async def renew(token):
        calls.append(token)
        entered.set()
        assert await asyncio.to_thread(release.wait, 4)
        return {
            "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
            "refresh_token": "rotation",
        }

    identity.renew = renew
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        login(a)
        b.cookies.set("__Host-reader", a.cookies.get("__Host-reader"))
        expire(clock, monkeypatch)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(a.get, "/reader/catalog")
            assert entered.wait(3)
            second = pool.submit(b.get, "/reader/catalog")
            release.set()
            assert [f.result().status_code for f in (first, second)] == [200, 200]
        assert calls == ["synthetic-refresh"]
        assert rows(postgres_reader)[0]["credential_version"] == 2


@pytest.mark.parametrize("boundary", ["absolute", "idle", "logout"])
def test_renewal_rechecks_lifetime_and_logout(
    reader_env, postgres_reader, monkeypatch, mint, boundary
):
    factory, identity, clock = reader_env
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        login(a)
        if boundary == "logout":
            identity.tokens = {
                "access_token": mint(exp=int(clock[0]) + 86400),
                "refresh_token": "other-device",
            }
            login(b)
        else:
            b.cookies.set("__Host-reader", a.cookies.get("__Host-reader"))
        csrf = b.get("/reader/session").json()["csrf"]
        expire(clock, monkeypatch)
        if boundary == "absolute":
            query(
                postgres_reader,
                "UPDATE reader_device_sessions SET created=%s,seen=%s",
                (clock[0] - LIFETIME + 1, clock[0]),
            )
        elif boundary == "idle":
            query(
                postgres_reader,
                "UPDATE reader_device_sessions SET seen=%s",
                (clock[0] - 7 * 86400 + 1,),
            )
        revoked = []

        async def revoke(token):
            revoked.append(token)

        async def renew(token):
            if boundary == "logout":
                response = await asyncio.to_thread(
                    b.post,
                    "/reader/logout",
                    json={"scope": "all", "csrf": csrf},
                    headers={"Origin": "https://reader.example"},
                )
                assert response.status_code == 200
            else:
                clock[0] += 2
            return {
                "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
                "refresh_token": "rejected-rotation",
            }

        identity.renew, identity.revoke = renew, revoke
        assert a.get("/reader/catalog").status_code == 401
        assert all(row["ended"] for row in rows(postgres_reader))
        assert "rejected-rotation" in revoked


def test_timestamp_claim_does_not_include_provider_wait(
    reader_env, postgres_reader, monkeypatch, mint
):
    factory, identity, clock = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        expire(clock, monkeypatch)
        admission = clock[0]

        async def renew(token):
            clock[0] += 2
            return {"access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600)}

        identity.renew = renew
        assert client.get("/reader/catalog").status_code == 200
        assert rows(postgres_reader)[0]["seen"] == admission


def test_touch_lock_timeout_is_redacted_and_fail_closed(reader_env, postgres_reader):
    factory, _, clock = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        clock[0] += 1
        before = rows(postgres_reader)
        with psycopg.connect(postgres_reader.conninfo) as blocker:
            blocker.execute("SELECT * FROM reader_session_owners FOR UPDATE")
            response = client.get("/reader/catalog")
            assert response.status_code == 503
            assert "Beans" not in response.text
            assert "reader_session_owners" not in response.text
            assert response.headers["x-reader-failure"].startswith("session_storage")
        assert rows(postgres_reader) == before
        assert client.get("/reader/catalog").status_code == 200


def test_failed_revoke_is_durable_and_retried(reader_env, postgres_reader, mint):
    factory, identity, clock = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        identity.refused = True
        assert logout(client).status_code == 200
        assert query(
            postgres_reader, "SELECT completed FROM reader_session_retirements"
        ) == [{"completed": False}]
        identity.refused = False
        identity.tokens = {"access_token": mint(), "refresh_token": "fresh-login"}
        clock[0] += 11
        assert login(client).status_code == 303
        assert query(
            postgres_reader, "SELECT completed FROM reader_session_retirements"
        ) == [{"completed": True}]


def test_new_encryption_epoch_cannot_admit_previous_sessions(
    reader_env, postgres_reader
):
    from cryptography.fernet import Fernet

    from cookbook.reader_sessions import Access, SignIn
    from cookbook.reader_sessions_postgres import PostgresSessionBook

    factory, _, _ = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        reader = postgres_reader.readers[0]
        fresh = Fernet.generate_key()
        replacement = PostgresSessionBook(
            postgres_reader.conninfo,
            Fernet(fresh),
            reader.verifier,
            reader.identity,
            fresh,
        )
        try:
            result = asyncio.run(
                replacement.authorize(
                    client.cookies.get("__Host-reader"), Access.PASSIVE
                )
            )
            assert isinstance(result, SignIn)
        finally:
            asyncio.run(replacement.close())


def test_stale_lease_never_replays_refresh(reader_env, postgres_reader):
    factory, identity, clock = reader_env

    async def forbidden(token):
        pytest.fail("stale refresh lease was replayed")

    identity.renew = forbidden
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        query(
            postgres_reader,
            "UPDATE reader_device_sessions SET lease='abandoned',renewing=%s",
            (clock[0] - 10,),
        )
        assert client.get("/reader/catalog").status_code == 401
        assert client.get("/reader/session").status_code == 401


def test_provider_timeout_never_replays_exchange(
    reader_env, postgres_reader, monkeypatch
):
    factory, identity, clock = reader_env
    calls = []

    async def stalled(token):
        calls.append(token)
        await asyncio.sleep(1)

    identity.renew = stalled
    monkeypatch.setattr("cookbook.reader_sessions_postgres.PROVIDER_TIMEOUT", 0.02)
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        expire(clock, monkeypatch)
        assert client.get("/reader/catalog").status_code == 401
        assert client.get("/reader/catalog").status_code == 401
        assert calls == ["synthetic-refresh"]


@pytest.mark.parametrize("committed", [False, True])
def test_lost_settlement_acknowledgement(
    reader_env, postgres_reader, monkeypatch, mint, committed
):
    from cookbook.reader_diagnostics import Stage

    factory, identity, clock = reader_env
    calls, revoked = [], []

    async def renew(token):
        calls.append(token)
        return {
            "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
            "refresh_token": "rotated-with-lost-ack",
        }

    async def revoke(token):
        revoked.append(token)

    identity.renew, identity.revoke = renew, revoke
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        expire(clock, monkeypatch)
        book = postgres_reader.readers[0].sessions
        original = book._run
        fired = False

        async def ambiguous(at, operation, **kwargs):
            nonlocal fired
            if at is Stage.RENEWAL_SETTLE and not fired:
                fired = True
                if committed:
                    await original(at, operation, **kwargs)
                raise OSError("private database acknowledgement sentinel")
            return await original(at, operation, **kwargs)

        monkeypatch.setattr(book, "_run", ambiguous)
        response = client.get("/reader/catalog")
        assert response.status_code == (200 if committed else 503)
        assert "private database" not in response.text
        assert calls == ["synthetic-refresh"]
        if committed:
            assert revoked == []
            assert client.get("/reader/session").status_code == 200
        else:
            assert revoked == ["rotated-with-lost-ack"]
            clock[0] += 10
            assert client.get("/reader/session").status_code == 401
            assert calls == ["synthetic-refresh"]


def test_ambiguous_touch_does_not_run_handler(reader_env, postgres_reader, monkeypatch):
    from cookbook.reader_diagnostics import Stage

    factory, _, clock = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        clock[0] += 1
        book = postgres_reader.readers[0].sessions
        original = book._run

        async def ambiguous(at, operation, **kwargs):
            result = await original(at, operation, **kwargs)
            if at is Stage.SESSION_WRITE:
                raise OSError("private touch acknowledgement")
            return result

        monkeypatch.setattr(book, "_run", ambiguous)
        response = client.get("/reader/catalog")
        assert response.status_code == 503
        assert "Beans" not in response.text
        assert rows(postgres_reader)[0]["seen"] == clock[0]
        assert client.get("/reader/session").status_code == 200


def test_logout_wins_over_waiting_activity(reader_env, postgres_reader, monkeypatch):
    factory, _, clock = reader_env
    loaded, release = Event(), Event()
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        login(a)
        b.cookies.set("__Host-reader", a.cookies.get("__Host-reader"))
        book = postgres_reader.readers[0].sessions
        original = book._admit

        async def pause(*args):
            loaded.set()
            assert await asyncio.to_thread(release.wait, 4)
            return await original(*args)

        monkeypatch.setattr(book, "_admit", pause)
        clock[0] += 1
        with ThreadPoolExecutor(1) as pool:
            active = pool.submit(a.get, "/reader/catalog")
            assert loaded.wait(3)
            assert logout(b, "all").status_code == 200
            release.set()
            assert active.result().status_code == 401
        assert all(row["ended"] for row in rows(postgres_reader))


def test_database_clock_and_durable_configuration(reader_env, postgres_reader):
    factory, _, _ = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        reader = postgres_reader.readers[0]
        reader.sessions._clock = None
        before = query(
            postgres_reader,
            "SELECT extract(epoch FROM clock_timestamp())::float8 AS now",
        )[0]["now"]
        assert login(client).status_code == 303
        assert client.get("/reader/catalog").status_code == 200
        after = query(
            postgres_reader,
            "SELECT extract(epoch FROM clock_timestamp())::float8 AS now",
        )[0]["now"]
        stored = rows(postgres_reader)[0]
        assert before <= stored["created"] <= stored["seen"] <= after
        assert query(
            postgres_reader,
            "SELECT current_setting('fsync') AS fsync,current_setting('synchronous_commit') AS commit",
        ) == [{"fsync": "on", "commit": "on"}]


def test_concurrent_sign_in_and_all_device_logout(reader_env, postgres_reader, mint):
    factory, identity, _ = reader_env
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        login(a)
        identity.tokens = {
            "access_token": mint(),
            "refresh_token": "concurrent-sign-in",
        }
        with ThreadPoolExecutor(2) as pool:
            ending = pool.submit(logout, a, "all")
            beginning = pool.submit(login, b)
            assert ending.result().status_code == 200
            assert beginning.result().status_code == 303
        generation = query(
            postgres_reader, "SELECT generation FROM reader_session_owners"
        )[0]["generation"]
        assert generation == 2
        for row in rows(postgres_reader):
            assert row["ended"] or row["generation"] == generation
        key = hashlib.sha256(b.cookies.get("__Host-reader", "").encode()).hexdigest()
        response = b.get("/reader/session")
        live = any(
            r["key"] == key and not r["ended"] and r["generation"] == generation
            for r in rows(postgres_reader)
        )
        assert response.status_code == (200 if live else 401)


def test_expiry_removal_rechecks_concurrent_activity(
    reader_env, postgres_reader, monkeypatch
):
    factory, _, clock = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        clock[0] += 7 * 86400
        book = postgres_reader.readers[0].sessions
        original = book._drop
        fired = False

        async def after_touch(*args, **kwargs):
            nonlocal fired
            if not fired:
                fired = True
                query(
                    postgres_reader,
                    "UPDATE reader_device_sessions SET seen=%s",
                    (clock[0],),
                )
            return await original(*args, **kwargs)

        monkeypatch.setattr(book, "_drop", after_touch)
        assert client.get("/reader/catalog").status_code == 200
        assert not rows(postgres_reader)[0]["ended"]


def test_database_restart_retains_session_and_logout(reader_env, postgres_reader):
    factory, _, _ = reader_env
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        login(a)
        login(b)
        live_cookie = a.cookies.get("__Host-reader")
        ended_cookie = b.cookies.get("__Host-reader")
        assert logout(b).status_code == 200
    data = Path(
        query(postgres_reader, "SELECT current_setting('data_directory') AS path")[0][
            "path"
        ]
    )
    binary = Path(os.environ["READER_TRIAL_PG_BIN"]) / "pg_ctl"
    subprocess.run(
        [
            str(binary),
            "-D",
            str(data),
            "-l",
            str(data.parent / "postgres.log"),
            "-m",
            "immediate",
            "-w",
            "restart",
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    with (
        TestClient(factory(), base_url="https://reader.example") as a,
        TestClient(factory(), base_url="https://reader.example") as b,
    ):
        a.cookies.set("__Host-reader", live_cookie)
        b.cookies.set("__Host-reader", ended_cookie)
        assert a.get("/reader/catalog").status_code == 200
        assert b.get("/reader/catalog").status_code == 401


def test_settlement_rejects_expired_lease_after_verification_wait(
    reader_env, postgres_reader, monkeypatch, mint
):
    factory, identity, clock = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        expire(clock, monkeypatch)
        reader = postgres_reader.readers[0]
        renewed = mint(iat=int(clock[0]), exp=int(clock[0]) + 600)
        verify = reader.verifier.verify_token

        async def delayed(raw, **kwargs):
            result = await verify(raw, **kwargs)
            if raw == renewed:
                clock[0] += 10
            return result

        identity.renewed_tokens = {
            "access_token": renewed,
            "refresh_token": "stale-settlement",
        }
        monkeypatch.setattr(reader.verifier, "verify_token", delayed)
        assert client.get("/reader/catalog").status_code == 401
        assert rows(postgres_reader)[0]["ended"]
