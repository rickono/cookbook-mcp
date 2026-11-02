"""Personal metadata through assembled HTTP; synthetic sources only."""

import pytest
from starlette.testclient import TestClient
from test_reader_content import destination
from test_reader_http import login
from test_reader_updates import fixture_source

from cookbook.storage import LocalStore

pytest_plugins = ["test_reader_http"]


def test_bookmarks_cross_device_restart_and_idempotency(
    reader_env, published, tmp_path
):
    from cookbook.reader_personal import PersonalState

    factory, _, _ = reader_env
    store = LocalStore(tmp_path / "personal")
    at = destination(
        published[0].publication_id, fixture_source(published), section_id="section-0"
    )
    headers = {"Origin": "https://reader.example"}
    with (
        TestClient(
            factory(personal_state=PersonalState(store)),
            base_url="https://reader.example",
        ) as a,
        TestClient(
            factory(personal_state=PersonalState(store)),
            base_url="https://reader.example",
        ) as b,
    ):
        login(a)
        login(b)
        assert (
            'id="bookmark-save" method="post"'
            in a.get("/reader/read", params={"at": at}).text
        )
        csrf = a.get("/reader/session").json()["csrf"]
        payload = {
            "csrf": csrf,
            "action": "save",
            "operation_id": "a" * 32,
            "at": at,
            "name": "Beans",
        }
        result = a.post("/reader/personal", json=payload, headers=headers)
        assert result.status_code == 200 and result.json()["status"] == "saved"
        assert (
            a.post("/reader/personal", json=payload, headers=headers).json()
            == result.json()
        )
        assert (
            a.post(
                "/reader/personal", json={**payload, "name": "Changed"}, headers=headers
            ).status_code
            == 409
        )
        rows = b.get("/reader/personal").json()["bookmarks"]
        assert (
            len(rows) == 1
            and rows[0]["name"] == "Beans"
            and rows[0]["state"] == "available"
        )
        saved = b.cookies
    with TestClient(
        factory(personal_state=PersonalState(store)),
        base_url="https://reader.example",
        cookies=saved,
    ) as b:
        assert b.get("/reader/personal").json()["bookmarks"][0]["name"] == "Beans"
        csrf = b.get("/reader/session").json()["csrf"]
        change = {
            "csrf": csrf,
            "action": "rename",
            "operation_id": "b" * 32,
            "bookmark_id": "a" * 32,
            "name": "Dinner",
        }
        assert (
            b.post("/reader/personal", json=change, headers=headers).status_code == 200
        )
        assert b.get("/reader/personal").json()["bookmarks"][0]["name"] == "Dinner"
        change.update(action="remove", operation_id="c" * 32)
        change.pop("name")
        assert (
            b.post("/reader/personal", json=change, headers=headers).json()["status"]
            == "removed"
        )
        assert b.get("/reader/personal").json()["bookmarks"] == []


def test_resume_priority_retirement_and_latest_accepted_write(
    reader_env, published, tmp_path
):
    import shutil

    from test_reader_updates import update

    from cookbook.reader_personal import PersonalState

    factory, _, _ = reader_env
    source = fixture_source(published)
    old = published[0].publication_id
    at = destination(old, source, section_id="section-0")
    book = destination(old, source)
    headers = {"Origin": "https://reader.example"}
    sink = PersonalState(LocalStore(tmp_path / "personal"))
    with (
        TestClient(
            factory(personal_state=sink), base_url="https://reader.example"
        ) as a,
        TestClient(
            factory(personal_state=sink), base_url="https://reader.example"
        ) as b,
    ):
        login(a)
        login(b)

        def send(client, action, op, **values):
            return client.post(
                "/reader/personal",
                json=dict(
                    csrf=client.get("/reader/session").json()["csrf"],
                    action=action,
                    operation_id=op * 32,
                    **values,
                ),
                headers=headers,
            )

        first = send(a, "resume", "a", at=at)
        assert first.status_code == 200
        assert send(b, "save", "b", at=at, name="Retained").status_code == 200
        assert "Resume this edition" in b.get("/reader/book", params={"at": book}).text
        explicit = b.get("/reader/read", params={"at": book})
        assert (
            explicit.status_code == 200 and "Resume this edition" not in explicit.text
        )
        # Passive session/update checks must not mutate remembered state.
        revision = b.get("/reader/personal").json()["revision"]
        b.get("/reader/updates", params={"at": at})
        b.get("/reader/session")
        assert b.get("/reader/personal").json()["revision"] == revision
        current = update(published, tmp_path, text="New beans")
        current_at = destination(current, source, section_id="section-0")
        second = send(b, "resume", "c", at=current_at)
        assert second.json()["revision"] > first.json()["revision"]
        # A retry of an old accepted operation never rolls back later navigation.
        assert send(a, "resume", "a", at=at).json() == first.json()
        shutil.rmtree(published[3].root / "versions" / old)
        rows = a.get("/reader/personal").json()
        assert rows["bookmarks"][0]["state"] == "available"
        assert (
            current
            in __import__("base64")
            .urlsafe_b64decode(rows["resume"][0]["at"] + "===")
            .decode()
        )
        update(
            published,
            tmp_path / "changed",
            locator='{"kind":"epub","document":"elsewhere","anchor":"different"}',
        )
        rows = b.get("/reader/personal").json()
        assert (
            rows["bookmarks"][0]["state"] == rows["resume"][0]["state"] == "unavailable"
        )
        assert rows["bookmarks"][0]["name"] == "Retained"


