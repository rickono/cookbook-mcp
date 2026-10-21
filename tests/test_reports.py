"""Page zoom and agent transcription reports, on a synthetic scanned book.

Rendering is replaced by a synthetic image: no PDF parser, OCR or model runs here.
"""

import io
import json
import uuid

import pytest
from PIL import Image
from starlette.testclient import TestClient

import cookbook.library as library_module
from cookbook.build import add_content, create_index
from cookbook.hosted import reports_store_from_environment
from cookbook.library import Library
from cookbook.publication import Entry, Manifest, Runtime, publish
from cookbook.quality import QUALITY_PATH, make_report
from cookbook.reports import ReportSink, list_reports
from cookbook.server import JWTVerifier, create_app
from cookbook.storage import (
    IntegrityError,
    LocalStore,
    S3Store,
    atomic_write,
    canonical,
    digest_file,
)

PAGE_1 = "Lentil soup\n1½ cups lentils\n2 tsp  salt\n4 cups water"
PAGE_2 = "Simmer the lentils for 30 minutes."


@pytest.fixture
def scanned(tmp_path, monkeypatch):
    root = tmp_path / "build"
    root.mkdir()
    pub = uuid.uuid4().hex
    db = create_index(root / "index.sqlite", pub)
    original = root / "book.pdf"
    original.write_bytes(b"%PDF-synthetic placeholder, never parsed")
    sha, _ = digest_file(original)
    source = "pdf:" + sha
    pages = [
        {
            "id": f"page-{n}",
            "title": f"Page {n}",
            "text": text,
            "locator": {"kind": "page", "physical_page": n},
            "provenance": "transcription",
            "kind": "page",
            "images": [],
        }
        for n, text in ((1, PAGE_1), (2, PAGE_2))
    ]
    recipe = {
        "id": "lentil-soup",
        "title": "Lentil soup",
        "text": PAGE_1 + "\n" + PAGE_2,
        "locator": {"kind": "page", "physical_page": 1},
        "provenance": "transcription",
        "kind": "recipe",
        "images": [],
    }
    add_content(db, source, "PDF", sha, "backup/book.pdf", [*pages, recipe], [], [])
    db.execute(
        "insert into books values(?,?,?,?,?,?)",
        ("book-1", 1, "Synthetic Lentils", '["Test Author"]', "[]", source),
    )
    db.commit()
    db.close()
    inputs = {
        "runtime/index.sqlite": root / "index.sqlite",
        "backup/book.pdf": original,
    }
    atomic_write(root / "ocr-review.json", canonical(make_report(pub, [])))
    inputs[QUALITY_PATH] = root / "ocr-review.json"
    entries = [
        Entry(
            path=k,
            sha256=digest_file(p)[0],
            size=digest_file(p)[1],
            role="runtime" if k.startswith("runtime") else "backup",
        )
        for k, p in inputs.items()
    ]
    m = Manifest(publication_id=pub, created_at="2026-10-20T00:00:00Z", files=entries)
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    publish(store, m, inputs, expected_version=None, activate=runtime.activate)

    renders = []

    def fake_render(path, fmt, page, destination, edge=1600):
        # Left half red, right half blue, so a crop's position is visible in its pixels.
        renders.append(edge)
        im = Image.new("RGB", (round(edge * 0.75), edge), "red")
        im.paste("blue", (im.width // 2, 0, im.width, im.height))
        im.save(destination, "PNG")

    monkeypatch.setattr(library_module, "render_page", fake_render)
    ids = {"publication_id": pub, "book_id": "book-1", "source_id": source}
    return Library(runtime), ids, sha, renders


def pixels(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.size, im.convert("RGB").getpixel((im.width // 2, im.height // 2))


def test_region_zoom_renders_larger_and_returns_only_the_box(scanned):
    lib, ids, _, renders = scanned
    meta, data = lib.get_page(**ids, physical_page=1, edge=800)
    assert renders == [800] and "region" not in meta
    meta, data = lib.get_page(**ids, physical_page=1, edge=800, region=[0.5, 0, 1, 0.5])
    # A half-height box needs twice the pixels to come back at the requested edge.
    assert renders[-1] == 1600 and meta["render_edge"] == 1600
    assert meta["region"] == [0.5, 0, 1, 0.5] and meta["text"] == PAGE_1
    size, centre = pixels(data)
    assert max(size) <= 800 and centre[2] > 200 and centre[0] < 60  # blue half only
    lib.get_page(**ids, physical_page=1, edge=1600, region=[0.4, 0.4, 0.45, 0.45])
    assert renders[-1] == library_module.ZOOM_EDGE  # tiny boxes are capped


@pytest.mark.parametrize(
    "region",
    [[0.5, 0, 0.4, 1], [0, 0, 0.01, 1], [0, 0, 1, 1.2], [0, 0, 1], ["0", 0, 1, 1]],
)
def test_bad_regions_are_refused(scanned, region):
    lib, ids, _, _ = scanned
    with pytest.raises(IntegrityError):
        lib.get_page(**ids, physical_page=1, region=region)


def report(ids, **changes):
    args = {
        **ids,
        "physical_page": 1,
        "quoted_text": "2 tsp salt",
        "proposed_text": "2 tbsp salt",
        "kind": "quantity",
        "region": [0, 0.3, 1, 0.6],
    }
    args.update(changes)
    return args


def test_report_is_anchored_content_addressed_and_never_overwritten(scanned, tmp_path):
    lib, ids, sha, _ = scanned
    reports = LocalStore(tmp_path / "reports")
    sink = ReportSink(reports)
    first = sink.submit(lib, **report(ids, note="looks like tbsp on the page"))
    assert first["status"] == "recorded" and first["verification"] == "pending"
    # Same claim, other whitespace and note: one report, not two.
    again = sink.submit(lib, **report(ids, quoted_text=" 2 tsp\nsalt ", note="again"))
    assert again == {**first, "status": "already_recorded"}
    [stored] = list_reports(reports)
    assert stored["report_id"] == first["report_id"]
    assert stored["source_sha256"] == sha and stored["format"] == "PDF"
    assert stored["note"] == "looks like tbsp on the page"
    assert reports.list(f"reports/{ids['publication_id']}") == [
        f"reports/{ids['publication_id']}/{first['report_id']}.json"
    ]
    # A quote may come from the cited section rather than the page.
    by_section = sink.submit(
        lib,
        **report(
            ids,
            physical_page=2,
            section_id="lentil-soup",
            quoted_text="4 cups water",
            proposed_text="4 cups stock",
        ),
    )
    assert by_section["status"] == "recorded"
    # The library is untouched.
    assert lib.get_page(**ids, physical_page=1)[0]["text"] == PAGE_1


@pytest.mark.parametrize(
    "changes",
    [
        {"quoted_text": "3 tsp salt"},  # not what the library serves
        {"proposed_text": "2 tsp salt"},  # no change claimed
        {"kind": "rewrite"},
        {"proposed_text": "x" * 501},
        {"note": "x" * 1001},
        {"physical_page": 9},
        {"section_id": "missing"},
        {"region": [0, 0, 2, 1]},
        {"source_id": "pdf:" + "0" * 64},
    ],
)
def test_invalid_reports_are_refused_without_writing(scanned, tmp_path, changes):
    lib, ids, _, _ = scanned
    reports = LocalStore(tmp_path / "reports")
    with pytest.raises(IntegrityError):
        ReportSink(reports).submit(lib, **report(ids, **changes))
    assert reports.list("reports") == []


def test_report_rate_limit(scanned, tmp_path):
    lib, ids, _, _ = scanned
    sink = ReportSink(LocalStore(tmp_path / "reports"), max_per_hour=1)
    sink.submit(lib, **report(ids))
    with pytest.raises(IntegrityError):
        sink.submit(lib, **report(ids, proposed_text="1 tsp salt"))


def rpc(client, headers, name, arguments):
    return client.post(
        "/mcp",
        headers={**headers, "Accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    ).json()["result"]


@pytest.mark.parametrize("configured", [True, False])
def test_report_tool_over_mcp(scanned, tmp_path, keys, mint, configured):
    lib, ids, _, _ = scanned
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://service.example",
        subjects=["user-1"],
        public_key=keys[1],
    )
    reports = LocalStore(tmp_path / "reports")
    app = create_app(lib, verifier, ReportSink(reports) if configured else None)
    headers = {"Authorization": "Bearer " + mint(aud="https://service.example")}
    with TestClient(app, base_url="https://service.example") as client:
        listed = client.post(
            "/mcp",
            headers={**headers, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 0, "method": "tools/list", "params": {}},
        ).json()["result"]["tools"]
        tool = next(t for t in listed if t["name"] == "report_transcription_issue")
        assert tool["annotations"]["readOnlyHint"] is False
        assert tool["annotations"]["destructiveHint"] is False
        page = next(t for t in listed if t["name"] == "get_page")
        assert "region" in page["inputSchema"]["properties"]
        zoom = rpc(
            client,
            headers,
            "get_page",
            {**ids, "physical_page": 1, "region": [0.5, 0, 1, 0.5]},
        )
        assert not zoom["isError"] and zoom["structuredContent"]["region"] == [
            0.5,
            0,
            1,
            0.5,
        ]
        r = rpc(client, headers, "report_transcription_issue", report(ids))
        if configured:
            assert not r["isError"] and r["structuredContent"]["status"] == "recorded"
            assert len(list_reports(reports)) == 1
        else:
            assert r["isError"]
            assert r["structuredContent"]["error"]["code"] == "reporting_unavailable"
        bad = rpc(
            client,
            headers,
            "report_transcription_issue",
            report(ids, quoted_text="nope"),
        )
        assert bad["isError"] and "nope" not in json.dumps(bad)


ENV = {
    "S3_ENDPOINT_URL": "https://account.r2.example",
    "S3_BUCKET": "library",
    "AWS_ACCESS_KEY_ID": "library-key",
    "AWS_SECRET_ACCESS_KEY": "library-secret",
}
REPORT_ENV = {
    "REPORTS_S3_BUCKET": "reports",
    "REPORTS_AWS_ACCESS_KEY_ID": "reports-key",
    "REPORTS_AWS_SECRET_ACCESS_KEY": "reports-secret",
}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, None),
        (REPORT_ENV, S3Store),
        ({"REPORTS_S3_BUCKET": "reports"}, ValueError),
        ({**REPORT_ENV, "REPORTS_S3_BUCKET": "library"}, ValueError),
        ({**REPORT_ENV, "REPORTS_AWS_ACCESS_KEY_ID": "library-key"}, ValueError),
        (
            {**REPORT_ENV, "REPORTS_S3_ENDPOINT_URL": "http://insecure.example"},
            ValueError,
        ),
    ],
)
def test_reports_store_is_separate_and_optional(monkeypatch, changes, expected):
    for name in [*ENV, *REPORT_ENV, "REPORTS_S3_ENDPOINT_URL"]:
        monkeypatch.delenv(name, raising=False)
    for name, value in {**ENV, **changes}.items():
        monkeypatch.setenv(name, value)
    if expected is ValueError:
        with pytest.raises(ValueError):
            reports_store_from_environment()
    elif expected is None:
        assert reports_store_from_environment() is None
    else:
        store = reports_store_from_environment()
        assert isinstance(store, expected) and store.bucket == "reports"
