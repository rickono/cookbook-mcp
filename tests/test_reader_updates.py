"""Publication recovery through authorized HTTP; synthetic indexes only."""

import sqlite3

from conftest import fixture_build
from starlette.testclient import TestClient
from test_reader_content import destination
from test_reader_http import login

from cookbook.publication import Entry, publish
from cookbook.storage import digest_file

pytest_plugins = ["test_reader_http"]


def fixture_source(published):
    with sqlite3.connect(published[1]["runtime/index.sqlite"]) as db:
        return db.execute("select id from sources").fetchone()[0]


def update(published, tmp_path, *, duplicate=False, **changes):
    m, inputs = fixture_build(tmp_path / mangle(changes), repeats=1000)
    db = sqlite3.connect(inputs["runtime/index.sqlite"])
    for column, value in changes.items():
        db.execute(f"update sections set {column}=?", (value,))
    if duplicate:
        db.execute(
            "insert into sections select 'duplicate',source_id,ordinal,title,text,?,provenance,kind,images from sections limit 1",
            (
                '{"anchor":"beans","kind":"epub","text_offset":0,"document":"chapter-0.xhtml"}',
            ),
        )
    db.commit()
    db.close()
    m.files = [
        Entry(
            path=e.path,
            sha256=digest_file(inputs[e.path])[0],
            size=inputs[e.path].stat().st_size,
            role=e.role,
        )
        for e in m.files
    ]
    publish(
        published[2],
        m,
        inputs,
        expected_version=published[2].read_version("control/active.json")[1],
        activate=published[3].activate,
    )
    return m.publication_id


def mangle(changes):
    return "updated-" + str(len(changes))


def test_pinned_notice_explicit_update_and_continuation(
    reader_env, published, tmp_path
):
    app, _, _ = reader_env
    source = fixture_source(published)
    at = destination(published[0].publication_id, source, section_id="section-0")
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        first = client.get("/reader/content", params={"at": at}).json()
        current = update(published, tmp_path, text="Updated synthetic beans")
        notice = client.get("/reader/updates", params={"at": at}).json()
        assert notice["state"] == "available"
        assert notice["current_publication_id"] == current
        pinned = client.get("/reader/content", params={"at": first["next_text"]}).json()
        assert pinned["citation"]["publication_id"] == published[0].publication_id
        assert "Updated synthetic beans" not in pinned["text"]
        adopted = client.get("/reader/content", params={"at": notice["at"]}).json()
        assert adopted["text"] == "Updated synthetic beans"
        assert adopted["citation"]["publication_id"] == current
        assert "Open current text" in client.get("/reader/read", params={"at": at}).text


def test_retired_link_recovers_only_with_source_evidence(
    reader_env, published, tmp_path
):
    import shutil

    app, _, _ = reader_env
    source = fixture_source(published)
    old = published[0].publication_id
    at = destination(old, source, section_id="section-0")
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        first = client.get("/reader/content", params={"at": at}).json()
        from cookbook.reader_content import encode_location

        durable = encode_location(first["source_location"])
        current = update(published, tmp_path, text="Current beans")
        shutil.rmtree(published[3].root / "versions" / old)
        stale = client.get("/reader/read", params={"at": durable})
        assert stale.status_code == 410
        assert "Open current text" in stale.text
        assert "Current beans" not in stale.text
        recovery = client.get("/reader/updates", params={"at": durable}).json()
        assert (
            recovery["state"] == "available"
            and recovery["current_publication_id"] == current
        )
        assert (
            client.get("/reader/updates", params={"at": at}).json()["state"]
            == "unavailable"
        )
        assert (
            client.get(
                "/reader/updates",
                params={
                    "at": destination(old, "epub:" + "a" * 64, section_id="section-0")
                },
            ).json()["state"]
            == "unavailable"
        )


