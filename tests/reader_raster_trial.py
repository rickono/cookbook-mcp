"""Opt-in synthetic PDF profile. Run only through scripts/ocr_sandbox.py."""

import hashlib
import io
import json
import statistics
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from PIL import Image
from reportlab.pdfgen.canvas import Canvas
from starlette.testclient import TestClient
from test_reader_http import login
from test_reader_original import scanned_original

from cookbook.library import Library

pytest_plugins = ["test_reader_http"]
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux serving renderer"
)


def test_interleaved_original_requests(reader_env, published, tmp_path, monkeypatch):
    # Generated vector artwork and text, no book or scan. The production renderer
    # still parses PDF, creates PNG, and encodes JPEG inside the timed requests.
    pdf = io.BytesIO()
    canvas = Canvas(pdf, pagesize=(612, 792), invariant=True)
    for page in range(2):
        for n in range(4000):
            canvas.setFillColorRGB((n % 17) / 17, (n % 31) / 31, (n % 43) / 43)
            canvas.circle((n * 17) % 612, (n * 23) % 792, 4, fill=1, stroke=0)
        canvas.drawString(50, 740, f"Synthetic original {page + 1}")
        canvas.showPage()
    canvas.save()
    at = scanned_original(published, tmp_path, original_bytes=pdf.getvalue())
    libraries = [Library(published[3], raster_cache_bytes=0), Library(published[3])]
    selected = [0]
    monkeypatch.setattr(
        "cookbook.hosted.Library", lambda *a, **k: libraries[selected[0]]
    )
    app, _, _ = reader_env
    logs = io.StringIO()
    samples = {"no_reuse": [], "reuse": []}
    # Build applications sequentially so the injection selects the intended Library.
    selected[0] = 0
    app_a = app()
    selected[0] = 1
    app_b = app()
    with (
        redirect_stdout(logs),
        TestClient(app_a, base_url="https://reader.example") as a,
        TestClient(app_b, base_url="https://reader.example") as b,
    ):
        login(a)
        login(b)
        # Record cold raster/original state separately. Warm both cases before
        # alternating five successful requests per case, with output decode.
        cold = []
        for client in (a, b):
            start = time.perf_counter()
            response = client.get("/reader/image", params={"at": at, "page": 2})
            cold.append(
                {
                    "ms": (time.perf_counter() - start) * 1000,
                    "status": response.status_code,
                }
            )
            assert response.status_code == 200, (response.text, logs.getvalue())
        expected = hashlib.sha256(response.content).hexdigest()
        for _ in range(5):
            for name, client in (("no_reuse", a), ("reuse", b)):
                start = time.perf_counter()
                response = client.get("/reader/image", params={"at": at, "page": 2})
                received = time.perf_counter()
                assert response.status_code == 200, (response.text, logs.getvalue())
                assert response.headers["cache-control"] == "private, no-store"
                with Image.open(io.BytesIO(response.content)) as image:
                    image.load()
                    assert max(image.size) == 1600
                assert hashlib.sha256(response.content).hexdigest() == expected
                samples[name].append(
                    {
                        "body_ms": (received - start) * 1000,
                        "decode_ms": (time.perf_counter() - received) * 1000,
                        "bytes": len(response.content),
                        "status": response.status_code,
                    }
                )
    traces = [json.loads(line) for line in logs.getvalue().splitlines()]
    traces = [t for t in traces if t.get("route") == "/reader/image"]
    for n, trace in enumerate(traces[2:]):
        name = "no_reuse" if n % 2 == 0 else "reuse"
        samples[name][n // 2]["stages"] = trace["stages"]
    assert len(traces) == 12
    assert all("original_render" in s["stages"] for s in samples["no_reuse"])
    assert all("original_encode" not in s["stages"] for s in samples["reuse"])
    assert all(s["stages"]["raster_hit"]["n"] == 1 for s in samples["reuse"])
    result = {
        "cold": cold,
        "samples": samples,
        "errors": 0,
        "transport": "in-process ASGI; excludes network",
        "summary": {},
    }
    for name, rows in samples.items():
        values = [r["body_ms"] for r in rows]
        result["summary"][name] = {
            "n": len(values),
            "median_ms": statistics.median(values),
            "min_ms": min(values),
            "max_ms": max(values),
        }
    Path("/output/original-profile.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"]))
