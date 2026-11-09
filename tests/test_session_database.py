"""Real provisioning/role checks on the disposable serving-only PostgreSQL cluster."""

import os

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.conninfo import make_conninfo

from cookbook.session_database import initialize, preflight


@pytest.mark.parametrize(
    "target",
    [
        "host=localhost sslmode=verify-full",
        "host=ep-synthetic.us-west-2.aws.neon.tech sslmode=require",
        "host=ep-synthetic-pooler.us-west-2.aws.neon.tech sslmode=verify-full",
        "host=ep-synthetic.us-west-2.aws.neon.tech.attacker.example sslmode=verify-full",
        "host=ep-synthetic.us-west-2.aws.neon.tech hostaddr=127.0.0.1 sslmode=verify-full",
        "host=ep-synthetic.us-west-2.aws.neon.tech service=other sslmode=verify-full",
        "host=ep-synthetic.us-west-2.aws.neon.tech,localhost sslmode=verify-full",
    ],
)
def test_neon_policy_rejects_unsafe_targets_before_connecting(monkeypatch, target):
    def unexpected(*args, **kwargs):
        pytest.fail("Unsafe Neon target reached a database connection")

    monkeypatch.setattr(psycopg, "connect", unexpected)
    with pytest.raises(ValueError, match="direct AWS Neon endpoint with verified TLS"):
        preflight(target, durability="neon")


def test_unknown_durability_policy_is_refused_before_connecting(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Unknown policy reached a database connection")

    monkeypatch.setattr(psycopg, "connect", unexpected)
    with pytest.raises(ValueError, match="Unsupported session durability"):
        preflight("", durability="other")


@pytest.mark.parametrize(
    "state,neon,tls,policy,message",
    [
        (
            (False, "off", "off", "on"),
            ("walproposer", "tenant", "timeline"),
            True,
            "postgres",
            "durable writable primary",
        ),
        (
            (True, "on", "off", "on"),
            ("walproposer", "tenant", "timeline"),
            True,
            "neon",
            "durable writable primary",
        ),
        (
            (False, "off", "off", "off"),
            ("walproposer", "tenant", "timeline"),
            True,
            "neon",
            "durable writable primary",
        ),
        (
            (False, "off", "off", "on"),
            ("", "tenant", "timeline"),
            True,
            "neon",
            "Neon session storage",
        ),
        (
            (False, "off", "off", "on"),
            ("walproposer", None, "timeline"),
            True,
            "neon",
            "Neon session storage",
        ),
        (
            (False, "off", "off", "on"),
            ("walproposer", "tenant", None),
            True,
            "neon",
            "Neon session storage",
        ),
        (
            (False, "off", "off", "on"),
            ("walproposer", "tenant", "timeline"),
            False,
            "neon",
            "Neon session storage",
        ),
    ],
)
def test_durability_checks_fail_closed_on_server_mismatch(
    monkeypatch, state, neon, tls, policy, message
):
    from types import SimpleNamespace

    class Connection:
        pgconn = SimpleNamespace(ssl_in_use=tls)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query):
            result = state if "pg_is_in_recovery" in query else neon
            return SimpleNamespace(fetchone=lambda: result)

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: Connection())
    with pytest.raises(ValueError, match=message):
        preflight(
            "host=ep-synthetic.us-west-2.aws.neon.tech sslmode=verify-full",
            durability=policy,
        )


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


def test_startup_rejects_admin_membership_with_set_initially_disabled(database):
    admin, runtime = database
    initialize(admin, "reader_runtime")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("CREATE ROLE nonset_admin_role NOLOGIN")
        conn.execute(
            "ALTER TABLE reader_session_schema_version OWNER TO nonset_admin_role"
        )
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                "GRANT nonset_admin_role TO reader_runtime WITH ADMIN TRUE, SET FALSE, INHERIT FALSE"
            )
        with psycopg.connect(runtime) as conn:
            assert conn.execute(
                "SELECT pg_has_role(current_user,'nonset_admin_role','SET')"
            ).fetchone() == (False,)
        with pytest.raises(ValueError, match="role memberships"):
            preflight(runtime)
        # ADMIN can enable SET even when it was initially false.
        with psycopg.connect(runtime) as conn:
            conn.execute("GRANT nonset_admin_role TO reader_runtime WITH SET TRUE")
            conn.execute("SET ROLE nonset_admin_role")
            conn.execute("UPDATE reader_session_schema_version SET version=version")
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("REASSIGN OWNED BY nonset_admin_role TO reader_trial")
            conn.execute("DROP ROLE nonset_admin_role")


