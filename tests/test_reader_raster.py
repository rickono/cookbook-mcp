"""Reuse and current access through synthetic serving fixtures, without OCR."""

import hashlib
import json
from io import BytesIO

import pytest
from PIL import Image
from starlette.testclient import TestClient
from test_reader_http import login
from test_reader_original import scanned_original

from cookbook.library import Library
from cookbook.reader_content import decode_location
from cookbook.rendering import RenderError
from cookbook.storage import IntegrityError, canonical
from cookbook.withdrawal import record_withdrawal

pytest_plugins = ["test_reader_http"]


@pytest.fixture
def raster_env(reader_env, published, tmp_path, monkeypatch):
    at = scanned_original(published, tmp_path)
    library = published[4]
    monkeypatch.setattr("cookbook.hosted.Library", lambda *a, **k: library)
    renders = []

    def render(path, fmt, page, destination, edge=1600):
        renders.append((page, edge))
        Image.new("RGB", (edge, edge // 2), "orange" if page == 2 else "blue").save(
            destination, "PNG"
        )

    monkeypatch.setattr("cookbook.library.render_page", render)
    app, _, clock = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        yield client, library, at, renders, clock


def pixels(response):
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(response.content)) as im:
        im.load()
        return im.size


def test_repeat_view_skips_original_hash_render_and_encode(
    raster_env, monkeypatch, capsys
):
    client, library, at, renders, _ = raster_env
    for _ in range(5):
        assert pixels(client.get("/reader/image", params={"at": at, "page": 2})) == (
            1600,
            800,
        )
        # Any later source-cache access would rehash the original.
        monkeypatch.setattr(
            library, "cached", lambda *a: pytest.fail("rehashing original")
        )
    assert renders == [(2, 1600)]
    traces = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    traces = [t for t in traces if t.get("route") == "/reader/image"]
    assert traces[0]["stages"]["original_encode"]["n"] == 1
    assert all(t["stages"]["raster_hit"]["n"] == 1 for t in traces[1:])
    assert all("original_render" not in t["stages"] for t in traces[1:])
    assert all("original_encode" not in t["stages"] for t in traces[1:])
    assert all(t["stages"]["original_validate"]["n"] == 1 for t in traces)


def test_hit_rechecks_withdrawal_expiry_and_retirement(raster_env, published):
    client, library, at, renders, clock = raster_env
    loc = decode_location(at)
    params = {"at": at, "page": 2}
    pixels(client.get("/reader/image", params=params))
    event = {
        "action": "revoke",
        "actor": {"kind": "human"},
        "affected_decisions": [],
        "affected_pages": [
            {"source_sha256": loc["source_id"].split(":")[1], "physical_page": 2}
        ],
    }
    event["id"] = hashlib.sha256(canonical(event)).hexdigest()
    record_withdrawal(published[2], event)
    # Current policy withholds transcription but keeps original access.
    assert (
        client.get("/reader/content", params={"at": at}).json()["state"] == "withheld"
    )
    pixels(client.get("/reader/image", params=params))
    meta, _ = library.get_page(
        *(loc[k] for k in ("publication_id", "book_id", "source_id")), 2
    )
    assert meta["text"] == "" and not meta["text_truncated"]
    assert len(renders) == 1
    manifest = (
        library.runtime.root / "versions" / loc["publication_id"] / "manifest.json"
    )
    retained = manifest.read_bytes()
    manifest.unlink()
    assert client.get("/reader/image", params=params).status_code == 410
    manifest.write_bytes(retained)
    clock[0] += 31 * 86400
    assert client.get("/reader/image", params=params).status_code == 401
    assert len(renders) == 1


def test_hit_keeps_busy_refusal_and_health_text_responsive(raster_env):
    client, library, at, renders, _ = raster_env
    params = {"at": at, "page": 2}
    pixels(client.get("/reader/image", params=params))
    assert library.render_lock.acquire(blocking=False)
    try:
        assert client.get("/reader/image", params=params).status_code == 503
        assert client.get("/healthz").status_code == 200
        assert client.get("/reader/content", params={"at": at}).status_code == 200
    finally:
        library.render_lock.release()
    pixels(client.get("/reader/image", params=params))
    assert len(renders) == 1


