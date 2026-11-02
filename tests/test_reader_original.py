"""Authenticated HTTP originals using synthetic assets, never real rendering/OCR."""

import re
from html import unescape

from starlette.testclient import TestClient
from test_reader_content import destination
from test_reader_http import login

pytest_plugins = ["test_reader_http"]


def test_native_image_delivery_and_exact_text_return(reader_env, published):
    app, _, _ = reader_env
    pub = published[0].publication_id
    source = published[4].search("salt")["results"][0]["citation"]["source_id"]
    at = destination(pub, source, section_id="section-0", offset=4000)
    with TestClient(app(), base_url="https://reader.example") as client:
        assert (
            client.get(
                "/reader/image", params={"at": at, "image": "image-0"}
            ).status_code
            == 401
        )
        login(client)
        reading = client.get("/reader/read", params={"at": at})
        link = unescape(re.search(r'href="([^"]+)">Inspect originals', reading.text)[1])
        page = client.get(link)
        assert page.status_code == 200
        assert "EPUB images" in page.text and "facsimile" in page.text
        assert f"/reader/read?at={at}#text" in page.text
        assert "data-original-image" not in page.text
        page = client.get("/reader/original", params={"at": at, "image": "image-0"})
        assert "data-original-image" in page.text and "Synthetic beans" in page.text
        image = client.get("/reader/image", params={"at": at, "image": "image-0"})
        assert (
            image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
        )
        assert image.content[:2] == b"\xff\xd8"
        assert image.headers["cache-control"] == "private, no-store"
        assert "img-src 'self'" in page.headers["content-security-policy"]
        assert (
            client.get(
                "/reader/image", params={"at": at, "image": "foreign"}
            ).status_code
            == 404
        )


def scanned_original(published, tmp_path):
    import json
    import sqlite3

    from conftest import fixture_build

    from cookbook.publication import Entry, publish
    from cookbook.storage import digest_file

    m, inputs = fixture_build(tmp_path / "originals", section_count=3, repeats=1)
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        source = db.execute("select id from sources").fetchone()[0]
        db.execute("update sources set format='PDF'")
        db.execute(
            "update sections set locator=? where id=?",
            (
                json.dumps({"kind": "scanned-section", "physical_pages": [2, 1]}),
                "section-0",
            ),
        )
        for n in (1, 2):
            db.execute(
                "update sections set kind=?,ordinal=?,locator=? where id=?",
                (
                    "page",
                    n - 1,
                    json.dumps({"kind": "page", "physical_page": n}),
                    f"section-0-{n}",
                ),
            )
        db.execute(
            "insert into transcription_units values(?,?,?,?,?)",
            (
                "section-0",
                source,
                json.dumps("unapproved"),
                json.dumps(
                    [
                        {
                            "physical_page": 2,
                            "box": [0.1, 0.2, 0.4, 0.5],
                            "state": "unresolved",
                        },
                        {
                            "physical_page": 2,
                            "box": [0.5, 0.5, 0.9, 0.9],
                            "state": "crop_confirmed",
                        },
                    ]
                ),
                "[]",
            ),
        )
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
    return destination(m.publication_id, source, section_id="section-0")