def test_cli_reports_fixed_refusal_reason(database, tmp_path, monkeypatch, capsys):
    import sys

    from cookbook.session_database import main

    admin, runtime = database
    initialize(admin, "reader_runtime")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("UPDATE reader_session_schema_version SET version=2")
    secret = tmp_path / "dsn"
    secret.write_text(runtime)
    secret.chmod(0o600)
    monkeypatch.setattr(
        sys, "argv", ["session_database", "check", "--dsn-file", str(secret)]
    )
    assert main() == 1
    output = capsys.readouterr().out
    assert "Unsupported session schema version" in output
    assert runtime not in output


@pytest.mark.parametrize(
    "signature,result,ending",
    [
        ("pg_is_in_recovery()", "boolean", "RETURN false;"),
        ("pg_advisory_xact_lock(integer)", "void", "RETURN;"),
    ],
)
def test_initializer_does_not_execute_public_shadow_functions(
    database, signature, result, ending
):
    admin, runtime = database
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("CREATE TABLE initializer_canary(actor text)")
        conn.execute("GRANT INSERT ON initializer_canary TO reader_runtime")
        conn.execute("GRANT CREATE ON SCHEMA public TO reader_runtime")
    try:
        with psycopg.connect(runtime, autocommit=True) as conn:
            conn.execute(
                f"CREATE FUNCTION public.{signature} RETURNS {result} "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "INSERT INTO public.initializer_canary VALUES(current_user); "
                f"{ending} END $$"
            )
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("REVOKE CREATE ON SCHEMA public FROM reader_runtime")
        initialize(admin, "reader_runtime")
        assert preflight(runtime)["restricted_role"]
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT * FROM initializer_canary").fetchall() == []
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
            conn.execute("DROP TABLE initializer_canary")
            conn.execute("REVOKE CREATE ON SCHEMA public FROM reader_runtime")


@pytest.mark.parametrize("scope", ["schema", "database"])
def test_initializer_refuses_runtime_object_creation_before_creating_schema(
    database, scope
):
    admin, _ = database
    from psycopg import sql

    with psycopg.connect(admin, autocommit=True) as conn:
        target = (
            sql.SQL("SCHEMA public")
            if scope == "schema"
            else sql.SQL("DATABASE {}").format(
                sql.Identifier(conn.execute("SELECT current_database()").fetchone()[0])
            )
        )
        conn.execute(sql.SQL("GRANT CREATE ON {} TO reader_runtime").format(target))
    try:
        with pytest.raises(ValueError, match="must not create database objects"):
            initialize(admin, "reader_runtime")
        with psycopg.connect(admin) as conn:
            assert conn.execute(
                "SELECT to_regclass('public.reader_session_owners')"
            ).fetchone() == (None,)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                sql.SQL("REVOKE CREATE ON {} FROM reader_runtime").format(target)
            )


@pytest.mark.parametrize(
    "table",
    [
        "reader_session_owners",
        "reader_device_sessions",
        "reader_session_exchanges",
        "reader_session_retirements",
        "reader_session_schema_version",
    ],
)
def test_preflight_rejects_runtime_table_ownership(database, table):
    from psycopg import sql

    admin, runtime = database
    initialize(admin, "reader_runtime")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL("ALTER TABLE public.{} OWNER TO reader_runtime").format(
                sql.Identifier(table)
            )
        )
    with pytest.raises(ValueError, match="must not own session tables"):
        preflight(runtime)


def test_initializer_refuses_untrusted_metadata_before_selecting_it(database):
    admin, runtime = database
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("CREATE TABLE initializer_canary(actor text)")
        conn.execute("GRANT INSERT ON initializer_canary TO reader_runtime")
        conn.execute("GRANT CREATE ON SCHEMA public TO reader_runtime")
    try:
        with psycopg.connect(runtime, autocommit=True) as conn:
            conn.execute(
                "CREATE FUNCTION public.provisioning_trap() RETURNS text "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "INSERT INTO public.initializer_canary VALUES(current_user); "
                "RETURN 'synthetic'; END $$"
            )
            conn.execute(
                "CREATE VIEW reader_session_schema_version AS "
                "SELECT 1 AS version,public.provisioning_trap() AS digest"
            )
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("REVOKE CREATE ON SCHEMA public FROM reader_runtime")
        with pytest.raises(ValueError, match="owned by the provisioning login"):
            initialize(admin, "reader_runtime")
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT * FROM initializer_canary").fetchall() == []
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("DROP VIEW IF EXISTS reader_session_schema_version")
            conn.execute("DROP FUNCTION IF EXISTS public.provisioning_trap()")
            conn.execute("DROP TABLE initializer_canary")
            conn.execute("REVOKE CREATE ON SCHEMA public FROM reader_runtime")