def test_source_page_region_and_encoding_settings_separate_results(
    raster_env, monkeypatch
):
    _, library, at, renders, _ = raster_env
    loc = decode_location(at)
    args = [loc[k] for k in ("publication_id", "book_id", "source_id")]
    _, full = library.get_page(*args, 2)
    _, other = library.get_page(*args, 1)
    assert full != other
    _, crop = library.get_page(*args, 2, region=[0.1, 0.2, 0.4, 0.5])
    assert Image.open(BytesIO(crop)).size == (720, 360)
    library.get_page(*args, 2, edge=800)
    monkeypatch.setattr("cookbook.library.JPEG_QUALITY", 80)
    library.get_page(*args, 2)
    assert len(renders) == 5
    # A changed current manifest cannot reach the old raster, even if source DB
    # identity is unchanged. The replacement bytes must pass verification first.
    path = library.runtime.root / "versions" / loc["publication_id"] / "manifest.json"
    manifest = json.loads(path.read_text())
    for entry in manifest["files"]:
        if entry["role"] == "backup" and entry["path"].startswith("backup/"):
            entry["sha256"] = "f" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises((IntegrityError, FileNotFoundError)):
        library.get_page(*args, 2)
    assert len(renders) == 5


def test_lru_byte_and_entry_limits_and_disabled_cache(raster_env, monkeypatch):
    _, original, at, renders, _ = raster_env
    loc = decode_location(at)
    args = [loc[k] for k in ("publication_id", "book_id", "source_id")]
    _, image = original.get_page(*args, 2)
    library = Library(original.runtime, raster_cache_bytes=len(image))
    library.get_page(*args, 2)
    library.get_page(*args, 1)
    library.get_page(*args, 2)
    assert len(renders) == 4  # byte eviction forces another render
    assert library._raster_size <= library.raster_cache_bytes
    assert sum(map(len, library._rasters.values())) == library._raster_size
    monkeypatch.setattr("cookbook.library.RASTER_ENTRIES", 2)
    library = Library(original.runtime)
    for edge in (800, 900, 1000):
        library.get_page(*args, 2, edge=edge)
    assert len(library._rasters) == 2
    library.get_page(*args, 2, edge=800)
    assert len(renders) == 8
    disabled = Library(original.runtime, raster_cache_bytes=0)
    for _ in range(2):
        disabled.get_page(*args, 2)
    assert len(renders) == 10 and not disabled._rasters


def test_failures_and_invalid_output_never_enter_cache(raster_env, monkeypatch):
    client, library, at, renders, _ = raster_env
    renderer = __import__("cookbook.library", fromlist=["render_page"]).render_page

    def refuse(*a, **k):
        raise RenderError("synthetic refusal")

    monkeypatch.setattr("cookbook.library.render_page", refuse)
    for _ in range(2):
        assert (
            client.get("/reader/image", params={"at": at, "page": 2}).status_code == 503
        )
    assert not library._rasters
    monkeypatch.setattr("cookbook.library.render_page", renderer)

    def invalid(*a, **k):
        raise RenderError("invalid raster")

    monkeypatch.setattr("cookbook.library.raster", invalid)
    assert client.get("/reader/image", params={"at": at, "page": 2}).status_code == 503
    assert not library._rasters and len(renders) == 1


def test_cached_pixels_still_require_session_and_raster_admission(
    raster_env, monkeypatch
):
    client, _, at, renders, _ = raster_env
    params = {"at": at, "page": 2}
    pixels(client.get("/reader/image", params=params))
    from cookbook import reader_original

    admission = reader_original.raster

    def refuse(data):
        raise RenderError("synthetic delivery refusal")

    monkeypatch.setattr(reader_original, "raster", refuse)
    assert client.get("/reader/image", params=params).status_code == 503
    monkeypatch.setattr(reader_original, "raster", admission)
    csrf = client.get("/reader/session").json()["csrf"]
    response = client.post(
        "/reader/logout",
        data={"csrf": csrf, "scope": "all"},
        headers={"Origin": "https://reader.example"},
    )
    assert response.status_code == 200
    assert client.get("/reader/image", params=params).status_code == 401
    assert len(renders) == 1
