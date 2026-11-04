"""Search through authenticated HTTP using synthetic publications, never OCR."""

import pytest
from starlette.testclient import TestClient
from test_reader_http import login

pytest_plugins = ["test_reader_http"]


def search(client, **changes):
    csrf = client.get("/reader/session").json()["csrf"]
    return client.post(
        "/reader/search/results",
        json={"csrf": csrf, "query": "salt", **changes},
        headers={"Origin": "https://reader.example"},
    )


def test_search_groups_source_links_and_private_post(reader_env, published):
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        assert client.get("/reader/search").status_code == 401
        login(client)
        page = client.get("/reader/search")
        assert (
            page.status_code == 200
            and "Content matches" in page.text
            and "Section matches" in page.text
        )
        response = search(client)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        data = response.json()
        assert data["publication_id"] == published[0].publication_id
        assert data["groups"]["content"]["state"] == "unavailable"
        section = data["groups"]["section"]
        assert section["state"] == "ok" and len(section["results"]) == 1
        hit = section["results"][0]
        assert "salt" in hit["excerpt"] and "Test Author" in hit["authors"]
        assert "salt" not in hit["href"] and "/reader/read?at=" in hit["href"]
        assert client.get(hit["href"]).status_code == 200
        assert search(client, author="ignored").status_code == 400
        assert (
            client.get("/reader/search", params={"query": "private"}).status_code == 400
        )


