"""Explicit session schema provisioning and production startup checks.

Runtime never migrates. CLI credentials come from a private file, never argv.
"""

import argparse
import hashlib
import json
import stat
from pathlib import Path

import psycopg
from psycopg import sql

VERSION = 1
TABLES = (
    "reader_session_owners",
    "reader_device_sessions",
    "reader_session_exchanges",
    "reader_session_retirements",
)
META = "reader_session_schema_version"


class PreflightRefused(ValueError):
    """A fixed operator-readable refusal containing no connection details."""


def _schema():
    raw = Path(__file__).with_name("reader_session_schema.sql").read_bytes()
    return raw.decode(), hashlib.sha256(raw).hexdigest()


def _no_role_memberships(conn, role):
    # The runtime receives direct grants. Reject all memberships, including
    # NOINHERIT/SET-false grants whose ADMIN option can enable escalation.
    if conn.execute(
        "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname<>%s AND pg_has_role(%s,oid,'MEMBER'))",
        (role, role),
    ).fetchone()[0]:
        raise PreflightRefused(
            "Session runtime login must not assume another role or hold role memberships"
        )


def initialize(conninfo, runtime_role):
    """Administrator-only, atomic and repeatable on an empty dedicated database."""
    ddl, digest = _schema()
    with psycopg.connect(
        conninfo,
        connect_timeout=5,
        options="-c statement_timeout=5000 -c search_path=public,pg_catalog",
    ) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(1340701)")
        if conn.execute("SELECT pg_is_in_recovery()").fetchone()[0]:
            raise PreflightRefused("Session provisioning requires the primary")
        if (
            conn.execute(
                "SELECT to_regclass('public.reader_session_schema_version')"
            ).fetchone()[0]
            is None
        ):
            if any(
                conn.execute("SELECT to_regclass(%s)", ("public." + table,)).fetchone()[
                    0
                ]
                for table in TABLES
            ):
                raise PreflightRefused("Refusing an unversioned session schema")
            conn.execute(ddl)
            conn.execute(
                "CREATE TABLE public.reader_session_schema_version (singleton boolean PRIMARY KEY CHECK(singleton), version integer NOT NULL, digest text NOT NULL)"
            )
            conn.execute(
                "INSERT INTO public.reader_session_schema_version VALUES(true,%s,%s)",
                (VERSION, digest),
            )
        stored = conn.execute(
            "SELECT version,digest FROM public.reader_session_schema_version"
        ).fetchall()
        if stored != [(VERSION, digest)]:
            raise PreflightRefused("Unsupported session schema version")
        role = conn.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s",
            (runtime_role,),
        ).fetchone()
        if role is None or any(role):
            raise PreflightRefused("Provision a restricted runtime login first")
        _no_role_memberships(conn, runtime_role)
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                sql.Identifier(runtime_role)
            )
        )
        for table in TABLES:
            conn.execute(
                sql.SQL(
                    "GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.{} TO {}"
                ).format(sql.Identifier(table), sql.Identifier(runtime_role))
            )
        conn.execute(
            sql.SQL("GRANT SELECT ON TABLE public.{} TO {}").format(
                sql.Identifier(META), sql.Identifier(runtime_role)
            )
        )


def preflight(conninfo):
    """Check production authority without writing or revealing connection details."""
    _, digest = _schema()
    with psycopg.connect(
        conninfo,
        connect_timeout=5,
        autocommit=True,
        options="-c statement_timeout=3000 -c synchronous_commit=on -c search_path=pg_catalog,public",
    ) as conn:
        state = conn.execute(
            "SELECT pg_is_in_recovery(), current_setting('transaction_read_only'), current_setting('fsync'),current_setting('synchronous_commit')"
        ).fetchone()
        if state != (False, "off", "on", "on"):
            raise PreflightRefused(
                "Session database requires a durable writable primary"
            )
        role = conn.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if any(role):
            raise PreflightRefused(
                "Session runtime login has administrative privileges"
            )
        _no_role_memberships(conn, conn.execute("SELECT current_user").fetchone()[0])
        ddl = conn.execute(
            "SELECT has_database_privilege(current_database(),'CREATE'),has_schema_privilege('public','CREATE')"
        ).fetchone()
        if any(ddl):
            raise PreflightRefused(
                "Session runtime login must not create database objects"
            )
        if (
            conn.execute(
                "SELECT to_regclass('public.reader_session_schema_version')"
            ).fetchone()[0]
            is None
        ):
            raise PreflightRefused("Session database schema is not initialized")
        if not conn.execute(
            "SELECT has_table_privilege(%s,%s)", ("public." + META, "SELECT")
        ).fetchone()[0]:
            raise PreflightRefused(
                "Session runtime login lacks required table privileges"
            )
        if conn.execute(
            "SELECT version,digest FROM public.reader_session_schema_version"
        ).fetchall() != [(VERSION, digest)]:
            raise PreflightRefused("Unsupported session schema version")
        if conn.execute(
            "SELECT has_table_privilege(%s,%s)",
            ("public." + META, "INSERT,UPDATE,DELETE,TRUNCATE"),
        ).fetchone()[0]:
            raise PreflightRefused("Session runtime login can change schema metadata")
        for table in (*TABLES, META):
            row = conn.execute(
                "SELECT relpersistence FROM pg_class WHERE oid=to_regclass(%s)",
                ("public." + table,),
            ).fetchone()
            if row != ("p",):
                raise PreflightRefused("Session authority requires logged tables")
            for privilege in (
                ("SELECT",)
                if table == META
                else ("SELECT", "INSERT", "UPDATE", "DELETE")
            ):
                if not conn.execute(
                    "SELECT has_table_privilege(%s,%s)", ("public." + table, privilege)
                ).fetchone()[0]:
                    raise PreflightRefused(
                        "Session runtime login lacks required table privileges"
                    )
    return {"schema_version": VERSION, "primary": True, "restricted_role": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["initialize", "check"])
    parser.add_argument("--dsn-file", type=Path, required=True)
    parser.add_argument("--runtime-role")
    args = parser.parse_args()
    if args.action == "initialize" and not args.runtime_role:
        parser.error("initialize requires --runtime-role")
    try:
        info = args.dsn_file.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise PreflightRefused("Credentials file must be private")
        dsn = args.dsn_file.read_text().strip()
        if args.action == "initialize":
            initialize(dsn, args.runtime_role)
            result = {"schema_version": VERSION, "initialized": True}
        else:
            result = preflight(dsn)
    except PreflightRefused as error:
        print(
            json.dumps(
                {"status": "refused", "action": args.action, "reason": str(error)}
            )
        )
        return 1
    except Exception:  # noqa: BLE001 - administrative boundary must not print URLs or driver errors
        print(json.dumps({"status": "failed", "action": args.action}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
