"""The local demo stays synthetic and rejects non-loopback browser origins."""

import html
import importlib.util
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from lxml.html import fromstring
from starlette.testclient import TestClient

spec = importlib.util.spec_from_file_location(
    "preview_reader", Path(__file__).parents[1] / "scripts/preview_reader.py"
)
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def test_sample_reader_journey_and_local_boundary(tmp_path):
    with TestClient(preview.app(tmp_path), base_url="http://localhost:8766") as client:
        assert (
            client.get("/reader", headers={"host": "foreign.example"}).status_code
            == 403
        )
        assert (
            client.get(
                "/reader", headers={"origin": "https://foreign.example"}
            ).status_code
            == 403
        )
        catalog = client.get("/reader/login")
        assert catalog.status_code == 200
        assert "The Weeknight Table" in catalog.text
        assert "Local preview" in catalog.text
        assert "preview-reader" in client.cookies
        assert "__Host-reader" not in client.cookies
        book = re.findall(r'href="(/reader/book\?at=[^"]+)"', catalog.text)[0]
        contents = client.get(book)
        section = re.search(
            r'href="(/reader/read\?at=[^"]+&amp;back=[^"]+)"', contents.text
        )
        reading = client.get(html.unescape(section.group(1)))
        assert "INGREDIENTS" in reading.text and "Save bookmark" in reading.text
        assert reading.headers["cache-control"] == "private, no-store"
        session = client.get("/reader/session").json()
        denied = client.post(
            "/reader/search/results",
            json={"csrf": session["csrf"], "query": "lemon"},
            headers={"origin": "http://foreign.example"},
        )
        assert denied.status_code == 403
        search = client.post(
            "/reader/search/results",
            json={"csrf": session["csrf"], "query": "lemon"},
            headers={"origin": "http://localhost:8766"},
        )
        assert search.status_code == 200
        assert "Lemony white beans" in search.text
        soup_book = fromstring(catalog.text).xpath(
            '//li[contains(., "The Soup Notebook")]//a/@href'
        )[0]
        soup_contents = client.get(soup_book)
        soup_link = fromstring(soup_contents.text).xpath(
            '//a[text()="Tomato and lentil soup"]/@href'
        )[0]
        soup = client.get(soup_link)
        assert "unresolved amount" in soup.text
        form = fromstring(soup.text)
        at = parse_qs(urlsplit(soup_link).query)["at"][0]
        image = client.get("/reader/image", params={"at": at, "page": 1})
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"
        reference = form.xpath('//input[@name="reference"]/@value')[0]
        report = client.post(
            "/reader/reports",
            headers={"origin": "http://localhost:8766"},
            json={
                "csrf": session["csrf"],
                "reference": reference,
                "submission_id": "11111111111111111111111111111111",
                "description": "Local sample: please check the cumin quantity.",
            },
        )
        assert report.status_code == 200
        assert report.json()["status"] == "received"