def test_scope_paging_failures_and_retired_publication(
    reader_env, published, tmp_path, monkeypatch
):
    from conftest import fixture_build

    from cookbook.publication import publish

    manifest, inputs = fixture_build(
        tmp_path / "many", count=2, section_count=25, repeats=1
    )
    publish(
        published[2],
        manifest,
        inputs,
        expected_version=published[2].read_version("control/active.json")[1],
        activate=published[3].activate,
    )
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        first = search(client, book_id="book-0").json()
        group = first["groups"]["section"]
        assert len(group["results"]) == 20 and group["next"] == 20
        assert all(
            row["source_id"] == group["results"][0]["source_id"]
            for row in group["results"]
        )
        # The alias does not create duplicate source hits; rank/order/continuation belong to Library.
        second = search(
            client,
            book_id="book-0",
            publication_id=first["publication_id"],
            group="section",
            section_offset=20,
        ).json()
        assert set(second["groups"]) == {"section"}
        assert len(second["groups"]["section"]["results"]) == 5
        assert second["groups"]["section"]["next"] is None
        assert not {r["href"] for r in group["results"]} & {
            r["href"] for r in second["groups"]["section"]["results"]
        }
        assert (
            search(client, query="unfindable").json()["groups"]["section"]["results"]
            == []
        )
        assert (
            search(client, query="salt unfindable").json()["groups"]["section"][
                "results"
            ]
            == []
        )
        assert (
            search(client, kind="recipe").json()["groups"]["section"]["state"]
            == "excluded"
        )
        assert search(client, publication_id="f" * 32).status_code == 410
        assert search(client, section_offset=20).status_code == 400
        assert search(client, tag="cooking").status_code == 400
        csrf = client.get("/reader/session").json()["csrf"]
        assert (
            client.post(
                "/reader/search/results",
                json={"query": "salt", "csrf": csrf},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert search(client, csrf="wrong").status_code == 403

        def broken(*args):
            raise OSError("private provider failure")

        monkeypatch.setattr(published[2], "read_version", broken)
        failed = search(client, publication_id=first["publication_id"])
        assert failed.json()["groups"]["section"]["state"] == "failed"
        assert failed.status_code == 200 and "private provider" not in failed.text


def test_withheld_page_can_continue_without_claiming_absence(
    reader_env, published, tmp_path
):
    import hashlib
    import json
    import sqlite3

    from conftest import fixture_build

    from cookbook.publication import Entry, publish
    from cookbook.storage import canonical, digest_file
    from cookbook.withdrawal import record_withdrawal

    manifest, inputs = fixture_build(
        tmp_path / "withdrawn", section_count=25, repeats=1
    )
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        source = db.execute("select id from sources").fetchone()[0]
        db.execute(
            "update sections set locator=?",
            (json.dumps({"kind": "scanned-section", "physical_pages": [1]}),),
        )
    manifest.files = [
        Entry(
            path=e.path,
            sha256=digest_file(inputs[e.path])[0],
            size=inputs[e.path].stat().st_size,
            role=e.role,
        )
        for e in manifest.files
    ]
    publish(
        published[2],
        manifest,
        inputs,
        expected_version=published[2].read_version("control/active.json")[1],
        activate=published[3].activate,
    )
    event = {
        "action": "revoke",
        "actor": {"kind": "human"},
        "affected_decisions": [],
        "affected_pages": [{"source_sha256": source.split(":")[1], "physical_page": 1}],
    }
    event["id"] = hashlib.sha256(canonical(event)).hexdigest()
    record_withdrawal(published[2], event)
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        group = search(client).json()["groups"]["section"]
        assert group["results"] == [] and group["next"] == 20
        assert (
            "withheld" in group["coverage"]
            and "not established absent" in group["coverage"]
        )


def test_search_reads_current_withdrawals_once_per_page(
    published, tmp_path, monkeypatch
):
    from conftest import fixture_build

    from cookbook.publication import publish
    from cookbook.withdrawal import KEY

    manifest, inputs = fixture_build(
        tmp_path / "many-control-checks", section_count=25, repeats=1
    )
    _, _, store, runtime, library, _ = published
    publish(
        store,
        manifest,
        inputs,
        expected_version=store.read_version("control/active.json")[1],
        activate=runtime.activate,
    )
    original = store.read_version
    reads = []

    def read(key):
        if key == KEY:
            reads.append(key)
        return original(key)

    monkeypatch.setattr(store, "read_version", read)
    assert len(library.search("salt", limit=20)["results"]) == 20
    assert len(reads) == 1
    # A subsequent request must not reuse an earlier control snapshot.
    store.put_bytes(KEY, b"invalid")
    import pytest

    with pytest.raises(ValueError):
        library.search("salt", limit=20)
    assert len(reads) == 2


def test_native_results_scope_independent_pages_and_partial_failure(
    reader_env, published, tmp_path
):
    """A synthetic external keyword-engine response; real Library resolves every hit."""
    import json
    import sqlite3

    from conftest import fixture_build

    from cookbook.book_capture import SCHEMA
    from cookbook.book_model import MODEL_PATH
    from cookbook.publication import Entry, publish
    from cookbook.storage import digest_file

    book_id = "a" * 32
    manifest, inputs = fixture_build(
        tmp_path / "native-search", section_count=25, repeats=1
    )
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        source = db.execute("select id from sources").fetchone()[0]
        db.execute("update books set id=? where id='book-0'", (book_id,))
    # Re-sign the synthetic index after editing identifiers.
    manifest.files = [
        Entry(
            path=e.path,
            sha256=digest_file(inputs[e.path])[0],
            size=inputs[e.path].stat().st_size,
            role=e.role,
        )
        for e in manifest.files
    ]
    path = tmp_path / "native-search" / MODEL_PATH
    path.parent.mkdir(exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            SCHEMA
            + "CREATE TABLE model_info(payload TEXT); CREATE TABLE coverage(edition_id TEXT,payload TEXT); CREATE TABLE search_units(id TEXT,edition_id TEXT,target_id TEXT,kind TEXT,state TEXT,title TEXT);"
        )
        db.execute(
            "insert into model_info values(?)",
            (
                json.dumps(
                    {
                        "publication_id": manifest.publication_id,
                        "model_snapshot": {"id": "snapshot-1"},
                    }
                ),
            ),
        )
        edition = {
            "id": book_id,
            "source_id": source,
            "source_sha256": source.split(":")[1],
            "title": "Native synthetic",
            "authors": ["Fixture"],
            "format": "EPUB",
        }
        db.execute(
            "insert into editions values(?,?,?,?)",
            (book_id, 0, "Native synthetic", json.dumps(edition)),
        )
        db.execute(
            "insert into coverage values(?,?)",
            (book_id, json.dumps({"semantic_state": "partial"})),
        )
        db.execute(
            "insert into documents values(?,?,?,?,?)",
            (
                "doc",
                book_id,
                "chapter.xhtml",
                "body",
                json.dumps({"parser_diagnostics": []}),
            ),
        )
        db.execute(
            "insert into occurrences values(?,?,?,?,?)",
            ("occ", book_id, "doc", 0, json.dumps({"id": "occ", "ordinal": 0})),
        )
        db.execute(
            "insert into nodes values(?,?,?,?,?,?,?,?,?,?)",
            (
                "body",
                "doc",
                None,
                0,
                0,
                "text",
                "text",
                "/",
                "Synthetic salt essay",
                json.dumps(
                    {"id": "body", "kind": "text", "text": "Synthetic salt essay"}
                ),
            ),
        )
        part = {
            "document_id": "doc",
            "reading_occurrence_id": "occ",
            "start": {"node_id": "body", "side": "before", "offset": None},
            "end": {"node_id": "body", "side": "after", "offset": None},
        }
        db.execute(
            "insert into spans values(?,?,?)",
            ("span", book_id, json.dumps({"parts": [part]})),
        )
        for n in range(21):
            db.execute(
                "insert into entities values(?,?,?,?,?)",
                (
                    f"target-{n}",
                    book_id,
                    "passage",
                    "Essay",
                    json.dumps(
                        {
                            "id": f"target-{n}",
                            "state": "candidate",
                            "evidence_span_ids": ["span"],
                        }
                    ),
                ),
            )
            db.execute(
                "insert into search_units values(?,?,?,?,?,?)",
                (f"unit-{n}", book_id, f"target-{n}", "passage", "candidate", "Essay"),
            )
    sha, size = digest_file(path)
    manifest.files.append(Entry(path=MODEL_PATH, sha256=sha, size=size, role="runtime"))
    inputs[MODEL_PATH] = path
    publish(
        published[2],
        manifest,
        inputs,
        expected_version=published[2].read_version("control/active.json")[1],
        activate=published[3].activate,
    )

    class KeywordService:
        failed = False

        def start(self):
            pass

        def close(self):
            pass

        def prepare(self, manifest, directory):
            pass

        def search(
            self,
            publication_id,
            query,
            book_ids,
            kinds,
            include_candidates,
            limit,
            page,
        ):
            if self.failed:
                raise OSError("private keyword engine failure")
            # Simulates the external engine's ranked hits, including typo tolerance.
            ids = range(20) if page == 1 else [20]
            return {
                "search_cutoff": True,
                "grouped_hits": [
                    {
                        "hits": [
                            {
                                "document": {"id": f"unit-{n}"},
                                "highlights": [
                                    {"field": "text", "snippet": "Synthetic salt essay"}
                                ],
                            }
                        ]
                    }
                    for n in ids
                ],
            }

    engine = KeywordService()
    app, _, _ = reader_env
    with TestClient(
        app(search_engine=engine), base_url="https://reader.example"
    ) as client:
        login(client)
        first = search(
            client,
            book_id=book_id,
            query="saltt",
            publication_id=manifest.publication_id,
        ).json()
        content = first["groups"]["content"]
        assert (
            content["state"] == "ok"
            and len(content["results"]) == 20
            and content["next"] == 2
        )
        assert content["cutoff"] and "Partial" in content["details"]["interpretation"]
        assert first["groups"]["section"]["results"] == []
        assert (
            len({r["href"] for r in content["results"]}) == 20
        )  # same wording, distinct targets
        second = search(
            client,
            book_id=book_id,
            publication_id=first["publication_id"],
            group="content",
            content_page=2,
        ).json()
        assert (
            set(second["groups"]) == {"content"}
            and len(second["groups"]["content"]["results"]) == 1
        )
        assert second["groups"]["content"]["next"] is None
        assert (
            "snapshot-1" not in content["results"][0]["href"]
        )  # identifiers encoded by shared reading_link
        opened = client.get(content["results"][0]["href"])
        assert opened.status_code == 200 and "Synthetic salt essay" in opened.text
        engine.failed = True
        failed = search(
            client, query="salt", publication_id=manifest.publication_id
        ).json()
        assert failed["groups"]["content"]["state"] == "failed"
        assert len(failed["groups"]["section"]["results"]) == 20
        assert "private keyword" not in json.dumps(failed)


def page_csrf(client):
    from lxml import html

    response = client.get("/reader/search")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    token = (
        html.fromstring(response.text).get_element_by_id("search-form").get("data-csrf")
    )
    assert token and response.text.count(token) == 1
    assert "synthetic-refresh" not in response.text
    return token


def direct_search(client, token, **fields):
    return client.post(
        "/reader/search/results",
        json={"query": "salt", "csrf": token, **fields},
        headers={"Origin": "https://reader.example"},
    )


def test_html_bootstrap_supports_repeated_search_without_session_get(reader_env):
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        token = page_csrf(client)
        first = direct_search(client, token)
        assert first.status_code == 200
        pin = first.json()["publication_id"]
        for group, cursor in [
            ("content", {"content_page": 2}),
            ("section", {"section_offset": 20}),
        ]:
            more = direct_search(
                client, token, publication_id=pin, group=group, **cursor
            )
            assert more.status_code == 200
            assert more.json()["publication_id"] == pin
            assert set(more.json()["groups"]) == {group}
        assert direct_search(client, token).json() == first.json()
        assert direct_search(client, "wrong").status_code == 403
        denied = client.post(
            "/reader/search/results",
            json={"query": "salt", "csrf": token},
            headers={"Origin": "https://foreign.example"},
        )
        assert denied.status_code == 403 and denied.json()["error"] == "origin_denied"


def test_cookie_replacement_recovers_same_read_and_pin(reader_env):
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        old = page_csrf(client)
        pin = direct_search(client, old).json()["publication_id"]
        login(client)
        denied = direct_search(
            client, old, publication_id=pin, group="section", section_offset=20
        )
        assert denied.status_code == 403 and denied.json()["error"] == "csrf_denied"
        new = client.get("/reader/session").json()["csrf"]
        assert new != old
        again = direct_search(
            client, new, publication_id=pin, group="section", section_offset=20
        )
        assert again.status_code == 200 and again.json()["publication_id"] == pin


def test_bootstrap_cannot_revive_an_expired_session(reader_env):
    app, _, clock = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        token = page_csrf(client)
        clock[0] += 7 * 86400 + 1
        assert direct_search(client, token).status_code == 401
        assert client.get("/reader/session").status_code == 401
        page = client.get("/reader/search")
        assert page.status_code == 401 and "data-csrf" not in page.text


@pytest.mark.parametrize("refused", [False, True])
def test_results_post_performs_renewal_without_session_preflight(
    reader_env, monkeypatch, mint, refused
):
    from datetime import UTC, datetime

    app, identity, clock = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        token = page_csrf(client)
        clock[0] += 601

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(clock[0], UTC)

        monkeypatch.setattr("jwt.api_jwt.datetime", Later)
        identity.renewed_tokens = {
            "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
            "refresh_token": "rotated-refresh",
        }
        identity.refused = refused
        response = direct_search(client, token)
        assert response.status_code == (401 if refused else 200)
        if not refused:
            assert page_csrf(client) == token
            assert direct_search(client, token).status_code == 200
