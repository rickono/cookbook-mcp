"""Dashboard HTTP behavior with synthetic metadata only; no OCR or source parsing."""

import asyncio
import json
import sqlite3
import time

import httpx
import pytest

from cookbook.dashboard.cli import demo_config
from cookbook.dashboard.runtime import Dashboard
from cookbook.dashboard.web import create_app
from cookbook.usage import UsageRecorder, aggregate


def request(
    dashboard, path="/", *, method="GET", headers=None, base="http://127.0.0.1:8770"
):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(dashboard)), base_url=base
        ) as client:
            return await client.request(method, path, headers=headers)

    return asyncio.run(run())


@pytest.fixture
def dashboard(tmp_path):
    d = Dashboard(demo_config(tmp_path))
    d.refresh(wait=True)
    return d


def test_inventory_identity_missing_records_and_details(dashboard):
    result = request(dashboard, "/api/snapshot").json()
    assert result["summary"]["included"] == 3
    assert result["summary"]["undecided"] == 1
    pantry = next(b for b in result["books"] if b["id"] == "sha256:" + "a" * 64)
    assert len(pantry["aliases"]) == 2
    pending = next(
        b for b in result["books"] if b["title"] == "Pending kitchen notebook"
    )
    assert pending["provisional"] and pending["states"]["processing"] == "unknown"
    assert len(pantry["queue"]) == 1
    assert pantry["queue"][0]["origins"] == ["build", "triage"]
    assert pantry["states"]["publication"] == "catalog present"
    assert pantry["states"]["access"] == "unknown"
    assert pantry["heartbeats"][0]["activity"] == "heartbeat overdue"
    html = request(dashboard, "/book", headers={}).text
    assert html == "Unknown edition"
    from urllib.parse import urlencode

    detail = request(dashboard, "/book?" + urlencode({"id": pantry["id"]})).text
    assert "terminal refusal" in detail and "demo-new-candidate" in detail
    assert "Retry" not in detail and "Owner queue" in detail
    assert result["owner_queue_total"] is None


def test_filters_escaping_and_local_http_boundary(dashboard):
    page = request(dashboard, "/?q=Pending").text
    assert (
        "Pending kitchen notebook" in page
        and 'class="book-title" href="/book?id=sha256' not in page
    )
    assert "Undecided discovery" in request(dashboard, "/?membership=undecided").text
    malicious = request(dashboard, "/?q=%22%3E%3Cscript%3Ealert(1)%3C/script%3E").text
    assert "<script>alert(1)</script>" not in malicious
    assert "&lt;script&gt;" in malicious
    assert request(dashboard, base="http://evil.example").status_code == 403
    assert (
        request(dashboard, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert request(dashboard, "/refresh", method="POST").status_code == 303
    assert request(dashboard, "/book", method="POST").status_code == 405
    assert request(dashboard, "/etc/passwd").status_code == 404
    assert request(dashboard).headers["cache-control"] == "no-store"


def test_failure_retains_previous_evidence_and_restart(dashboard):
    path = dashboard.sources[1]["path"]
    previous = next(
        o for o in dashboard.snapshot()["observations"] if o["id"] == "demo-status"
    )["observed_at"]
    from pathlib import Path

    Path(path).write_text("{broken")
    dashboard.refresh(wait=True)
    snap = dashboard.snapshot()
    obs = next(o for o in snap["observations"] if o["id"] == "demo-status")
    assert obs["status"] == "unknown" and obs["observed_at"] == previous
    pantry = next(b for b in snap["books"] if b["id"] == "sha256:" + "a" * 64)
    assert pantry["states"]["publication"] == "unknown"
    assert pantry["facts"] and not pantry["facts"][0]["current"]
    assert pantry["heartbeats"][0]["activity"] == "unknown"
    assert "unknown; previous evidence: catalog present" in request(dashboard).text
    restored = Dashboard(dashboard.config)
    assert restored.snapshot()["summary"]["included"] == 3
    assert all(o["status"] == "unknown" for o in restored.snapshot()["observations"])


def test_staleness_and_conflicting_alias_membership(dashboard):
    from pathlib import Path

    registry = Path(dashboard.sources[0]["path"])
    data = json.loads(registry.read_text())
    data["records"][1]["membership"] = "excluded"
    registry.write_text(json.dumps(data))
    dashboard.refresh(wait=True)
    assert dashboard.snapshot()["summary"]["conflict"] == 1
    now = dashboard.clock()
    dashboard.clock = lambda: now + 61
    snap = dashboard.snapshot()
    assert all(o["stale"] for o in snap["observations"])
    assert all(b["states"]["publication"] == "unknown" for b in snap["books"])


def test_sources_unchanged_by_reading_and_storage_disjoint(dashboard):
    from pathlib import Path

    before = {s["path"]: Path(s["path"]).read_bytes() for s in dashboard.sources}
    for route in ("/", "/api/snapshot", "/analytics", "/observations"):
        assert request(dashboard, route).status_code == 200
    dashboard.refresh(wait=True)
    assert all(Path(p).read_bytes() == value for p, value in before.items())
    config = dict(
        dashboard.config, storage=str(Path(dashboard.sources[0]["path"]).parent)
    )
    with pytest.raises(ValueError):
        Dashboard(config)


def test_candidate_coverage_metadata_only_and_mismatch(dashboard, tmp_path):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "version": "scanned-candidate.v1",
                "source": {"sha256": "a" * 64, "physical_pages": 10},
                "coverage": {
                    "pages_total": 10,
                    "transcribed": 5,
                    "blank": 1,
                    "failed": 2,
                },
                "counts": {"unresolved": 3},
            }
        )
    )
    dashboard.sources.append(
        {"id": "candidate", "kind": "candidate", "path": str(candidate)}
    )
    dashboard.refresh(wait=True)
    book = next(
        b for b in dashboard.snapshot()["books"] if b["id"] == "sha256:" + "a" * 64
    )
    assert book["coverage"][0]["coverage"]["unaccounted"] == 2
    assert "2 unaccounted" in request(dashboard).text
    dashboard.sources[-1]["edition"] = "sha256:" + "b" * 64
    dashboard.refresh(wait=True)
    assert dashboard.snapshot()["observations"][-1]["status"] == "unknown"


