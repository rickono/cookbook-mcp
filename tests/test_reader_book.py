"""Synthetic original sources and authenticated delivery; no ingestion or OCR."""

from urllib.parse import parse_qs, urlsplit

from lxml import html
from starlette.testclient import TestClient
from test_reader_preview import preview

from cookbook.reader_content import decode_location, encode_location


def entry(client, catalog, title):
    tree = html.fromstring(catalog.text)
    href = tree.xpath("//li[contains(., $title)]//a/@href", title=title)[0]
    page = client.get(href)
    return html.fromstring(page.text)


def test_originals_are_default_and_source_delivery_supports_authenticated_ranges(
    tmp_path,
):
    with TestClient(preview.app(tmp_path), base_url="http://localhost:8766") as client:
        assert client.get("/reader/source", params={"at": "invalid"}).status_code == 401
        catalog = client.get("/reader/login")
        for title, fmt, magic in [
            ("The Weeknight Table", "EPUB", b"PK"),
            ("The Soup Notebook", "PDF", b"%PDF-"),
        ]:
            page = entry(client, catalog, title)
            at = page.xpath("//section[@data-book-at]/@data-book-at")[0]
            full = client.get("/reader/source", params={"at": at})
            assert full.status_code == 200 and full.content.startswith(magic)
            assert full.headers["cache-control"] == "private, no-store"
            assert full.headers["accept-ranges"] == "bytes"
            assert full.headers["content-type"] == (
                "application/pdf" if fmt == "PDF" else "application/epub+zip"
            )
            head = client.head("/reader/source", params={"at": at})
            assert head.status_code == 200 and not head.content
            assert head.headers["content-type"] == full.headers["content-type"]
            partial = client.get(
                "/reader/source", params={"at": at}, headers={"Range": "bytes=0-31"}
            )
            assert partial.status_code == 206 and partial.content == full.content[:32]
            assert partial.headers["content-range"] == f"bytes 0-31/{len(full.content)}"
            tail = client.get(
                "/reader/source", params={"at": at}, headers={"Range": "bytes=-15"}
            )
            assert tail.content == full.content[-15:]
            assert (
                client.get(
                    "/reader/source",
                    params={"at": at},
                    headers={"Range": "bytes=999999999-"},
                ).status_code
                == 416
            )
            assert (
                client.get(
                    "/reader/source", params={"at": at, "path": "/etc/passwd"}
                ).status_code
                == 400
            )
            bad = {**decode_location(at), "source_id": "epub:" + "f" * 64}
            assert (
                client.get(
                    "/reader/source", params={"at": encode_location(bad)}
                ).status_code
                == 404
            )
            text = page.xpath('//a[text()="Text view"]/@href')[0]
            assert client.get(text).status_code == 200
            chapter = page.xpath('//nav[@aria-label="Book contents"]/a/@href')[0]
            selected = parse_qs(urlsplit(chapter).query)["at"][0]
            info = client.get("/reader/book-info", params={"at": selected}).json()
            assert info["format"] == fmt
            if fmt == "EPUB":
                assert (
                    info["epub_document"] == "weeknight-0.xhtml"
                    and info["epub_anchor"] == "start"
                )
            else:
                assert info["physical_page"] == 1
        client.cookies.clear()
        assert client.get("/reader/source", params={"at": at}).status_code == 401
        assert client.get("/reader/book-info", params={"at": at}).status_code == 401
        assert client.get("/reader/book-view", params={"at": at}).status_code == 401


def test_public_vendor_assets_are_bounded_to_the_packaged_directory(tmp_path):
    with TestClient(preview.app(tmp_path), base_url="http://localhost:8766") as client:
        for name in [
            "pdfjs-dist/build/pdf.mjs",
            "epubjs/dist/epub.min.js",
            "jszip/dist/jszip.min.js",
        ]:
            response = client.get("/reader/vendor/" + name)
            assert response.status_code == 200 and response.headers[
                "content-type"
            ].startswith("text/javascript")
        assert client.get("/reader/vendor/%2e%2e/reader.py").status_code == 404
        assert client.get("/reader/vendor/unknown.js").status_code == 404
        assert client.get("/reader/vendor/a%00b").status_code == 404
        assert (
            client.get("/reader/vendor/pdfjs-dist/build/pdf%202.mjs").status_code == 404
        )


def test_original_reader_preserves_stable_personal_controls(
    reader_env, published, tmp_path
):
    from test_reader_content import destination
    from test_reader_http import login
    from test_reader_updates import fixture_source

    from cookbook.reader_personal import PersonalState
    from cookbook.storage import LocalStore

    app, _, _ = reader_env
    at = destination(
        published[0].publication_id, fixture_source(published), section_id="section-0"
    )
    with TestClient(
        app(personal_state=PersonalState(LocalStore(tmp_path / "personal"))),
        base_url="https://reader.example",
    ) as client:
        login(client)
        page = html.fromstring(client.get("/reader/book-view", params={"at": at}).text)
        controls = page.xpath('//section[@id="reader-personal"]')
        assert controls and controls[0].get("data-stable") == "true"
        info = client.get("/reader/book-info", params={"at": at}).json()
        assert decode_location(info["personal_at"])["section_id"] == "section-0"
        assert info["personal_stable"] is True
        assert page.xpath('//script[@src="/reader/personal.js"]')


