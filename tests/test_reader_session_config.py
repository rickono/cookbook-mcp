"""Hosted backend selection without constructing a pool or contacting a service."""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from cookbook.hosted import reader_from_environment

pytest.importorskip("psycopg")


@pytest.fixture
def configuration(monkeypatch):
    import os

    for name in list(os.environ):
        if name.startswith(("READER_", "PERSONAL_", "REPORTS_")):
            monkeypatch.delenv(name)
    for name, value in {
        "READER_ORIGIN": "https://reader.example",
        "READER_CLIENT_ID": "synthetic-client",
        "READER_CLIENT_SECRET": "synthetic-secret",
        "READER_SESSION_KEY": Fernet.generate_key().decode(),
        "READER_S3_BUCKET": "private-oauth",
        "READER_AWS_ACCESS_KEY_ID": "oauth-key",
        "READER_AWS_SECRET_ACCESS_KEY": "synthetic-secret",
        "S3_ENDPOINT_URL": "https://storage.example",
        "S3_BUCKET": "library",
        "AWS_ACCESS_KEY_ID": "read-only-library",
    }.items():
        monkeypatch.setenv(name, value)
    seen = []
    monkeypatch.setattr("cookbook.hosted.s3_store", lambda *args: object())
    monkeypatch.setattr(
        "cookbook.session_database.preflight", lambda dsn: {"primary": True}
    )

    def reader(*args, **kwargs):
        seen.append(kwargs)
        return object()

    monkeypatch.setattr("cookbook.reader.Reader", reader)
    return SimpleNamespace(audience="https://reader.example/mcp"), seen


@pytest.mark.parametrize("backend", [None, "r2", "postgres"])
def test_backend_is_explicit_and_legacy_default_is_preserved(
    configuration, monkeypatch, backend
):
    verifier, seen = configuration
    if backend:
        monkeypatch.setenv("READER_SESSION_BACKEND", backend)
    database = (
        "postgresql://synthetic-private-database" if backend == "postgres" else None
    )
    if database:
        monkeypatch.setenv("READER_SESSION_DATABASE_URL", database)
    assert reader_from_environment(verifier) is not None
    assert seen[0]["session_database"] == database


@pytest.mark.parametrize(
    "backend,database",
    [("other", None), ("postgres", None), ("r2", "postgresql://PRIVATE-SENTINEL")],
)
def test_incomplete_or_ambiguous_authority_configuration_stops_startup(
    configuration, monkeypatch, backend, database
):
    verifier, seen = configuration
    monkeypatch.setenv("READER_SESSION_BACKEND", backend)
    if database:
        monkeypatch.setenv("READER_SESSION_DATABASE_URL", database)
    with pytest.raises(ValueError) as error:
        reader_from_environment(verifier)
    assert "PRIVATE-SENTINEL" not in str(error.value)
    assert seen == []


def test_failed_database_preflight_stops_startup_without_leaking_url(
    configuration, monkeypatch
):
    verifier, seen = configuration
    monkeypatch.setenv("READER_SESSION_BACKEND", "postgres")
    monkeypatch.setenv("READER_SESSION_DATABASE_URL", "postgresql://PRIVATE-SENTINEL")

    def failed(dsn):
        raise OSError(dsn)

    monkeypatch.setattr("cookbook.session_database.preflight", failed)
    with pytest.raises(ValueError, match="startup checks") as error:
        reader_from_environment(verifier)
    assert "PRIVATE-SENTINEL" not in str(error.value)
    assert error.value.__suppress_context__
    assert seen == []


def test_fixed_database_refusal_explains_operator_action(configuration, monkeypatch):
    from cookbook.session_database import PreflightRefused

    verifier, seen = configuration
    monkeypatch.setenv("READER_SESSION_BACKEND", "postgres")
    monkeypatch.setenv("READER_SESSION_DATABASE_URL", "postgresql://PRIVATE-SENTINEL")

    def refused(dsn):
        raise PreflightRefused("Unsupported session schema version")

    monkeypatch.setattr("cookbook.session_database.preflight", refused)
    with pytest.raises(ValueError, match="Unsupported session schema version") as error:
        reader_from_environment(verifier)
    assert "PRIVATE-SENTINEL" not in str(error.value)
    assert seen == []