def test_index_reads_metadata_without_text_or_runtime_constructor(dashboard, tmp_path):
    path = tmp_path / "index.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE info(publication_id); INSERT INTO info VALUES ('pub-A'); CREATE TABLE books(id,title,source_id); CREATE TABLE sources(id,sha256,format); CREATE TABLE sections(source_id,text);"
        )
        db.execute(
            "INSERT INTO books VALUES ('book-A','Synthetic published book','pdf:a')"
        )
        db.execute("INSERT INTO sources VALUES ('pdf:a',?,'PDF')", ("a" * 64,))
        db.execute(
            "INSERT INTO sections VALUES ('pdf:a','DO NOT DISCLOSE source payload')"
        )
    before = path.read_bytes()
    dashboard.sources.append(
        {"id": "published", "kind": "index", "path": str(path), "publication": "pub-A"}
    )
    dashboard.refresh(wait=True)
    assert path.read_bytes() == before
    snap = request(dashboard, "/api/snapshot").text
    assert "1 indexed sections" in snap and "DO NOT DISCLOSE" not in snap
    assert not (tmp_path / "index.sqlite-journal").exists()
    dashboard.sources[-1]["publication"] = "pub-B"
    dashboard.refresh(wait=True)
    assert dashboard.snapshot()["observations"][-1]["status"] == "unknown"


def test_timeout_does_not_spawn_replacements_or_block_local(tmp_path):
    import threading

    release = threading.Event()
    calls = []

    def reader(source):
        calls.append(source["id"])
        if source["id"] == "blocked":
            release.wait(2)
        return {"records": []}

    config = demo_config(tmp_path)
    config["sources"][0]["id"] = "blocked"
    d = Dashboard(config, reader=reader)
    try:
        d.tick()
        d.flights["blocked"]["started"] -= 6
        time.sleep(0.02)
        d.tick()
        snap = d.snapshot()
        assert snap["observations"][0]["status"] == "unknown"
        assert snap["observations"][1]["status"] == "ok"
        d.tick(force=True)
        assert calls.count("blocked") == 1
    finally:
        release.set()


def test_retention_and_failed_snapshot_preserves_previous(dashboard):
    old = (dashboard.storage / "snapshot.json").read_bytes()
    dashboard.config["max_storage_bytes"] = 1
    dashboard.refresh(wait=True)
    assert dashboard.snapshot()["storage_error"]
    assert (dashboard.storage / "snapshot.json").read_bytes() == old
    assert len(list(dashboard.storage.glob("history-*"))) <= 2


