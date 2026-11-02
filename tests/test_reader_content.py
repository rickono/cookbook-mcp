"""Synthetic public HTTP reading journeys; no extraction, OCR or model calls."""

import base64
import json
import re
from html import unescape

from starlette.testclient import TestClient
from test_reader_http import login

pytest_plugins = ["test_reader_http"]


def destination(pub, source, **extra):
    value = {"publication_id": pub, "book_id": "book-0", "source_id": source, **extra}
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def test_catalog_book_text_continuations_and_login_return(
    reader_env, published, tmp_path
):
    app, _, _ = reader_env
    source = published[4].search("salt")["results"][0]["citation"]["source_id"]
    at = destination(published[0].publication_id, source, section_id="section-0")
    with TestClient(app(), base_url="https://reader.example") as client:
        denied = client.get("/reader/read", params={"at": at})
        assert denied.status_code == 401
        sign_in = unescape(re.search(r'href="([^"]+)">Sign in', denied.text)[1])
        oauth = client.get(sign_in, follow_redirects=False)
        from urllib.parse import parse_qs, urlsplit

        state = parse_qs(urlsplit(oauth.headers["location"]).query)["state"][0]
        callback = client.get(
            "/reader/callback",
            params={
                "state": state,
                "code": "synthetic-code",
                "iss": "https://issuer.example/",
            },
            follow_redirects=False,
        )
        assert callback.headers["location"] == "/reader/read?at=" + at
        page = client.get(callback.headers["location"])
        assert page.status_code == 200 and "Synthetic bean recipe" in page.text
        assert "Partial text" in page.text and "Unapproved" in page.text
        assert "private, no-store" == page.headers["cache-control"]
        first = client.get("/reader/content", params={"at": at}).json()
        chunks = [first["text"]]
        original_publication = first["citation"]["publication_id"]
        publish_scanned(published, tmp_path)
        while first["next_text"]:
            first = client.get(
                "/reader/content", params={"at": first["next_text"]}
            ).json()
            assert first["citation"]["publication_id"] == original_publication
            chunks.append(first["text"])
        assert "".join(chunks) == (
            "Synthetic bean recipe 0. Use 1/2 teaspoon salt and 200 grams beans. Simmer 20 minutes. "
            * 1000
        )
        assert first["state"] == "complete_text"
        catalog = client.get("/reader/catalog")
        assert "/reader/book?at=" in catalog.text