def test_scanned_geometry_refusal_and_withheld_original(
    reader_env, published, tmp_path, monkeypatch
):
    import base64
    import hashlib
    import json

    from PIL import Image

    from cookbook.rendering import RenderError
    from cookbook.storage import canonical
    from cookbook.withdrawal import record_withdrawal

    at = scanned_original(published, tmp_path)

    def synthetic_render(path, fmt, page, destination, edge=1600):
        Image.new("RGB", (edge, edge // 2), "orange").save(destination, "PNG")

    monkeypatch.setattr("cookbook.library.render_page", synthetic_render)
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        page = client.get("/reader/original", params={"at": at})
        assert page.text.index("Physical page 2") < page.text.index("Physical page 1")
        page = client.get("/reader/original", params={"at": at, "page": 2})
        assert (
            "Unresolved content" in page.text
            and "Crop confirmed; not approval" in page.text
        )
        assert "[0.1, 0.2, 0.4, 0.5]" in page.text
        from io import BytesIO

        crop = client.get("/reader/image", params={"at": at, "page": 2, "region": 0})
        assert crop.status_code == 200
        assert Image.open(BytesIO(crop.content)).size == (720, 360)
        assert (
            client.get(
                "/reader/image", params={"at": at, "page": 1, "region": 0}
            ).status_code
            == 404
        )
        assert (
            client.get("/reader/image", params={"at": at, "page": 99}).status_code
            == 404
        )
        assert (
            client.get(
                "/reader/image", params={"at": at, "page": 2, "edge": 10000}
            ).status_code
            == 400
        )

        def refused(*args, **kwargs):
            raise RenderError("/private/book.pdf renderer busy")

        monkeypatch.setattr("cookbook.library.render_page", refused)
        failure = client.get("/reader/image", params={"at": at, "page": 2, "region": 0})
        assert failure.status_code == 503 and "/private/" not in failure.text
        assert "whole page" in failure.text and "same text position" in failure.text
        assert client.get("/reader/content", params={"at": at}).json()["text"]
        source = json.loads(base64.urlsafe_b64decode(at + "=" * (-len(at) % 4)))[
            "source_id"
        ]
        event = {
            "action": "revoke",
            "actor": {"kind": "human"},
            "affected_decisions": [],
            "affected_pages": [
                {"source_sha256": source.split(":")[1], "physical_page": 2}
            ],
        }
        event["id"] = hashlib.sha256(canonical(event)).hexdigest()
        record_withdrawal(published[2], event)
        assert (
            client.get("/reader/content", params={"at": at}).json()["state"]
            == "withheld"
        )
        monkeypatch.setattr("cookbook.library.render_page", synthetic_render)
        assert (
            client.get("/reader/image", params={"at": at, "page": 2}).status_code == 200
        )


def test_original_expiry_and_busy_recovery_are_bounded(
    reader_env, published, tmp_path, monkeypatch
):
    at = scanned_original(published, tmp_path)
    app, _, clock = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from PIL import Image

        started, release = Event(), Event()

        def slow_renderer(path, fmt, page, destination, edge=1600):
            started.set()
            assert release.wait(5)
            Image.new("RGB", (100, 100), "orange").save(destination, "PNG")

        monkeypatch.setattr("cookbook.library.render_page", slow_renderer)
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(
                client.get, "/reader/image", params={"at": at, "page": 2}
            )
            try:
                assert started.wait(5)
                response = client.get("/reader/image", params={"at": at, "page": 2})
                assert response.status_code == 503 and "busy" in response.text
                assert "Retry selected original" in response.text
            finally:
                release.set()
            assert first.result(timeout=5).status_code == 200
        clock[0] += 31 * 86400
        assert (
            client.get("/reader/image", params={"at": at, "page": 2}).status_code == 401
        )
        assert (
            client.get("/reader/original", params={"at": at, "page": 2}).status_code
            == 401
        )


def test_whole_book_native_images_bind_snapshot_and_document(
    reader_env, published, tmp_path
):
    import json
    import sqlite3

    from conftest import fixture_build

    from cookbook.book_capture import SCHEMA
    from cookbook.book_model import MODEL_PATH
    from cookbook.publication import Entry, publish
    from cookbook.storage import digest_file

    m, inputs = fixture_build(tmp_path / "native-original", repeats=1)
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        source = db.execute("select id from sources").fetchone()[0]
    path = tmp_path / "native-original" / MODEL_PATH
    path.parent.mkdir(exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            SCHEMA
            + "CREATE TABLE model_info(payload TEXT); CREATE TABLE coverage(edition_id TEXT,payload TEXT);"
        )
        db.execute(
            "insert into model_info values(?)",
            (
                json.dumps(
                    {
                        "publication_id": m.publication_id,
                        "model_snapshot": {"id": "snapshot-1"},
                    }
                ),
            ),
        )
        edition = {
            "id": "book-0",
            "source_id": source,
            "source_sha256": source.split(":")[1],
            "title": "Native beans",
            "authors": ["Fixture"],
            "format": "EPUB",
        }
        db.execute(
            "insert into editions values(?,?,?,?)",
            ("book-0", 0, "Native beans", json.dumps(edition)),
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
        db.execute(
            "insert into occurrences values(?,?,?,?,?)",
            ("occ", "book-0", "doc", 0, json.dumps({"id": "occ", "ordinal": 0})),
        )
        node = {"id": "root", "kind": "text", "text": "Native text"}
        db.execute(
            "insert into nodes values(?,?,?,?,?,?,?,?,?,?)",
            (
                "root",
                "doc",
                None,
                0,
                0,
                "text",
                "text",
                "Native text",
                None,
                json.dumps(node),
            ),
        )
    inputs[MODEL_PATH] = path
    m.files.append(
        Entry(
            path=MODEL_PATH,
            sha256=digest_file(path)[0],
            size=path.stat().st_size,
            role="runtime",
        )
    )
    publish(
        published[2],
        m,
        inputs,
        expected_version=published[2].read_version("control/active.json")[1],
        activate=published[3].activate,
    )
    at = destination(
        m.publication_id, source, target_id="occ", model_snapshot_id="snapshot-1"
    )
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        page = client.get("/reader/original", params={"at": at, "image": "image-0"})
        assert page.status_code == 200 and "Native text" in page.text
        assert (
            client.get(
                "/reader/image", params={"at": at, "image": "image-0"}
            ).status_code
            == 200
        )
        foreign = destination(
            m.publication_id, source, target_id="occ", model_snapshot_id="foreign"
        )
        assert (
            client.get(
                "/reader/image", params={"at": foreign, "image": "image-0"}
            ).status_code
            == 404
        )


def test_active_image_payload_is_refused_and_cannot_load_external_resources(
    reader_env, published, tmp_path
):
    from conftest import fixture_build

    from cookbook.publication import Entry, publish
    from cookbook.storage import digest_file

    m, inputs = fixture_build(tmp_path / "hostile-image", repeats=1)
    inputs["assets/image"].write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>private_evil()</script></svg>'
    )
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
    source = published[4].get_book(m.publication_id, "book-0")["citation"]["source_id"]
    at = destination(m.publication_id, source, section_id="section-0")
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        response = client.get("/reader/image", params={"at": at, "image": "image-0"})
        assert response.status_code == 503 and "private_evil" not in response.text
        assert "same text position" in response.text
        foreign = destination(m.publication_id, "epub:foreign", section_id="section-0")
        assert (
            client.get(
                "/reader/image", params={"at": foreign, "image": "image-0"}
            ).status_code
            == 404
        )
        duplicate = client.get(
            "/reader/image", params=[("at", at), ("page", "1"), ("page", "2")]
        )
        assert duplicate.status_code == 400