def test_personal_storage_configuration_is_separate_and_complete(monkeypatch, tmp_path):
    import pytest

    from cookbook.personal_config import personal_from_environment

    make = lambda endpoint, bucket, *args: LocalStore(tmp_path / bucket)
    for name in list(__import__("os").environ):
        if name.startswith("PERSONAL_"):
            monkeypatch.delenv(name)
    assert personal_from_environment(make) is None
    monkeypatch.setenv("PERSONAL_S3_BUCKET", "personal")
    with pytest.raises(ValueError, match="incomplete"):
        personal_from_environment(make)
    monkeypatch.setenv("PERSONAL_AWS_ACCESS_KEY_ID", "personal-key")
    monkeypatch.setenv("PERSONAL_AWS_SECRET_ACCESS_KEY", "private")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://storage.example")
    assert personal_from_environment(make) is not None
    for prefix in ("", "READER_", "REPORTS_", "OWNER_REPORTS_"):
        monkeypatch.setenv(prefix + "S3_BUCKET", "personal")
        with pytest.raises(ValueError, match="separate"):
            personal_from_environment(make)
        monkeypatch.setenv(prefix + "S3_BUCKET", "other")
        key = prefix + "AWS_ACCESS_KEY_ID" if prefix else "AWS_ACCESS_KEY_ID"
        monkeypatch.setenv(key, "personal-key")
        with pytest.raises(ValueError, match="separate"):
            personal_from_environment(make)
        monkeypatch.setenv(key, "other-key")


def test_personal_security_ambiguity_and_no_false_ack(
    reader_env, published, tmp_path, monkeypatch
):
    from cookbook.reader_personal import PersonalState

    factory, _, clock = reader_env
    store = LocalStore(tmp_path / "personal")
    at = destination(
        published[0].publication_id, fixture_source(published), section_id="section-0"
    )
    with TestClient(
        factory(personal_state=PersonalState(store)), base_url="https://reader.example"
    ) as a:
        assert a.get("/reader/personal").status_code == 401
        login(a)
        payload = {
            "csrf": a.get("/reader/session").json()["csrf"],
            "action": "save",
            "operation_id": "d" * 32,
            "at": at,
            "name": "  Dinner\u202e\n party  ",
        }
        headers = {"Origin": "https://reader.example"}
        assert a.post("/reader/personal", json=payload).status_code == 403
        assert (
            a.post(
                "/reader/personal", json={**payload, "csrf": "wrong"}, headers=headers
            ).status_code
            == 403
        )
        assert (
            a.post(
                "/reader/personal",
                json={**payload, "text": "book text"},
                headers=headers,
            ).status_code
            == 400
        )
        put = store.put_bytes

        def lost(key, data, expected=None):
            put(key, data, expected)
            raise TimeoutError("private backend detail")

        monkeypatch.setattr(store, "put_bytes", lost)
        ambiguous = a.post("/reader/personal", json=payload, headers=headers)
        assert (
            ambiguous.status_code == 503
            and ambiguous.json()["error"] == "persistence_unconfirmed"
        )
        assert "private backend" not in ambiguous.text
        retry = a.post("/reader/personal", json=payload, headers=headers)
        assert retry.status_code == 200
        rows = a.get("/reader/personal")
        assert rows.json()["bookmarks"][0]["name"] == "Dinner party"
        assert "no-store" in rows.headers["cache-control"]
        assert a.get("/reader/personal?name=private").status_code == 400
        clock[0] += 31 * 86400
        assert (
            a.post("/reader/personal", json=payload, headers=headers).status_code == 401
        )