def publish_scanned(published, tmp_path):
    """Direct synthetic index rows, never a PDF parser or transcription pipeline."""
    import sqlite3

    from conftest import fixture_build

    from cookbook.publication import Entry, publish
    from cookbook.storage import digest_file

    m, inputs = fixture_build(tmp_path / "scan", section_count=2, repeats=100)
    db = sqlite3.connect(inputs["runtime/index.sqlite"])
    source = db.execute("select id from sources").fetchone()[0]
    locator = {
        "kind": "scanned-section",
        "physical_pages": [1, 2],
        "unresolved_ids": ["u1"],
        "references": [
            {"label": f"See sauce {n}", "target_section_id": "section-0-1"}
            for n in range(23)
        ],
    }
    db.execute(
        "update sections set locator=?,text=?,provenance=? where id='section-0'",
        (
            json.dumps(locator),
            "Synthetic soup\n[unresolved u1: amount]\n"
            + "Simmer. " * 1000
            + "<script>evil()</script>",
            "agent transcription, unapproved",
        ),
    )
    db.execute("update sources set format='PDF'")
    db.execute(
        "update sources set toc=?",
        (
            json.dumps(
                [
                    {"title": "Soup", "section_id": "section-0"},
                    {"title": "Sauce", "section_id": "section-0-1"},
                ]
            ),
        ),
    )
    db.execute(
        "insert into transcription_units values(?,?,?,?,?)",
        (
            "section-0",
            source,
            json.dumps("agent transcription, unapproved"),
            json.dumps(
                [
                    {
                        "physical_page": 1,
                        "box": [0.1, 0.2, 0.4, 0.5],
                        "status": "unresolved",
                    }
                ]
            ),
            json.dumps([{"id": "correction-1", "reviewer": "synthetic"}]),
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
    return m.publication_id, source


def test_scanned_independent_relationships_reference_return_and_safety(
    reader_env, published, tmp_path
):
    pub, source = publish_scanned(published, tmp_path)
    app, _, _ = reader_env
    at = destination(pub, source, section_id="section-0", offset=4000)
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        data = client.get("/reader/content", params={"at": at}).json()
        assert len(data["related"]) == 20
        assert data["citation"]["locator"]["physical_pages"] == [1, 2]
        assert data["citation"]["extraction"]["corrections"][0]["id"] == "correction-1"
        assert data["check_regions"][0]["box"] == [0.1, 0.2, 0.4, 0.5]
        more = client.get("/reader/content", params={"at": data["next_related"]}).json()
        assert len(more["related"]) == 3 and more["next_related"] is None
        assert more["text_offset"] == 4000 and more["text"] == data["text"]
        assert (
            client.get("/reader/content", params={"at": more["next_text"]}).json()[
                "text"
            ]
            == client.get("/reader/content", params={"at": data["next_text"]}).json()[
                "text"
            ]
        )
        target = client.get(
            "/reader/read", params={"at": data["related"][0]["at"], "back": at}
        )
        assert "Return to originating location" in target.text and at in target.text
        page = client.get(
            "/reader/read",
            params={
                "at": destination(pub, source, section_id="section-0", offset=8000)
            },
        )
        assert "<script>evil()" not in page.text and "&lt;script&gt;evil()" in page.text
        assert "Next section" in page.text
        assert "Printed page labels remain unverified" in page.text


def test_exact_publication_withdrawal_unavailable_and_failure(
    reader_env, published, tmp_path, monkeypatch
):
    import hashlib

    from cookbook.storage import canonical
    from cookbook.withdrawal import record_withdrawal

    pub, source = publish_scanned(published, tmp_path)
    app, _, _ = reader_env
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
        withdrawn = client.get("/reader/content", params={"at": at}).json()
        assert (
            withdrawn["state"] == "withheld"
            and withdrawn["text"] == ""
            and withdrawn["next_text"] is None
        )
        # A valid identifier with a different source never changes edition.
        assert (
            client.get(
                "/reader/read",
                params={"at": destination(pub, "epub:wrong", section_id="section-0")},
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/reader/read", params={"at": destination("f" * 32, source)}
            ).status_code
            == 410
        )

        def broken(*args):
            raise OSError("/private/synthetic-path")

        monkeypatch.setattr(published[2], "read_version", broken)
        failed = client.get("/reader/read", params={"at": at})
        assert failed.status_code == 503 and "/private/" not in failed.text
        assert "Retry this location" in failed.text and at in failed.text


def test_all_reading_routes_require_session_and_reject_unsafe_destinations(
    reader_env, published
):
    app, _, _ = reader_env
    source = published[4].search("salt")["results"][0]["citation"]["source_id"]
    at = destination(published[0].publication_id, source, section_id="section-0")
    with TestClient(app(), base_url="https://reader.example") as client:
        for route in ("read", "content"):
            r = client.get("/reader/" + route, params={"at": at})
            assert r.status_code == 401 and "Synthetic bean recipe" not in r.text
        login(client)
        for bad in (
            "https://evil.example",
            destination(published[0].publication_id, source, path="/private/book"),
            destination(published[0].publication_id, source, offset=-1),
        ):
            assert client.get("/reader/read", params={"at": bad}).status_code == 400
        assert (
            client.get(
                "/reader/content", params={"at": at}, headers={"Host": "evil.example"}
            ).status_code
            == 400
        )


def test_native_snapshot_occurrences_and_cursor_binding(
    reader_env, published, tmp_path
):
    """Hand-authored synthetic artifact; no capture, ingestion or inference."""
    import sqlite3

    from conftest import fixture_build

    from cookbook.book_capture import SCHEMA
    from cookbook.book_model import MODEL_PATH
    from cookbook.publication import Entry, publish
    from cookbook.storage import digest_file

    manifest, inputs = fixture_build(tmp_path / "native")
    pub = manifest.publication_id
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as index:
        source = index.execute("select id from sources").fetchone()[0]
    root = tmp_path / "native"
    path = root / MODEL_PATH
    path.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(
        SCHEMA
        + "CREATE TABLE model_info(payload TEXT); CREATE TABLE coverage(edition_id TEXT,payload TEXT);"
    )
    db.execute(
        "insert into model_info values(?)",
        (json.dumps({"publication_id": pub, "model_snapshot": {"id": "snapshot-1"}}),),
    )
    db.execute(
        "insert into editions values(?,?,?,?)",
        (
            "book-0",
            0,
            "Native beans",
            json.dumps(
                {
                    "id": "book-0",
                    "source_id": source,
                    "source_sha256": source.split(":")[1],
                    "title": "Native beans",
                    "authors": ["Fixture"],
                    "format": "EPUB",
                }
            ),
        ),
    )
    db.execute(
        "insert into coverage values(?,?)",
        ("book-0", json.dumps({"semantic_state": "partial"})),
    )
    db.execute(
        "insert into documents values(?,?,?,?,?)",
        (
            "doc",
            "book-0",
            "chapter.xhtml",
            "root",
            json.dumps({"parser_diagnostics": []}),
        ),
    )
    for n in range(2):
        db.execute(
            "insert into occurrences values(?,?,?,?,?)",
            (
                "occ-" + str(n),
                "book-0",
                "doc",
                n,
                json.dumps({"id": "occ-" + str(n), "ordinal": n}),
            ),
        )
    nodes = [
        (
            "root",
            0,
            2,
            "element",
            "document",
            "",
            {
                "id": "root",
                "kind": "element",
                "content_kind": "link",
                "child_ids": ["body", "tail"],
                "source_tag": "body",
            },
        ),
        (
            "body",
            1,
            1,
            "text",
            "text",
            "αβ🍲 beans " * 5000,
            {"id": "body", "kind": "text", "text": "αβ🍲 beans " * 5000},
        ),
    ]
    nodes.append(
        (
            "tail",
            2,
            2,
            "element",
            "link",
            "",
            {
                "id": "tail",
                "kind": "element",
                "content_kind": "link",
                "child_ids": [],
                "source_tag": "a",
            },
        )
    )
    for link_id, state, node in (
        ("late-resolved", "resolved_node", "body"),
        ("late-unresolved", "unresolved_link", None),
    ):
        db.execute(
            "insert into links values(?,?,?,?,?,?,?,?)",
            (
                link_id,
                "book-0",
                "doc",
                "tail",
                "doc",
                node,
                state,
                json.dumps(
                    {"target": {"state": state, "node_id": node, "document_id": "doc"}}
                ),
            ),
        )
    for id, ordinal, end, kind, content, text, payload in nodes:
        db.execute(
            "insert into nodes values(?,?,?,?,?,?,?,?,?,?)",
            (
                id,
                "doc",
                None,
                ordinal,
                end,
                kind,
                content,
                "/",
                text,
                json.dumps(payload),
            ),
        )
    db.execute(
        "insert into links values(?,?,?,?,?,?,?,?)",
        (
            "link",
            "book-0",
            "doc",
            "root",
            "doc",
            "body",
            "resolved_node",
            json.dumps(
                {
                    "target": {
                        "state": "resolved_node",
                        "node_id": "body",
                        "document_id": "doc",
                    }
                }
            ),
        ),
    )
    part = {
        "document_id": "doc",
        "reading_occurrence_id": "occ-1",
        "start": {"node_id": "root", "side": "before", "offset": None},
        "end": {"node_id": "root", "side": "after", "offset": None},
    }
    db.execute(
        "insert into spans values(?,?,?)",
        ("span", "book-0", json.dumps({"parts": [part]})),
    )
    db.execute(
        "insert into entities values(?,?,?,?,?)",
        (
            "recipe",
            "book-0",
            "recipe",
            "Synthetic recipe",
            json.dumps(
                {"id": "recipe", "state": "candidate", "evidence_span_ids": ["span"]}
            ),
        ),
    )
    for n in range(20):
        db.execute(
            "insert into entities values(?,?,?,?,?)",
            (
                "part-" + str(n),
                "book-0",
                "recipe_part",
                "Part",
                json.dumps(
                    {
                        "id": "part-" + str(n),
                        "kind": "recipe_part",
                        "state": "candidate",
                        "recipe_id": "recipe",
                        "ordinal": n,
                        "evidence_span_ids": ["span"],
                    }
                ),
            ),
        )
    db.commit()
    db.close()
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
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        entry = client.get(
            "/reader/content", params={"at": destination(pub, source)}
        ).json()
        assert len(entry["contents"]) == 2
        first = client.get(
            "/reader/content", params={"at": entry["contents"][1]["at"]}
        ).json()
        assert first["citation"]["model_snapshot_id"] == "snapshot-1"
        assert first["citations"][0]["reading_occurrence_id"] == "occ-1"
        assert len(first["references"]) == 1
        chunks = [first["text"]]
        while first["next_text"]:
            chunk_at = first["next_text"]
            first = client.get("/reader/content", params={"at": chunk_at}).json()
            assert first["citations"][0]["reading_occurrence_id"] == "occ-1"
            chunks.append(first["text"])
        assert "".join(chunks) == "αβ🍲 beans " * 5000
        assert len(first["references"]) == 2
        assert first["references"][0]["at"]
        assert first["references"][1]["at"] is None
        assert "unresolved" in first["references"][1]["label"]

        retry = client.get("/reader/content", params={"at": chunk_at}).json()
        assert retry["references"] == first["references"]
        assert len({ref["id"] for ref in retry["references"]}) == 2
        assert all(len(ref["id"]) == 64 for ref in retry["references"])
        recipe = destination(
            pub, source, target_id="recipe", model_snapshot_id="snapshot-1"
        )
        related = client.get("/reader/content", params={"at": recipe}).json()
        assert len(related["related"]) == 16
        assert len(related["references"]) == 1
        target = client.get(
            "/reader/read",
            params={"at": related["references"][0]["at"], "back": recipe},
        )
        assert (
            target.status_code == 200
            and "Return to originating location" in target.text
            and recipe in target.text
        )
        next_related = client.get(
            "/reader/content", params={"at": related["next_related"]}
        ).json()
        assert (
            len(next_related["related"]) == 4 and next_related["next_related"] is None
        )
        assert next_related["text"] == related["text"]
        next_text = client.get(
            "/reader/content", params={"at": related["next_text"]}
        ).json()
        assert next_text["citations"][0]["reading_occurrence_id"] == "occ-1"
        foreign = json.loads(
            base64.urlsafe_b64decode(
                related["next_text"] + "=" * (-len(related["next_text"]) % 4)
            )
        )
        foreign["target_id"] = "occ-0"
        assert (
            client.get(
                "/reader/read",
                params={
                    "at": destination(
                        pub,
                        source,
                        **{
                            k: v
                            for k, v in foreign.items()
                            if k not in {"publication_id", "book_id", "source_id"}
                        },
                    )
                },
            ).status_code
            == 404
        )
        bad = destination(
            pub, source, target_id="occ-1", model_snapshot_id="snapshot-wrong"
        )
        assert client.get("/reader/read", params={"at": bad}).status_code == 404