def test_collection_not_started_and_telemetry_privacy(dashboard, tmp_path):
    assert "usage collection not started" in request(dashboard, "/analytics").text
    path = tmp_path / "usage.sqlite"
    recorder = UsageRecorder(path)
    kwargs = {
        "publication_id": "pub-A",
        "source_id": "pdf:" + "a" * 64,
        "book_id": "alias-A",
        "section_id": "s1",
        "query": "PRIVATE QUERY",
        "offset": 40,
    }
    for _ in range(2):
        recorder.record(
            "read_section", kwargs, {"text": "PRIVATE TEXT"}, event_id="event-1"
        )
    recorder.record("read_section", kwargs, {"text": "PRIVATE TEXT"})
    recorder.record("read_section", kwargs, {"text": ""})
    recorder.record(
        "get_page",
        {**kwargs, "physical_page": 1, "region": [0, 0, 1, 1]},
        {},
        error=True,
    )
    assert b"PRIVATE" not in path.read_bytes()
    dashboard.config["usage"] = [str(path)]
    result = request(dashboard, "/api/usage").json()
    assert result["totals"]["read_section:success"] == 2
    assert result["totals"]["read_section:withheld"] == 1
    assert result["totals"]["get_page_zoom:error"] == 1
    assert result["unique_content_scopes"] == 1
    assert result["collectors"][0]["started_at"]
    assert request(dashboard, "/api/usage?publication=pub-B").json()["totals"] == {}
    assert "Daily activity" in request(dashboard, "/analytics").text


def test_search_appearances_alias_grouping_retention_and_contention(tmp_path):
    now = [2000000000.0]
    r = UsageRecorder(tmp_path / "usage.sqlite", clock=lambda: now[0], retention=90)
    response = {
        "publication_id": "p1",
        "results": [
            {"citation": {"source_id": "pdf:aaa", "book_id": alias}}
            for alias in ["one", "two"]
        ],
    }
    r.record("search", {}, response)
    data = aggregate([r.path], now=now[0])
    assert data["editions"]["pdf:aaa"]["search:success"] == 1
    now[0] += 100
    r.lock.acquire()
    try:
        r.record("get_book", {}, {})
    finally:
        r.lock.release()
    assert r.lost == 1
    r.record("get_book", {}, {})
    data = aggregate([r.path], now=now[0])
    assert "search:success" not in data["totals"]
    assert data["collectors"][0]["known_lost"] == 1
    assert aggregate([tmp_path / "missing.sqlite"])["status"] == "partial"
    assert not (tmp_path / "missing.sqlite").exists()


def test_tool_boundary_records_real_mcp_calls_without_content(tmp_path, keys, mint):
    """Authenticated SDK calls exercise the producer and dashboard consumer together."""
    import socket
    import threading

    import httpx2
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from cookbook.server import JWTVerifier
    from cookbook.server import create_app as mcp_app

    class SyntheticLibrary:
        def read_section(self, **kwargs):
            if kwargs["section_id"] == "missing":
                raise ValueError("PRIVATE EXCEPTION")
            return {
                "citation": {
                    "publication_id": "pub-A",
                    "source_id": "pdf:" + "a" * 64,
                    "book_id": "alias-A",
                },
                "text": "PRIVATE CONTENT",
                "next_offset": None,
            }

        def search(self, **kwargs):
            return {
                "publication_id": "pub-A",
                "results": [
                    {"citation": {"source_id": "pdf:" + "a" * 64}},
                    {"citation": {"source_id": "pdf:" + "b" * 64}},
                ],
            }

    recorder = UsageRecorder(tmp_path / "usage.sqlite")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/mcp"
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience=url,
        subjects=["user-1"],
        public_key=keys[1],
    )
    server = uvicorn.Server(
        uvicorn.Config(
            mcp_app(SyntheticLibrary(), verifier, usage=recorder),
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="critical",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.01)
        assert server.started

        async def calls():
            async with (
                httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + mint(aud=url)}
                ) as http,
                streamable_http_client(url, http_client=http) as transport,
                ClientSession(*transport) as session,
            ):
                await session.initialize()
                args = {
                    "publication_id": "pub-A",
                    "book_id": "alias-A",
                    "source_id": "pdf:" + "a" * 64,
                    "section_id": "s1",
                }
                assert not (await session.call_tool("read_section", args)).is_error
                assert (
                    await session.call_tool(
                        "read_section", {**args, "section_id": "missing"}
                    )
                ).is_error
                await session.call_tool("search_library", {"query": "PRIVATE QUERY"})
                await session.call_tool(
                    "search_library", {"query": "", "mode": "catalog"}
                )

        asyncio.run(calls())
        d = Dashboard(demo_config(tmp_path / "dashboard"))
        d.config["usage"] = [str(recorder.path)]
        data = request(d, "/api/usage").json()
        assert data["totals"]["read_section:success"] == 1
        assert data["totals"]["read_section:error"] == 1
        assert data["totals"]["search:success"] == 1
        assert data["totals"]["search_appearances"] == 2
        assert sum(data["daily"].values()) == 3
        assert b"PRIVATE" not in recorder.path.read_bytes()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_queue_conflicts_and_calibre_discovery_do_not_transfer_source_identity(
    dashboard, tmp_path
):
    from pathlib import Path

    source = Path(dashboard.sources[1]["path"])
    data = json.loads(source.read_text())
    data["queue"].append({**data["queue"][0], "outcome": "rejected"})
    source.write_text(json.dumps(data))
    dashboard.refresh(wait=True)
    b = next(
        b for b in dashboard.snapshot()["books"] if b["id"] == "sha256:" + "a" * 64
    )
    assert b["queue"][0]["conflict"]
    db_path = tmp_path / "calibre.sqlite"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            "CREATE TABLE library_id(uuid); INSERT INTO library_id VALUES ('library-A'); CREATE TABLE books(id,uuid,title); INSERT INTO books VALUES (17,'book-uuid','Synthetic discovery');"
        )
    dashboard.sources.append({"id": "catalog", "kind": "calibre", "path": str(db_path)})
    dashboard.refresh(wait=True)
    found = next(
        b for b in dashboard.snapshot()["books"] if b["title"] == "Synthetic discovery"
    )
    assert found["membership"] == "undecided" and found["provisional"]