def test_concurrent_metadata_writes_wait_for_durability(
    reader_env, published, tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from cookbook.reader_personal import PersonalState

    factory, _, _ = reader_env
    store = LocalStore(tmp_path / "personal")
    at = destination(
        published[0].publication_id, fixture_source(published), section_id="section-0"
    )
    entered, release = threading.Event(), threading.Event()
    put = store.put_bytes

    def delayed(key, data, expected=None):
        if json_load(data)["revision"] == 1 and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return put(key, data, expected)

    monkeypatch.setattr(store, "put_bytes", delayed)
    with (
        TestClient(
            factory(personal_state=PersonalState(store)),
            base_url="https://reader.example",
        ) as a,
        TestClient(
            factory(personal_state=PersonalState(store)),
            base_url="https://reader.example",
        ) as b,
    ):
        login(a)
        login(b)
        headers = {"Origin": "https://reader.example"}

        def save(client, op):
            return client.post(
                "/reader/personal",
                json={
                    "csrf": client.get("/reader/session").json()["csrf"],
                    "action": "save",
                    "operation_id": op * 32,
                    "at": at,
                    "name": op,
                },
                headers=headers,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(save, a, "a")
            try:
                assert entered.wait(3) and not first.done()
                second = pool.submit(save, b, "b").result(timeout=4)
                assert second.status_code == 200
            finally:
                release.set()
            assert (
                first.result(timeout=4).json()["revision"] > second.json()["revision"]
            )
        assert len(b.get("/reader/personal").json()["bookmarks"]) == 2


def json_load(data):
    import json

    return json.loads(data)


def test_native_saved_occurrences_never_guess_changed_snapshot(
    reader_env, published, tmp_path
):
    from test_reader_updates import native_publication

    from cookbook.reader_personal import PersonalState

    factory, _, _ = reader_env
    old, source = native_publication(published, tmp_path / "native-old")
    with TestClient(
        factory(personal_state=PersonalState(LocalStore(tmp_path / "personal"))),
        base_url="https://reader.example",
    ) as a:
        login(a)
        csrf = a.get("/reader/session").json()["csrf"]
        for op, occurrence in [("a", "occ-0"), ("b", "occ-1")]:
            at = destination(
                old, source, target_id=occurrence, model_snapshot_id="stable"
            )
            result = a.post(
                "/reader/personal",
                json={
                    "csrf": csrf,
                    "action": "save",
                    "operation_id": op * 32,
                    "at": at,
                    "name": occurrence,
                },
                headers={"Origin": "https://reader.example"},
            )
            assert result.status_code == 200
        native_publication(published, tmp_path / "native-current")
        rows = a.get("/reader/personal").json()["bookmarks"]
        for row in rows:
            content = a.get("/reader/content", params={"at": row["at"]}).json()
            assert content["citations"][0]["reading_occurrence_id"] == row["name"]
        native_publication(published, tmp_path / "native-changed", snapshot="changed")
        rows = a.get("/reader/personal").json()["bookmarks"]
        assert len(rows) == 2 and all(row["state"] == "unavailable" for row in rows)


@pytest.mark.parametrize(
    "prefix,function",
    [
        ("PERSONAL", "cookbook.personal_config.personal_from_environment"),
        (
            "OWNER_REPORTS",
            "cookbook.owner_report_config.owner_reports_from_environment",
        ),
    ],
)
def test_metadata_store_endpoint_validation_and_fallback(monkeypatch, prefix, function):
    from importlib import import_module

    module, name = function.rsplit(".", 1)
    configure = getattr(import_module(module), name)
    for key in list(__import__("os").environ):
        if key.startswith(
            ("PERSONAL_", "OWNER_REPORTS_", "READER_", "REPORTS_")
        ) or key in ("S3_BUCKET", "AWS_ACCESS_KEY_ID"):
            monkeypatch.delenv(key)
    monkeypatch.setenv(prefix + "_S3_BUCKET", "isolated")
    monkeypatch.setenv(prefix + "_AWS_ACCESS_KEY_ID", "isolated-key")
    monkeypatch.setenv(prefix + "_AWS_SECRET_ACCESS_KEY", "synthetic")
    observed = []

    def make(*args):
        observed.append(args)
        return object()

    monkeypatch.setenv("S3_ENDPOINT_URL", "http://unsafe.example")
    with pytest.raises(ValueError, match="HTTPS"):
        configure(make)
    assert observed == []
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://fallback.example")
    assert configure(make) is not None
    assert observed[-1] == (
        "https://fallback.example",
        "isolated",
        "isolated-key",
        "synthetic",
    )
    monkeypatch.setenv(prefix + "_S3_ENDPOINT_URL", "https://dedicated.example")
    assert configure(make) is not None
    assert observed[-1][0] == "https://dedicated.example"
