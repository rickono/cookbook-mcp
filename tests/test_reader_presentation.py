"""Safe assembled HTTP checks; no observed browser/device claims or ingestion."""

import pytest
from lxml import html
from starlette.testclient import TestClient
from test_reader_content import destination
from test_reader_http import login

pytest_plugins = ["test_reader_http"]


def test_reading_and_original_offer_kitchen_without_losing_source(
    reader_env, published
):
    app, _, _ = reader_env
    citation = published[4].search("salt")["results"][0]["citation"]
    at = destination(
        published[0].publication_id, citation["source_id"], section_id="section-0"
    )
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        for path in ("/reader/read", "/reader/original"):
            page = client.get(path, params={"at": at})
            assert page.status_code == 200
            doc = html.fromstring(page.text)
            assert doc.xpath('//button[@data-kitchen][@aria-pressed="false"]')
            assert doc.xpath('//a[@href="#reader-main"]')
            assert doc.xpath('//main[@id="reader-main"][@tabindex="-1"]')
            assert doc.xpath('//script[@src="/reader/presentation.js"]')
            assert "private, no-store" == page.headers["cache-control"]
            assert at in page.text
        css = client.get("/reader/presentation.css")
        assert css.status_code == 200
        assert "22px" in css.text and "52px" in css.text


def test_original_roundtrip_keeps_authored_reference_return(reader_env, published):
    from urllib.parse import parse_qs, urlsplit

    app, _, _ = reader_env
    citation = published[4].search("salt")["results"][0]["citation"]
    at = destination(
        published[0].publication_id,
        citation["source_id"],
        section_id="section-0",
        offset=4000,
    )
    back = destination(
        published[0].publication_id, citation["source_id"], section_id="section-0"
    )
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        doc = html.fromstring(
            client.get("/reader/read", params={"at": at, "back": back}).text
        )
        original = doc.xpath('//a[starts-with(@href,"/reader/original?")]/@href')[0]
        assert parse_qs(urlsplit(original).query)["back"] == [back]
        page = client.get(original)
        assert page.status_code == 200
        doc = html.fromstring(page.text)
        returned = doc.xpath('//a[contains(text(),"Return to same text")]/@href')[0]
        assert parse_qs(urlsplit(returned).query) == {"at": [at], "back": [back]}
        assert urlsplit(returned).fragment == "text"


@pytest.mark.parametrize("anonymous_paths", [False, True])
def test_native_table_continuation_is_labelled_focusable_and_escaped(
    reader_env, published, tmp_path, anonymous_paths
):
    """Hand-authored native rows, with a long cell crossing the delivery budget."""
    import json
    import sqlite3

    from conftest import fixture_build

    from cookbook.book_capture import SCHEMA
    from cookbook.book_model import MODEL_PATH
    from cookbook.publication import Entry, publish
    from cookbook.storage import digest_file

    root = tmp_path / "table"
    manifest, inputs = fixture_build(root)
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        source = db.execute("select id from sources").fetchone()[0]
    path = root / MODEL_PATH
    path.parent.mkdir(exist_ok=True)
    cell = "<img src='https://evil.example'> beans " * 1800
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
                        "publication_id": manifest.publication_id,
                        "model_snapshot": {"id": "table-snapshot"},
                    }
                ),
            ),
        )
        db.execute(
            "insert into editions values(?,?,?,?)",
            (
                "book-0",
                0,
                "Table book",
                json.dumps(
                    {
                        "id": "book-0",
                        "source_id": source,
                        "source_sha256": source.split(":")[1],
                        "title": "Table book",
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
            ("doc", "book-0", "table.xhtml", "table", "{}"),
        )
        db.execute(
            "insert into occurrences values(?,?,?,?,?)",
            ("occ", "book-0", "doc", 0, json.dumps({"id": "occ", "ordinal": 0})),
        )
        for i, (nid, kind, content, xpath, text) in enumerate(
            [
                ("table", "element", "table", "/html/body/table[1]", ""),
                ("row", "element", "table_row", "/html/body/table[1]/tr[1]", ""),
                (
                    "cell",
                    "element",
                    "table_cell",
                    "/html/body/table[1]/tr[1]/td[1]",
                    "",
                ),
                ("text", "text", "text", "/html/body/table[1]/tr[1]/td[1]", cell),
            ]
        ):
            if anonymous_paths:
                xpath = "/*/*/*" + "/node()" * i
            payload = {
                "document_id": "doc",
                "preorder": i,
                "id": nid,
                "kind": kind,
                "content_kind": content,
                "source_xpath": xpath,
                "text": text,
                "source_slot": "text",
            }
            if kind == "element":
                payload["child_ids"] = [["row"], ["cell"], ["text"]][i]
            db.execute(
                "insert into nodes values(?,?,?,?,?,?,?,?,?,?)",
                (
                    nid,
                    "doc",
                    None,
                    i,
                    3,
                    kind,
                    content,
                    xpath,
                    text,
                    json.dumps(payload),
                ),
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
    app, _, _ = reader_env
    at = destination(
        manifest.publication_id,
        source,
        target_id="occ",
        model_snapshot_id="table-snapshot",
    )
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        text = ""
        count = 0
        while at:
            page = client.get("/reader/read", params={"at": at})
            doc = html.fromstring(page.text)
            regions = doc.xpath('//div[@role="region"][@tabindex="0"][@aria-label]')
            assert regions and "Table" in regions[0].get("aria-label")
            assert not doc.xpath("//img")
            data = client.get("/reader/content", params={"at": at}).json()
            assert any(b["kind"] == "table" for b in data["text_blocks"])
            text += data["text"]
            at = data["next_text"]
            count += 1
        assert count > 1
        assert text == "\n\n | " + cell
