"""Reading validation through synthetic authenticated HTTP; no OCR or rendering."""

import hashlib

import pytest
from starlette.testclient import TestClient
from test_reader_content import decode_at, destination, publish_scanned
from test_reader_http import login
from test_reader_updates import fixture_source, update

from cookbook.reader_personal import PersonalState
from cookbook.storage import LocalStore, canonical
from cookbook.withdrawal import KEY

pytest_plugins = ["test_reader_http"]


def revoke(source):
    event = {
        "action": "revoke",
        "actor": {"kind": "human"},
        "affected_decisions": [],
        "affected_pages": [{"source_sha256": source.split(":")[1], "physical_page": 1}],
    }
    return {**event, "id": hashlib.sha256(canonical(event)).hexdigest()}


@pytest.fixture
def policy_reads(published, monkeypatch):
    original = published[2].read_version
    calls = []

    def read(key):
        if key == KEY:
            calls.append(key)
        return original(key)

    monkeypatch.setattr(published[2], "read_version", read)
    return calls


@pytest.mark.parametrize("scanned", [False, True])
def test_each_text_response_observes_policy_once_and_next_request_rechecks(
    reader_env, published, tmp_path, policy_reads, scanned
):
    if scanned:
        pub, source = publish_scanned(published, tmp_path)
    else:
        pub, source = published[0].publication_id, fixture_source(published)
    policy_reads.clear()
    factory, _, _ = reader_env
    at = destination(pub, source, section_id="section-0")
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        for count in (1, 2):
            response = client.get("/reader/content", params={"at": at})
            assert response.status_code == 200
            data = response.json()
            assert data["text"] and data["next_text"]
            assert data["citation"]["publication_id"] == pub
            assert data["update"]["state"] == (
                "unavailable" if scanned else "available"
            )
            assert ("source_key" in data["source_location"]) is not scanned
            assert len(policy_reads) == count


def test_section_text_and_eligibility_use_one_observation_during_withdrawal(
    reader_env, published, tmp_path, monkeypatch
):
    pub, source = publish_scanned(published, tmp_path)
    store = published[2]
    original = store.read_version
    calls = []

    def read(key):
        raw, version = original(key)
        if key == KEY:
            calls.append(key)
            if len(calls) == 1:
                store.put_bytes(KEY, canonical([revoke(source)]), expected=version)
        return raw, version

    monkeypatch.setattr(store, "read_version", read)
    factory, _, _ = reader_env
    at = destination(pub, source, section_id="section-0")
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        first = client.get("/reader/content", params={"at": at}).json()
        assert first["state"] == "partial_text"
        assert "Synthetic soup" in first["text"] and first["next_text"]
        assert first["eligibility"] == first["citation"]["eligibility"]
        second = client.get("/reader/content", params={"at": first["next_text"]}).json()
        assert second["state"] == "withheld"
        assert second["text"] == "" and second["next_text"] is None
        assert second["eligibility"] == second["citation"]["eligibility"]
        assert second["eligibility"]["reasons"] == ["approval_revoked"]


@pytest.mark.parametrize(
    "offset",
    [{"offset": 2_000_000}, {"contents_offset": 200_000}, {"related_offset": 200_000}],
)
def test_failed_pinned_offsets_keep_existing_stripped_location_recovery(
    reader_env, published, tmp_path, offset
):
    factory, _, _ = reader_env
    old = published[0].publication_id
    source = fixture_source(published)
    at = destination(old, source, section_id="section-0", **offset)
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        notice = client.get("/reader/updates", params={"at": at}).json()
        assert notice["pinned_state"] == "unavailable"
        assert notice["state"] == "available"
        target = decode_at(notice["at"])
        assert target["publication_id"] == old
        assert not set(offset) & target.keys()
        current = update(published, tmp_path, text="Current synthetic beans")
        response = client.get("/reader/read", params={"at": at})
        assert response.status_code == 404
        assert "Open current text" in response.text
        notice = client.get("/reader/updates", params={"at": at}).json()
        assert notice["state"] == "available"
        assert decode_at(notice["at"])["publication_id"] == current