def test_retired_original_location_keeps_explicit_source_bound_recovery(
    reader_env, published, tmp_path
):
    import shutil

    from test_reader_content import destination
    from test_reader_http import login
    from test_reader_updates import fixture_source, update

    app, _, _ = reader_env
    old = published[0].publication_id
    at = destination(old, fixture_source(published), section_id="section-0")
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        stable = client.get("/reader/content", params={"at": at}).json()[
            "source_location"
        ]
        durable = encode_location(stable)
        update(published, tmp_path, text="Current synthetic beans")
        shutil.rmtree(published[3].root / "versions" / old)
        retired = client.get("/reader/book-view", params={"at": durable})
        assert retired.status_code == 410 and retired.headers[
            "content-type"
        ].startswith("text/html")
        page = html.fromstring(retired.text)
        assert page.xpath('//a[starts-with(@href,"/reader/book-view?")]')
        assert not page.xpath('//a[starts-with(@href,"/reader/read?")]')
        assert (
            client.get("/reader/book-info", params={"at": durable}).status_code == 410
        )
        unavailable = client.get("/reader/book-view", params={"at": at})
        assert unavailable.status_code == 410
        assert not html.fromstring(unavailable.text).xpath(
            '//a[starts-with(@href,"/reader/book-view?")]'
        )


pytest_plugins = ["test_reader_http"]


def test_unsupported_original_format_keeps_the_existing_text_reader(
    reader_env, published, tmp_path
):
    import sqlite3

    from conftest import fixture_build
    from test_reader_content import destination
    from test_reader_http import login

    from cookbook.publication import Entry, publish
    from cookbook.storage import digest_file

    manifest, inputs = fixture_build(tmp_path / "djvu", repeats=1)
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        old = db.execute("select id from sources").fetchone()[0]
        source = "djvu:" + old.split(":")[1]
        db.execute("update sources set id=?,format='DJVU' where id=?", (source, old))
        for table in ("books", "sections", "images"):
            db.execute(
                f"update {table} set source_id=? where source_id=?", (source, old)
            )
        db.execute(
            "update sections set locator=?", ('{"kind":"page","physical_page":1}',)
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
    app, _, _ = reader_env
    at = destination(manifest.publication_id, source, section_id="section-0")
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        redirect = client.get(
            "/reader/book-view", params={"at": at}, follow_redirects=False
        )
        assert redirect.status_code == 303 and redirect.headers["location"].startswith(
            "/reader/read?"
        )
        fallback = client.get(redirect.headers["location"])
        assert fallback.status_code == 200 and "Synthetic bean recipe" in fallback.text


def test_vendor_bundle_contains_only_the_reproduced_assets():
    import hashlib
    import json
    import subprocess
    import zipfile
    from pathlib import Path

    root = Path(__file__).parents[1] / "src/cookbook/book_vendor"
    manifest = json.loads((root / "assets.json").read_text())
    with zipfile.ZipFile(root / "assets.zip") as archive:
        assert set(archive.namelist()) == set(manifest)
        assert len(archive.namelist()) == len(manifest)
        assert not any(" 2" in name or " 3" in name for name in archive.namelist())
        for name, digest in manifest.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    visible = set(
        subprocess.check_output(
            ["git", "ls-files", "-c", "-o", "--exclude-standard", "--", str(root)],
            cwd=root.parents[2],
        )
        .decode()
        .splitlines()
    )
    assert {Path(name).name for name in visible} == {
        ".gitignore",
        "assets.json",
        "assets.zip",
        "packages.json",
    }


def test_original_reader_errors_remain_html_and_keep_retry_recovery(
    reader_env, published, monkeypatch
):
    from test_reader_content import destination
    from test_reader_http import login
    from test_reader_updates import fixture_source

    from cookbook import reader_book

    app, _, _ = reader_env
    at = destination(
        published[0].publication_id, fixture_source(published), section_id="section-0"
    )
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        invalid = client.get("/reader/book-view", params={"at": "invalid"})
        assert invalid.status_code == 400 and invalid.headers[
            "content-type"
        ].startswith("text/html")
        assert html.fromstring(invalid.text).xpath("//main")

        def fail(*args):
            raise RuntimeError("synthetic failure with no source contents")

        monkeypatch.setattr(reader_book, "information", fail)
        interrupted = client.get("/reader/book-view", params={"at": at})
        assert interrupted.status_code == 503 and interrupted.headers[
            "content-type"
        ].startswith("text/html")
        page = html.fromstring(interrupted.text)
        assert page.xpath('//a[starts-with(@href,"/reader/book-view?")]')
        assert "synthetic failure" not in interrupted.text
        assert page.xpath('//meta[@name="reader-stage"]/@content') == [
            "content_deliver"
        ]