def test_telemetry_failure_never_changes_tool_outcome(tmp_path):
    # A held SQLite writer is bounded by the producer's 10 ms lock timeout.
    r = UsageRecorder(tmp_path / "usage.sqlite")
    with sqlite3.connect(r.path) as db:
        db.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        r.record("read_section", {"section_id": "s1"}, {"text": "synthetic"})
        assert time.monotonic() - started < 0.5
        assert r.lost == 1


def test_remote_reader_allows_only_metadata_and_pins_pagination(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import mcp
    import mcp.client.streamable_http

    from cookbook.dashboard.remote import _collect

    calls = []
    mixed = [False]

    @asynccontextmanager
    async def transport(*args, **kwargs):
        yield (None, None)

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def initialize(self):
            pass

        async def call_tool(self, name, args):
            calls.append((name, args))
            if name == "get_publication_info":
                data = {"publication_id": "pub-A"}
            else:
                data = {
                    "publication_id": "pub-B" if mixed[0] else "pub-A",
                    "results": [],
                    "next_offset": 20 if args["offset"] == 0 else None,
                }
            return SimpleNamespace(is_error=False, structured_content=data)

    monkeypatch.setattr(mcp, "ClientSession", Session)
    monkeypatch.setattr(mcp.client.streamable_http, "streamable_http_client", transport)
    result = asyncio.run(
        _collect("https://library.example/mcp", lambda: "synthetic-token")
    )
    assert result["publication"] == "pub-A"
    assert [name for name, _ in calls] == [
        "get_publication_info",
        "search_library",
        "search_library",
    ]
    assert all(
        args["publication_id"] == "pub-A" and args["mode"] == "catalog"
        for name, args in calls
        if name == "search_library"
    )
    mixed[0] = True
    with pytest.raises(ValueError):
        asyncio.run(_collect("https://library.example/mcp", lambda: "synthetic-token"))


def test_published_dashboard_reader_links_identifiers_only(tmp_path):
    import re
    from html import unescape
    from urllib.parse import parse_qs, urlsplit

    from conftest import fixture_build

    from cookbook.reader_content import decode_location

    manifest, inputs = fixture_build(tmp_path / "published")
    config = demo_config(tmp_path / "dashboard")
    config["reader_origin"] = "https://reader.example"
    config["sources"].append(
        {
            "id": "published",
            "kind": "index",
            "path": str(inputs["runtime/index.sqlite"]),
        }
    )
    dashboard = Dashboard(config)
    dashboard.refresh(wait=True)
    page = request(dashboard, "/?membership=all")
    links = re.findall(r'href="([^"]+)">Open in library reader', page.text)
    assert links
    for link in links:
        url = urlsplit(unescape(link))
        assert (
            url.scheme == "https"
            and url.netloc == "reader.example"
            and url.path == "/reader/read"
        )
        location = decode_location(parse_qs(url.query)["at"][0])
        assert set(location) == {"publication_id", "book_id", "source_id"}
        assert location["publication_id"] == manifest.publication_id
    assert "Open in library reader" not in request(dashboard, "/?q=Pending").text
    assert request(dashboard, base="http://evil.example").status_code == 403
