"""Synthetic owner reporting through the assembled authenticated HTTP boundary."""

import re
from html import unescape

from starlette.testclient import TestClient
from test_reader_content import destination, publish_scanned
from test_reader_http import login

from cookbook.storage import LocalStore

pytest_plugins = ["test_reader_http"]


def test_description_only_receipt_survives_restart_and_original_failure(
    reader_env, published, tmp_path
):
    from cookbook.owner_reports import OwnerReports

    pub, source = publish_scanned(published, tmp_path)
    app, _, _ = reader_env
    store = LocalStore(tmp_path / "owner-reports")
    at = destination(pub, source, section_id="section-0")
    with TestClient(
        app(owner_reports=OwnerReports(store)), base_url="https://reader.example"
    ) as client:
        login(client)
        page = client.get("/reader/read", params={"at": at})
        ref = unescape(re.search(r'name="reference" value="([^"]+)"', page.text)[1])
        csrf = client.get("/reader/session").json()["csrf"]
        assert client.get("/reader/nonexistent-original").status_code == 404
        payload = {
            "csrf": csrf,
            "reference": ref,
            "submission_id": "a" * 32,
            "description": "Amount appears incomplete.",
        }
        received = client.post(
            "/reader/reports",
            json=payload,
            headers={"Origin": "https://reader.example"},
        )
        assert received.status_code == 200
        assert received.json()["status"] == "received"
        cookies = client.cookies
    with TestClient(
        app(owner_reports=OwnerReports(store)),
        base_url="https://reader.example",
        cookies=cookies,
    ) as client:
        retry = client.post(
            "/reader/reports",
            json=payload,
            headers={"Origin": "https://reader.example"},
        )
        assert retry.json() == received.json()
        changed = client.post(
            "/reader/reports",
            json={**payload, "description": "Different"},
            headers={"Origin": "https://reader.example"},
        )
        assert changed.status_code == 409
        assert "Synthetic soup" in client.get("/reader/read", params={"at": at}).text


def test_retired_binding_ambiguous_write_limits_and_expiry(
    reader_env, published, tmp_path, monkeypatch
):
    from starlette.responses import Response
    from starlette.routing import Route

    from cookbook.owner_reports import OwnerReports

    pub, source = publish_scanned(published, tmp_path)
    factory, _, clock = reader_env
    store = LocalStore(tmp_path / "observations")
    sink = OwnerReports(store, max_per_hour=1)
    app = factory(owner_reports=sink)
    app.routes.insert(
        0,
        Route("/synthetic-failed-original", lambda request: Response(status_code=503)),
    )
    at = destination(pub, source, section_id="section-0")
    with TestClient(app, base_url="https://reader.example") as client:
        login(client)
        page = client.get("/reader/read", params={"at": at})
        ref = unescape(re.search(r'name="reference" value="([^"]+)"', page.text)[1])
        payload = {
            "csrf": client.get("/reader/session").json()["csrf"],
            "reference": ref,
            "submission_id": "b" * 32,
            "description": "Original unavailable; quantity seems incomplete.",
        }
        headers = {"Origin": "https://reader.example"}
        assert client.get("/synthetic-failed-original").status_code == 503
        # The original is independently failed; report submission never requests it.
        (published[3].root / "versions" / pub / "manifest.json").unlink()
        assert client.get("/reader/read", params={"at": at}).status_code == 410
        original_put = store.put_bytes

        def ambiguous(key, data, expected=None):
            result = original_put(key, data, expected)
            if "/receipts/" in key:
                raise TimeoutError("private backend detail")
            return result

        monkeypatch.setattr(store, "put_bytes", ambiguous)
        unconfirmed = client.post("/reader/reports", json=payload, headers=headers)
        assert (
            unconfirmed.status_code == 503
            and unconfirmed.json()["error"] == "receipt_unconfirmed"
        )
        assert "private backend" not in unconfirmed.text
        received = client.post("/reader/reports", json=payload, headers=headers)
        assert received.status_code == 200 and received.json()["status"] == "received"
        limited = client.post(
            "/reader/reports",
            json={**payload, "submission_id": "c" * 32},
            headers=headers,
        )
        assert limited.status_code == 429 and limited.headers["retry-after"]
        assert (
            client.post("/reader/reports", json=payload, headers=headers).json()
            == received.json()
        )
        clock[0] += 31 * 86400
        assert (
            client.post("/reader/reports", json=payload, headers=headers).status_code
            == 401
        )


