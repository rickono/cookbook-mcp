"""Cross-feature public HTTP journey, hand-authored data; never ingestion/OCR."""

import math
import time
from urllib.parse import parse_qs, urlsplit

from lxml import html
from starlette.testclient import TestClient
from test_reader_content import destination, publish_scanned
from test_reader_http import login
from test_reader_search import search
from test_reader_updates import update

from cookbook.owner_reports import OwnerReports
from cookbook.reader_personal import PersonalState
from cookbook.storage import LocalStore

pytest_plugins = ["test_reader_http"]
ORIGIN = {"Origin": "https://reader.example"}


def test_search_read_original_save_update_restart_and_logout(
    reader_env, published, tmp_path
):
    factory, _, _ = reader_env
    personal = LocalStore(tmp_path / "personal")
    reports = LocalStore(tmp_path / "reports")

    def app():
        return factory(
            personal_state=PersonalState(personal), owner_reports=OwnerReports(reports)
        )

    with TestClient(app(), base_url="https://reader.example") as a:
        assert login(a).status_code == 303
        assert a.get("/reader/catalog").status_code == 200
        hit = search(a).json()["groups"]["section"]["results"][0]
        at = parse_qs(urlsplit(hit["href"]).query)["at"][0]
        first = a.get("/reader/content", params={"at": at}).json()
        assert first["state"] == "partial_text"
        # Follow every continuation and compare to the independent authored fixture.
        chunks, cursor = first["text"], first["next_text"]
        while cursor:
            chunk = a.get("/reader/content", params={"at": cursor}).json()
            assert (
                chunk["citation"]["publication_id"]
                == first["citation"]["publication_id"]
            )
            chunks += chunk["text"]
            cursor = chunk["next_text"]
        assert chunks == (
            "Synthetic bean recipe 0. Use 1/2 teaspoon salt and 200 grams beans. Simmer 20 minutes. "
            * 1000
        )
        image = a.get("/reader/image", params={"at": at, "image": "image-0"})
        assert (
            image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
        )
        assert image.headers["cache-control"] == "private, no-store"
        csrf = a.get("/reader/session").json()["csrf"]
        saved = a.post(
            "/reader/personal",
            headers=ORIGIN,
            json={
                "csrf": csrf,
                "action": "save",
                "operation_id": "a" * 32,
                "at": at,
                "name": "Synthetic supper",
            },
        )
        assert saved.status_code == 200
        current = update(published, tmp_path, text="Current synthetic supper")
        notice = a.get("/reader/updates", params={"at": at}).json()
        assert notice["current_publication_id"] == current
        assert (
            a.get("/reader/content", params={"at": at}).json()["text"] == first["text"]
        )
        cookies = a.cookies
    with TestClient(app(), base_url="https://reader.example") as b:
        login(b)  # Independent session, new app over the same production stores.
        bookmark = b.get("/reader/personal").json()["bookmarks"][0]
        assert bookmark["name"] == "Synthetic supper"
        assert (
            b.get("/reader/content", params={"at": bookmark["at"]}).json()["text"]
            == "Current synthetic supper"
        )
        pub, source = publish_scanned(published, tmp_path)
        report_at = destination(pub, source, section_id="section-0")
        page = html.fromstring(b.get("/reader/read", params={"at": report_at}).text)
        reference = page.xpath('//input[@name="reference"]/@value')[0]
        payload = {
            "csrf": b.get("/reader/session").json()["csrf"],
            "reference": reference,
            "submission_id": "b" * 32,
            "description": "Synthetic quantity needs checking",
        }
        receipt = b.post("/reader/reports", json=payload, headers=ORIGIN)
        assert receipt.status_code == 200 and receipt.json()["status"] == "received"
        assert (
            b.post("/reader/reports", json=payload, headers=ORIGIN).json()
            == receipt.json()
        )
        logout = b.post(
            "/reader/logout",
            headers=ORIGIN,
            data={
                "csrf": payload["csrf"],
                "scope": "all",
            },
        )
        assert logout.status_code == 200
    with TestClient(app(), base_url="https://reader.example", cookies=cookies) as a:
        assert a.get("/reader/personal").status_code == 401
        assert a.get("/reader/read", params={"at": at}).status_code == 401


def test_local_http_timing_probe(reader_env):
    """Diagnostic only: ASGI/SQLite, no network shaping or hosted budget claim."""
    factory, _, _ = reader_env
    with TestClient(factory(), base_url="https://reader.example") as client:
        login(client)
        timings = []
        for _ in range(21):
            start = time.perf_counter()
            result = search(client)
            assert result.status_code == 200
            hit = result.json()["groups"]["section"]["results"][0]
            assert client.get(hit["href"]).status_code == 200
            timings.append(round((time.perf_counter() - start) * 1000, 2))
        print(
            {
                "environment": "local ASGI synthetic section search plus HTML read",
                "network_shaped": False,
                "cold_ms": timings[0],
                "warm_samples": 20,
                "warm_p95_ms": sorted(timings[1:])[math.ceil(20 * 0.95) - 1],
            }
        )