def test_changed_locator_refuses_section_id_match(reader_env, published, tmp_path):
    app, _, _ = reader_env
    source = fixture_source(published)
    at = destination(published[0].publication_id, source, section_id="section-0")
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        update(
            published,
            tmp_path,
            locator='{"kind":"epub","document":"other.xhtml","anchor":"beans"}',
        )
        notice = client.get("/reader/updates", params={"at": at}).json()
        assert notice["state"] == "unavailable" and notice["at"] is None
        assert (
            "Open current text"
            not in client.get("/reader/read", params={"at": at}).text
        )


def test_notice_requires_auth_and_valid_destination(reader_env):
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        assert (
            client.get(
                "/reader/updates", params={"at": "https://evil.example"}
            ).status_code
            == 401
        )
        login(client)
        assert (
            client.get(
                "/reader/updates", params={"at": "https://evil.example"}
            ).status_code
            == 400
        )


def test_passive_notice_enforces_current_withdrawal(reader_env, published, tmp_path):
    import hashlib

    from test_reader_content import publish_scanned

    from cookbook.storage import canonical
    from cookbook.withdrawal import record_withdrawal

    app, _, _ = reader_env
    pub, source = publish_scanned(published, tmp_path)
    at = destination(pub, source, section_id="section-0")
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        assert "Synthetic soup" in client.get("/reader/read", params={"at": at}).text
        event = {
            "action": "revoke",
            "actor": {"kind": "human"},
            "affected_decisions": [],
            "affected_pages": [
                {"source_sha256": source.split(":")[1], "physical_page": 1}
            ],
        }
        event["id"] = hashlib.sha256(canonical(event)).hexdigest()
        record_withdrawal(published[2], event)
        notice = client.get("/reader/updates", params={"at": at}).json()
        assert notice["pinned_state"] == "withheld"
        assert notice["at"] is None
        assert client.get("/reader/content", params={"at": at}).json()["text"] == ""


def native_publication(published, root, snapshot="stable"):
    import json

    from cookbook.book_build import validate_model
    from cookbook.book_capture import SCHEMA
    from cookbook.book_model import MODEL_PATH, REPORT_PATH

    m, inputs = fixture_build(root)
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as index:
        source = index.execute("select id from sources").fetchone()[0]
        index.execute("delete from books where id='alias'")
    path = root / "model.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            SCHEMA
            + "CREATE TABLE model_info(payload TEXT); CREATE TABLE coverage(edition_id TEXT,payload TEXT); CREATE TABLE search_units(target_id TEXT,edition_id TEXT,kind TEXT,state TEXT);"
        )
        db.execute(
            "insert into model_info values(?)",
            (
                json.dumps(
                    {
                        "publication_id": m.publication_id,
                        "model_snapshot": {"id": snapshot},
                    }
                ),
            ),
        )
        edition = {
            "id": "book-0",
            "source_id": source,
            "source_sha256": source.split(":")[1],
            "title": "Native fixture",
            "authors": [],
            "format": "EPUB",
        }
        db.execute(
            "insert into editions values(?,?,?,?)",
            ("book-0", 0, "Native fixture", json.dumps(edition)),
        )
        db.execute("insert into coverage values(?,?)", ("book-0", "{}"))
        db.execute(
            "insert into documents values(?,?,?,?,?)",
            (
                "b" * 32,
                "book-0",
                "chapter.xhtml",
                "a" * 32,
                json.dumps(
                    {
                        "parser_diagnostics": [],
                        "body_text_sha256": __import__("hashlib")
                        .sha256(b"")
                        .hexdigest(),
                    }
                ),
            ),
        )
        for n in range(2):
            db.execute(
                "insert into occurrences values(?,?,?,?,?)",
                (
                    f"occ-{n}",
                    "book-0",
                    "b" * 32,
                    n,
                    json.dumps({"id": f"occ-{n}", "ordinal": n}),
                ),
            )
        db.execute(
            "insert into nodes values(?,?,?,?,?,?,?,?,?,?)",
            (
                "a" * 32,
                "b" * 32,
                None,
                0,
                0,
                "element",
                "document",
                "/",
                "",
                json.dumps(
                    {
                        "id": "a" * 32,
                        "kind": "element",
                        "document_id": "b" * 32,
                        "parent_id": None,
                        "child_ordinal": 0,
                        "preorder": 0,
                        "subtree_end": 0,
                        "source_xpath": "/",
                        "source_tag": "body",
                        "content_kind": "document",
                        "source_attributes": {},
                        "child_ids": [],
                    }
                ),
            ),
        )
    db.close()
    report = root / "report.json"
    report.write_text(
        json.dumps(
            {
                "publication_id": m.publication_id,
                "validation": validate_model(
                    path, m.publication_id, inputs["runtime/index.sqlite"]
                ),
            }
        )
    )
    inputs[MODEL_PATH] = path
    inputs[REPORT_PATH] = report
    m.files = [
        Entry(
            path=k,
            sha256=digest_file(v)[0],
            size=v.stat().st_size,
            role="runtime" if k.startswith("runtime/") else "backup",
        )
        for k, v in inputs.items()
    ]
    result = publish(
        published[2],
        m,
        inputs,
        expected_version=published[2].read_version("control/active.json")[1],
        activate=published[3].activate,
    )
    assert result["status"] == "active", result
    return m.publication_id, source