def test_reporting_authorization_validation_and_unavailable(
    reader_env, published, tmp_path
):
    pub, source = publish_scanned(published, tmp_path)
    factory, _, _ = reader_env
    at = destination(pub, source, section_id="section-0")
    with TestClient(factory(), base_url="https://reader.example") as client:
        assert client.post("/reader/reports", json={}).status_code == 401
        login(client)
        page = client.get("/reader/read", params={"at": at})
        ref = unescape(re.search(r'name="reference" value="([^"]+)"', page.text)[1])
        payload = {
            "csrf": client.get("/reader/session").json()["csrf"],
            "reference": ref,
            "submission_id": "d" * 32,
            "description": "Suspected amount error",
        }
        headers = {"Origin": "https://reader.example"}
        assert client.post("/reader/reports", json=payload).status_code == 403
        assert (
            client.post(
                "/reader/reports", json={**payload, "csrf": "wrong"}, headers=headers
            ).status_code
            == 403
        )
        for change in (
            {"reference": at},
            {"description": ""},
            {"description": "x" * 1001},
            {"region": [0, 0, 2, 2]},
        ):
            assert (
                client.post(
                    "/reader/reports", json={**payload, **change}, headers=headers
                ).status_code
                == 400
            )
        unavailable = client.post("/reader/reports", json=payload, headers=headers)
        assert (
            unavailable.status_code == 503
            and unavailable.json()["error"] == "reporting_unavailable"
        )


def test_hosted_owner_storage_requires_distinct_complete_authority(
    monkeypatch, keys, tmp_path
):
    import pytest
    from cryptography.fernet import Fernet

    from cookbook.hosted import reader_from_environment
    from cookbook.server import JWTVerifier

    settings = {
        "READER_ORIGIN": "https://reader.example",
        "READER_CLIENT_ID": "web",
        "READER_CLIENT_SECRET": "secret",
        "READER_SESSION_KEY": Fernet.generate_key().decode(),
        "READER_S3_BUCKET": "sessions",
        "READER_AWS_ACCESS_KEY_ID": "session-key",
        "READER_AWS_SECRET_ACCESS_KEY": "secret",
        "S3_BUCKET": "library",
        "AWS_ACCESS_KEY_ID": "library-key",
        "S3_ENDPOINT_URL": "https://storage.example",
        "OWNER_REPORTS_S3_BUCKET": "observations",
        "OWNER_REPORTS_AWS_ACCESS_KEY_ID": "owner-report-key",
        "OWNER_REPORTS_AWS_SECRET_ACCESS_KEY": "secret",
        "REPORTS_S3_BUCKET": "legacy-reports",
        "REPORTS_AWS_ACCESS_KEY_ID": "legacy-key",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "cookbook.hosted.s3_store",
        lambda endpoint, bucket, *args: LocalStore(tmp_path / bucket),
    )
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://reader.example/mcp",
        subjects=["user-1"],
        public_key=keys[1],
    )
    assert reader_from_environment(verifier).owner_reports is not None
    for bucket in ("sessions", "library", "legacy-reports"):
        monkeypatch.setenv("OWNER_REPORTS_S3_BUCKET", bucket)
        with pytest.raises(ValueError, match="separate"):
            reader_from_environment(verifier)
    monkeypatch.setenv("OWNER_REPORTS_S3_BUCKET", "observations")
    for key in ("session-key", "library-key", "legacy-key"):
        monkeypatch.setenv("OWNER_REPORTS_AWS_ACCESS_KEY_ID", key)
        with pytest.raises(ValueError, match="separate"):
            reader_from_environment(verifier)
    monkeypatch.delenv("OWNER_REPORTS_AWS_SECRET_ACCESS_KEY")
    with pytest.raises(ValueError, match="incomplete"):
        reader_from_environment(verifier)


def test_receipt_waits_for_durability_and_concurrent_retry_is_atomic(
    reader_env, published, tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from cookbook.owner_reports import OwnerReports

    pub, source = publish_scanned(published, tmp_path)
    factory, _, _ = reader_env
    store = LocalStore(tmp_path / "atomic-reports")
    sink = OwnerReports(store)
    writing, release = threading.Event(), threading.Event()
    original_put = store.put_bytes
    lock = threading.Lock()
    held = [False]

    def delayed(key, data, expected=None):
        with lock:
            pause = "/receipts/" in key and not held[0]
            if pause:
                held[0] = True
        if pause:
            writing.set()
            assert release.wait(5)
        return original_put(key, data, expected)

    monkeypatch.setattr(store, "put_bytes", delayed)
    with TestClient(
        factory(owner_reports=sink), base_url="https://reader.example"
    ) as client:
        login(client)
        page = client.get(
            "/reader/read",
            params={"at": destination(pub, source, section_id="section-0")},
        )
        ref = unescape(re.search(r'name="reference" value="([^"]+)"', page.text)[1])
        payload = {
            "reference": ref,
            "csrf": client.get("/reader/session").json()["csrf"],
            "submission_id": "e" * 32,
            "description": "Suspected quantity error",
        }

        def send():
            return client.post(
                "/reader/reports",
                json=payload,
                headers={"Origin": "https://reader.example"},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(send)
            try:
                assert writing.wait(3)
                assert (
                    not first.done()
                )  # No receipt while persistence is still pending.
                second = pool.submit(send).result(timeout=4)
                assert second.status_code == 200
            finally:
                release.set()
            result = first.result(timeout=4)
            assert result.status_code == 200 and result.json() == second.json()
