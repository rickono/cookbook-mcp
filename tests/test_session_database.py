"""Real provisioning/role checks on the disposable serving-only PostgreSQL cluster."""

import os

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.conninfo import make_conninfo

from cookbook.session_database import initialize, preflight


@pytest.fixture
def database():
    dsn = os.environ.get("READER_TRIAL_DATABASE")
    if not dsn:
        pytest.skip("Use scripts/try_postgres_reader.py")
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT current_setting('reader.local_trial',true)='on' AND inet_server_addr() IS NULL"
        ).fetchone() == (True,)
        conn.execute(
            "DROP TABLE IF EXISTS reader_session_retirements,reader_session_exchanges,reader_device_sessions,reader_session_owners,reader_session_schema_version CASCADE"
        )
        if not conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='reader_runtime'"
        ).fetchone():
            conn.execute(
                "CREATE ROLE reader_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
    return dsn, make_conninfo(dsn, user="reader_runtime")


def test_provisioning_is_repeatable_and_runtime_is_restricted(database):
    admin, runtime = database
    initialize(admin, "reader_runtime")
    initialize(admin, "reader_runtime")
    assert preflight(runtime) == {
        "schema_version": 1,
        "primary": True,
        "restricted_role": True,
    }
    with psycopg.connect(runtime, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO reader_session_owners(epoch,subject) VALUES('synthetic','user')"
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE public.forbidden_runtime_ddl(i int)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE reader_session_schema_version SET version=2")


def test_startup_rejects_administrator_and_changed_schema(database):
    admin, runtime = database
    initialize(admin, "reader_runtime")
    with pytest.raises(ValueError, match="administrative"):
        preflight(admin)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("UPDATE reader_session_schema_version SET version=2")
    with pytest.raises(ValueError, match="version"):
        preflight(runtime)
    with pytest.raises(ValueError, match="version"):
        initialize(admin, "reader_runtime")


def test_provisioning_does_not_adopt_existing_unversioned_tables(database):
    admin, _ = database
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("CREATE TABLE reader_session_owners(keep text)")
        conn.execute("INSERT INTO reader_session_owners VALUES('preserve')")
    with pytest.raises(ValueError, match="unversioned"):
        initialize(admin, "reader_runtime")
    with psycopg.connect(admin) as conn:
        assert conn.execute("SELECT * FROM reader_session_owners").fetchall() == [
            ("preserve",)
        ]


def test_startup_rejects_missing_runtime_privileges(database):
    admin, runtime = database
    initialize(admin, "reader_runtime")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("REVOKE UPDATE ON reader_device_sessions FROM reader_runtime")
    with pytest.raises(ValueError, match="privileges"):
        preflight(runtime)


def test_runtime_cannot_use_read_only_database_session(database):
    admin, runtime = database
    initialize(admin, "reader_runtime")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("ALTER ROLE reader_runtime SET default_transaction_read_only=on")
    try:
        with pytest.raises(ValueError, match="writable primary"):
            preflight(runtime)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                "ALTER ROLE reader_runtime RESET default_transaction_read_only"
            )


def test_cli_checks_private_credentials_file_without_echoing_it(
    database, tmp_path, monkeypatch, capsys
):
    import sys

    from cookbook.session_database import main

    admin, runtime = database
    initialize(admin, "reader_runtime")
    secret = tmp_path / "runtime-dsn"
    secret.write_text(runtime)
    secret.chmod(0o600)
    monkeypatch.setattr(
        sys, "argv", ["session_database", "check", "--dsn-file", str(secret)]
    )
    assert main() == 0
    assert "restricted_role" in capsys.readouterr().out
    secret.write_text("postgresql://PRIVATE-CREDENTIAL-SENTINEL")
    secret.chmod(0o644)
    assert main() == 1
    assert "PRIVATE-CREDENTIAL-SENTINEL" not in capsys.readouterr().out


def test_runtime_rejects_unlogged_authority_metadata(database):
    admin, runtime = database
    initialize(admin, "reader_runtime")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("ALTER TABLE reader_session_schema_version SET UNLOGGED")
    with pytest.raises(ValueError, match="logged"):
        preflight(runtime)


@pytest.mark.parametrize("indirect", [False, True])
def test_startup_rejects_set_role_privileges_even_with_noinherit(database, indirect):
    admin, runtime = database
    initialize(admin, "reader_runtime")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("CREATE ROLE schema_owner NOLOGIN")
        conn.execute("ALTER TABLE reader_session_schema_version OWNER TO schema_owner")
        conn.execute("ALTER ROLE reader_runtime NOINHERIT")
        if indirect:
            conn.execute("CREATE ROLE intermediate_role NOLOGIN NOINHERIT")
            conn.execute("GRANT schema_owner TO intermediate_role")
            conn.execute("GRANT intermediate_role TO reader_runtime")
        else:
            conn.execute("GRANT schema_owner TO reader_runtime")
    try:
        with psycopg.connect(runtime) as conn:
            conn.execute("SET ROLE schema_owner")
            conn.execute("UPDATE reader_session_schema_version SET version=version")
        with pytest.raises(ValueError, match="assume another role"):
            preflight(runtime)
        with pytest.raises(ValueError, match="assume another role"):
            initialize(admin, "reader_runtime")
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("ALTER ROLE reader_runtime INHERIT")
            conn.execute("REASSIGN OWNED BY schema_owner TO reader_trial")
            if indirect:
                conn.execute("DROP ROLE intermediate_role")
            conn.execute("DROP ROLE schema_owner")