def test_current_publication_is_read_independently(
    reader_env, published, tmp_path, policy_reads
):
    factory, _, _ = reader_env
    old = published[0].publication_id
    source = fixture_source(published)
    current = update(published, tmp_path, text="Current synthetic beans")
    policy_reads.clear()
    at = destination(old, source, section_id="section-0")
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        response = client.get("/reader/content", params={"at": at})
        assert response.status_code == 200
        data = response.json()
        assert data["citation"]["publication_id"] == old
        assert "Current synthetic beans" not in data["text"]
        assert decode_at(data["update"]["at"])["publication_id"] == current
        assert len(policy_reads) == 2
        policy_reads.clear()
        adopted = client.get("/reader/content", params={"at": data["update"]["at"]})
        assert adopted.status_code == 200
        assert adopted.json()["text"] == "Current synthetic beans"
        assert len(policy_reads) == 1


@pytest.mark.parametrize(
    "fault,status", [("storage", 503), ("json", 503), ("event", 404)]
)
def test_policy_failure_remains_closed(
    reader_env, published, tmp_path, monkeypatch, fault, status
):
    pub, source = publish_scanned(published, tmp_path)
    original = published[2].read_version

    def read(key):
        if key != KEY:
            return original(key)
        if fault == "storage":
            raise OSError("private-policy-error")
        return (b"{" if fault == "json" else b"[{}]"), None

    monkeypatch.setattr(published[2], "read_version", read)
    factory, _, _ = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        response = client.get(
            "/reader/read",
            params={"at": destination(pub, source, section_id="section-0")},
        )
        assert response.status_code == status
        assert "Synthetic soup" not in response.text
        assert "private-policy-error" not in response.text
        if status == 503:
            assert response.headers["X-Reader-Failure"].startswith(
                "content; stage=content_deliver;"
            )


def test_identity_errors_and_contents_do_not_depend_on_policy_store(
    reader_env, published, tmp_path, monkeypatch
):
    pub, source = publish_scanned(published, tmp_path)
    original = published[2].read_version

    def read(key):
        if key == KEY:
            raise AssertionError("identity errors and contents must not fetch policy")
        return original(key)

    monkeypatch.setattr(published[2], "read_version", read)
    factory, _, _ = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        for at, status in [
            (destination(pub, source, section_id="missing"), 404),
            (destination("f" * 32, source, section_id="section-0"), 410),
            (destination(pub, source), 200),
        ]:
            assert client.get("/reader/read", params={"at": at}).status_code == status


def test_saved_scanned_entry_retains_unavailable_reference_and_explicit_destination(
    reader_env, published, tmp_path, policy_reads
):
    pub, source = publish_scanned(published, tmp_path)
    personal = PersonalState(LocalStore(tmp_path / "personal"))
    factory, _, _ = reader_env
    at = destination(pub, source, section_id="section-0")
    with TestClient(
        factory(personal_state=personal), base_url="https://reader.example"
    ) as client:
        login(client)
        result = client.post(
            "/reader/personal",
            headers={"Origin": "https://reader.example"},
            json={
                "csrf": client.get("/reader/session").json()["csrf"],
                "action": "resume",
                "operation_id": "a" * 32,
                "at": at,
            },
        )
        assert result.status_code == 200
        policy_reads.clear()
        entry = client.get("/reader/book", params={"at": destination(pub, source)})
        assert entry.status_code == 200
        assert (
            "Remembered location unavailable. Your reference is retained." in entry.text
        )
        from lxml import html

        contents = html.fromstring(entry.text).xpath(
            '//nav[@aria-label="Book contents"]/a/@href'
        )
        assert contents and all(
            href.startswith("/reader/book-view?at=") for href in contents
        )
        assert len(policy_reads) == 1
        explicit = client.get("/reader/read", params={"at": at})
        assert explicit.status_code == 200 and "Synthetic soup" in explicit.text
        assert "Remembered location unavailable" not in explicit.text
        saved = client.get("/reader/personal").json()["resume"]
        assert len(saved) == 1 and saved[0]["state"] == "unavailable"