def test_native_updates_preserve_occurrence_and_refuse_changed_snapshot(
    reader_env, published, tmp_path
):
    app, _, _ = reader_env
    old, source = native_publication(published, tmp_path / "native-old")
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        current, _ = native_publication(published, tmp_path / "native-current")
        for occurrence in ("occ-0", "occ-1"):
            at = destination(
                old, source, target_id=occurrence, model_snapshot_id="stable"
            )
            notice = client.get("/reader/updates", params={"at": at}).json()
            assert notice["state"] == "available"
            opened = client.get("/reader/content", params={"at": notice["at"]}).json()
            assert opened["citation"]["publication_id"] == current
            assert opened["citations"][0]["reading_occurrence_id"] == occurrence
        native_publication(published, tmp_path / "native-changed", snapshot="changed")
        assert (
            client.get("/reader/updates", params={"at": at}).json()["state"]
            == "unavailable"
        )


def test_ambiguous_source_locator_never_offers_current_text(
    reader_env, published, tmp_path
):
    app, _, _ = reader_env
    at = destination(
        published[0].publication_id, fixture_source(published), section_id="section-0"
    )
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        update(published, tmp_path, duplicate=True)
        assert (
            client.get("/reader/updates", params={"at": at}).json()["state"]
            == "unavailable"
        )


def test_passive_update_checks_do_not_extend_session_inactivity(reader_env, published):
    app, _, clock = reader_env
    at = destination(
        published[0].publication_id, fixture_source(published), section_id="section-0"
    )
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        for day in range(8):
            clock[0] += 86400
            response = client.get("/reader/updates", params={"at": at})
        assert response.status_code == 401


def test_same_publication_resolution_reads_once_and_rechecks_next_request(
    published, monkeypatch
):
    from cookbook import reader_content
    from cookbook.reader_updates import resolve_current, source_location
    from cookbook.storage import IntegrityError

    loc = source_location(
        published[4],
        {
            "publication_id": published[0].publication_id,
            "book_id": "book-0",
            "source_id": fixture_source(published),
            "section_id": "section-0",
        },
    )
    original = reader_content.read
    calls = []

    def read(library, location):
        calls.append(location)
        return original(library, location)

    monkeypatch.setattr(reader_content, "read", read)
    assert resolve_current(published[4], loc)["state"] == "available"
    assert len(calls) == 1

    def unavailable(library, location):
        raise IntegrityError("withdrawn or unavailable")

    monkeypatch.setattr(reader_content, "read", unavailable)
    assert resolve_current(published[4], loc)["state"] == "unavailable"
