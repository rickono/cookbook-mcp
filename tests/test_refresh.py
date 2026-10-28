"""The refresh command: reports -> blind triage -> ledger -> rebuild -> publish, synthetically.

The whole loop runs through the MCP app's test client on the synthetic scanned book. The
sandbox admission check, the guarded crop and the reader are injected fakes: no PDF is
parsed or rendered, and no OCR or model runs.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from synthetic_scanned import pdf_sha256, registry, snapshot

import cookbook.build as build_module
import cookbook.library as library_module
from cookbook.build import build_snapshot
from cookbook.library import Library
from cookbook.publication import Runtime, publish_build
from cookbook.reports import ReportSink
from cookbook.storage import IntegrityError, LocalStore

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location(
    "refresh_library", SCRIPTS / "refresh_library.py"
)
refresh_library = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refresh_library)

SALT = ("Salt | 2 tsp", "Salt | 2 tbsp")


@pytest.fixture(autouse=True)
def no_ocr_or_rendering(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the refresh must not OCR a scanned book")

    def fake_render(path, fmt, page, destination, edge=1600):
        Image.new("RGB", (round(edge * 0.75), edge), "white").save(destination, "PNG")

    monkeypatch.setattr(build_module, "paged", refuse)
    monkeypatch.setattr(library_module, "render_page", fake_render)


class Fakes:
    """Injected admission check, guarded crop and blind reader, with a call log."""

    def __init__(self, readings=None, errors=("timeout 300s",)):
        # readings(report_id_prefix) -> the three blind readings of that report's crop
        self.readings = readings or (lambda prefix: [SALT[1]] * 3)
        self.errors = list(errors)
        self.admitted = 0
        self.crops = []
        self.current = None

    def admission(self):
        self.admitted += 1

    def books(self):
        return {pdf_sha256(): 18}

    def crop(self, out, book, page, sha, box, n):
        self.crops.append((book, page, sha, box))
        self.current = list(self.readings(n))
        return {"image": "/synthetic/crop.png", "sha256": "c" * 64, "long_edge": 4000}

    def call(self, out, reader, prompt, image):
        if not self.current:
            raise AssertionError("reader called outside a report")
        text = self.current.pop(0)
        return text, {"model": reader, "errors": [] if text else self.errors}


class Loop:
    """A published synthetic scanned book, its MCP app with a reports store, and the refresh."""

    def __init__(self, tmp_path, client, headers, store, runtime, reports):
        self.tmp, self.client, self.headers = tmp_path, client, headers
        self.store, self.runtime, self.reports = store, runtime, reports
        self.out = tmp_path / "triage"

    def tool(self, name, arguments):
        r = self.client.post(
            "/mcp",
            headers={**self.headers, "Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        ).json()["result"]
        assert not r.get("isError"), r
        return r["structuredContent"]

    def hit(self, query, publication_id=None):
        args = {"query": query}
        if publication_id:
            args["publication_id"] = publication_id
        return self.tool("search_library", args)["results"]

    def ids(self):
        citation = self.hit("plain soup")[0]["citation"]
        return {k: citation[k] for k in ("publication_id", "book_id", "source_id")}

    def report(self, quoted, proposed, *, page=1, region=(0.1, 0.4, 0.9, 0.7)):
        return self.tool(
            "report_transcription_issue",
            {
                **self.ids(),
                "physical_page": page,
                "quoted_text": quoted,
                "proposed_text": proposed,
                "kind": "quantity",
                "region": list(region),
            },
        )["report_id"]

    def active(self):
        return json.loads(self.store.read("control/active.json"))

    def publications(self):
        return sorted(self.store.list("publications"))

    def refresh(self, fakes, **kwargs):
        return refresh_library.refresh(
            self.reports,
            self.out,
            store=self.store,
            activate=self.runtime.activate,
            work=self.tmp / "work",
            admission=fakes.admission,
            books=fakes.books,
            crop=fakes.crop,
            call=fakes.call,
            log=lambda line: None,
            **kwargs,
        )


@pytest.fixture
def loop(tmp_path, keys, mint):
    from starlette.testclient import TestClient

    from cookbook.server import JWTVerifier, create_app

    build_snapshot(
        snapshot(tmp_path),
        [1],
        tmp_path / "build",
        tmp_path / "cache",
        progress=lambda event: None,
        scanned=registry(tmp_path),
    )
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    publish_build(store, tmp_path / "build", activate=runtime.activate)
    reports = LocalStore(tmp_path / "reports")
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://service.example",
        subjects=["user-1"],
        public_key=keys[1],
    )
    app = create_app(Library(runtime), verifier, ReportSink(reports))
    headers = {"Authorization": "Bearer " + mint(aud="https://service.example")}
    with TestClient(app, base_url="https://service.example") as client:
        yield Loop(tmp_path, client, headers, store, runtime, reports)


def test_a_report_is_triaged_and_republished_as_a_traceable_correction(loop):
    earlier = loop.active()
    earlier_manifest = loop.store.read(
        f"publications/{earlier['publication_id']}/manifest.json"
    )
    rid = loop.report(*SALT)
    fakes = Fakes()

    result = loop.refresh(fakes)

    assert fakes.admitted == 1 and len(fakes.crops) == 1
    assert result["status"] == "published"
    assert result["corrections"] == {"applied": 1, "stale": 0, "ambiguous": 0}
    active = loop.active()
    assert active["publication_id"] == result["publication_id"]
    assert active["publication_id"] != earlier["publication_id"]
    reviewer = {"kind": "agent", "id": "blind-reread:claude:claude-haiku-5-5 x3"}
    applied = [{"id": rid, "reviewer": reviewer}]

    [hit] = loop.hit("tbsp")
    citation = hit["citation"]
    assert citation["publication_id"] == active["publication_id"]
    assert citation["section_title"] == "LENTIL SOUP"
    assert citation["extraction"]["corrections"] == applied
    ids = {k: citation[k] for k in ("publication_id", "book_id", "source_id")}
    section = loop.tool("read_section", {**ids, "section_id": citation["section_id"]})
    assert "Salt | 2 tbsp" in section["text"] and "2 tsp" not in section["text"]
    assert section["citation"]["extraction"]["corrections"] == applied
    page = loop.tool("get_page", {**ids, "physical_page": 1})
    assert "Salt | 2 tbsp" in page["text"]
    assert page["citation"]["extraction"]["corrections"] == applied
    info = loop.tool("get_publication_info", {})
    assert info["counts"]["applied_corrections"] == 1

    # The earlier publication is unchanged, still served by id, and kept for rollback.
    assert (
        loop.store.read(f"publications/{earlier['publication_id']}/manifest.json")
        == earlier_manifest
    )
    old = loop.hit("Salt", earlier["publication_id"])
    assert any("2 tsp" in h["snippet"] for h in old)
    history = json.loads(loop.store.read("control/successful.json"))
    assert [p["publication_id"] for p in history] == [
        active["publication_id"],
        earlier["publication_id"],
    ]
    build_report = json.loads(
        (Path(result["build"]) / "build-report.json").read_bytes()
    )
    assert build_report["corrections"]["applied"] == 1


def test_a_refresh_with_no_new_reports_publishes_nothing(loop):
    loop.report(*SALT)
    loop.refresh(Fakes())
    active, publications = loop.active(), loop.publications()
    again = Fakes()

    result = loop.refresh(again)

    assert result["status"] == "unchanged"
    assert again.admitted == 0 and again.crops == []
    assert loop.active() == active and loop.publications() == publications


def test_a_failing_admission_check_stops_the_run_before_triage(loop):
    loop.report(*SALT)
    active = loop.active()
    fakes = Fakes()

    def refuse():
        raise SystemExit("scripts/ocr_sandbox.py doctor refused")

    fakes.admission = refuse

    with pytest.raises(SystemExit, match="doctor refused"):
        loop.refresh(fakes)

    assert fakes.crops == []
    assert list((loop.out / "decisions").glob("*.json")) == []
    assert loop.active() == active


def test_reports_over_the_triage_limit_stay_pending(loop):
    for proposed in ("Salt | 2 tbsp", "Salt | 3 tsp", "Salt | 4 tsp"):
        loop.report("Salt | 2 tsp", proposed)
    fakes = Fakes(readings=lambda prefix: ["Salt | 2 tsp"] * 3)

    first = loop.refresh(fakes, limit=2)

    assert len(fakes.crops) == 2
    assert first["triage"]["pending"] == 1
    assert first["triage"]["decided"]["rejected"] == 2
    assert first["status"] == "unchanged"

    second = loop.refresh(fakes, limit=2)

    assert len(fakes.crops) == 3 and second["triage"]["pending"] == 0


@pytest.mark.parametrize(
    ("errors", "stops"),
    [(("timeout 300s",), False), (("Claude AI usage limit reached",), True)],
)
def test_a_failed_reading_leaves_the_report_pending(loop, errors, stops):
    first = loop.report(*SALT)
    loop.report("Salt | 2 tsp", "Salt | 3 tsp")
    fakes = Fakes(readings=lambda prefix: [None] * 3, errors=errors)
    active = loop.active()

    result = loop.refresh(fakes)

    # A usage limit ends the run at the first report; a timeout moves on to the next.
    assert len(fakes.crops) == (1 if stops else 2)
    assert result["triage"]["pending"] == 2
    assert list((loop.out / "decisions").glob("*.json")) == []
    assert result["status"] == "unchanged" and loop.active() == active

    fakes.readings = lambda prefix: (
        [SALT[1]] * 3 if first.startswith(prefix) else ["Salt | 2 tsp"] * 3
    )
    retried = loop.refresh(fakes)
    assert retried["status"] == "published" and retried["triage"]["pending"] == 0


def test_the_owner_queue_lists_filter_refusals_and_ambiguous_corrections(loop):
    refused = loop.report(*SALT)
    ambiguous = loop.report("lentils", "beans", page=2)
    fakes = Fakes(
        readings=lambda prefix: (
            [None] * 3 if refused.startswith(prefix) else ["beans"] * 3
        ),
        errors=("API Error: Output blocked by content filtering policy",),
    )

    result = loop.refresh(fakes)

    # The refusal is a result, not retried; the accepted correction can't be placed.
    assert result["triage"]["pending"] == 0
    assert result["status"] == "published"
    assert result["corrections"] == {"applied": 0, "stale": 0, "ambiguous": 1}
    assert result["owner_queue"]["new"] == 2
    page = Path(result["owner_queue"]["file"]).read_text()
    first, second = page.split("\n## ")[1:]
    assert refused in first and '"Salt | 2 tsp"' in first and '"Salt | 2 tbsp"' in first
    assert first.count("refused by the provider's content filter") == 1
    assert "refused a reading; not retried or worked around" in first
    assert ambiguous in second and '"lentils"' in second and '"beans"' in second
    assert "physical page 2" in second and second.count('`: "beans"') == 3
    assert f"ambiguous correction {ambiguous}" in second

    again = loop.refresh(Fakes())
    assert again["status"] == "unchanged"
    assert again["owner_queue"]["new"] == 0 and again["owner_queue"]["total"] == 2


def test_a_refusal_with_limit_metadata_is_recorded_and_never_retried(loop):
    loop.report(*SALT)
    fakes = Fakes(
        readings=lambda prefix: [None] * 3,
        errors=("Output blocked by content filtering policy; session limit reached",),
    )
    active = loop.active()

    result = loop.refresh(fakes)

    assert result["triage"]["pending"] == 0
    assert result["triage"]["decided"]["owner_queue"] == 1
    assert result["status"] == "unchanged" and loop.active() == active
    assert not (loop.out / "ledger.jsonl").read_bytes()
    again = Fakes()
    assert loop.refresh(again)["triage"]["pending"] == 0
    assert again.admitted == 0 and not again.crops


def test_a_failed_build_leaves_the_active_publication_unchanged(loop):
    loop.report(*SALT)
    active, publications = loop.active(), loop.publications()
    [pdf] = (loop.tmp / "snapshot").rglob("scan.pdf")
    pdf.write_bytes(pdf.read_bytes() + b"\n% changed after the snapshot was proved")

    with pytest.raises(IntegrityError, match="snapshot changed"):
        loop.refresh(Fakes())

    assert loop.active() == active and loop.publications() == publications
    assert loop.runtime.active() == active


def test_a_publication_without_recorded_build_inputs_is_not_rebuilt(
    loop, tmp_path, monkeypatch
):
    # A publication built before build inputs were recorded under their logical path.
    monkeypatch.setattr(build_module, "BUILD_INPUTS", "quality/unrecorded.json")
    build_snapshot(
        tmp_path / "snapshot" / "library",
        [1],
        tmp_path / "old-build",
        tmp_path / "cache",
        progress=lambda event: None,
        scanned=registry(tmp_path),
    )
    publish_build(loop.store, tmp_path / "old-build", activate=loop.runtime.activate)
    loop.report(*SALT)
    active, publications = loop.active(), loop.publications()

    with pytest.raises(refresh_library.RefreshError, match="cookbook build"):
        loop.refresh(Fakes())

    assert loop.active() == active and loop.publications() == publications
