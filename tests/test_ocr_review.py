import json
from pathlib import Path
import sqlite3
import pytest
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from cookbook import ocr
from cookbook.extract import ocr_page
from cookbook.build import build_snapshot
from cookbook.publication import publish
from cookbook.quality import read_report, finalize
from cookbook.storage import IntegrityError, atomic_write, canonical, digest_file
from test_extract import make_pdf


def test_forced_ocr_replaces_bad_embedded_text_and_preserves_empty_pages(
    tmp_path, monkeypatch
):
    from cookbook.extract import paged
    from cookbook import extract

    image = make_pdf(tmp_path / "image-source.pdf")
    pdf = tmp_path / "bad-text.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(612, 792))
    bogus = "Unreliable hidden text: use 4 teaspoons of salt for this entire recipe."
    for visible in (True, False):
        if visible:
            c.drawImage(ImageReader(image), 0, 0, 612, 792)
        hidden = c.beginText(40, 740)
        hidden.setTextRenderMode(3)
        hidden.textLine(bogus)
        c.drawText(hidden)
        c.showPage()
    c.save()
    before = digest_file(pdf)
    source = "pdf:" + before[0]
    native, _, _ = paged(pdf, "PDF", source, tmp_path / "cache")
    assert all(bogus in s["text"] and "ocr" not in s["locator"] for s in native)
    forced, _, _ = paged(pdf, "PDF", source, tmp_path / "cache", force_ocr=True)
    assert "1/2 teaspoon salt" in forced[0]["text"]
    assert forced[1]["text"] == "" and forced[1]["provenance"] == "ocr-empty"
    assert all(bogus not in s["text"] and "ocr" in s["locator"] for s in forced)
    assert [s["id"] for s in native] == [s["id"] for s in forced]
    assert digest_file(pdf) == before

    def failed(*args, **kwargs):
        raise IntegrityError("OCR failed")

    monkeypatch.setattr(extract, "ocr_page", failed)
    with pytest.raises(IntegrityError, match="OCR failed"):
        paged(pdf, "PDF", source, tmp_path / "cache", force_ocr=True)


def test_forced_source_policy_survives_finalization_and_blocks_missing_assessment(
    tmp_path, monkeypatch
):
    from cookbook.quality import check_publish_quality, QUALITY_PATH
    from cookbook.publication import Manifest

    monkeypatch.setattr(ocr, "assess", lambda *args, **kwargs: [])
    snapshot = snapshot_fixture(tmp_path)
    cache, build = tmp_path / "cache", tmp_path / "build"
    with pytest.raises(IntegrityError, match="approved selection"):
        build_snapshot(snapshot, [1], build, cache, force_ocr_ids=[2])
    m, _, _ = build_snapshot(
        snapshot, [1], build, cache, progress=lambda _: None, force_ocr_ids=[1]
    )
    report = read_report(build)
    assert len(report["items"]) == 4 and len(report["forced_ocr_sources"]) == 1
    assert not report["pending_ids"]
    final_dir = tmp_path / "final"
    finalize(build, cache, final_dir)
    assert read_report(final_dir)["forced_ocr_sources"] == report["forced_ocr_sources"]
    inputs = {
        k: Path(v)
        for k, v in json.loads((final_dir / "inputs.json").read_bytes()).items()
    }
    m = Manifest.model_validate_json((final_dir / "manifest.json").read_bytes())
    check_publish_quality(m, inputs)
    # Simulate an extractor regression that trusts one embedded-text page again.
    report = read_report(final_dir)
    removed = report["items"].pop()
    with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
        locator = json.loads(
            db.execute(
                "select locator from sections where id=?", (removed["section_id"],)
            ).fetchone()[0]
        )
        del locator["ocr"]
        db.execute(
            "update sections set locator=?,provenance=? where id=?",
            (json.dumps(locator), "native", removed["section_id"]),
        )
    atomic_write(inputs[QUALITY_PATH], canonical(report))
    m = m.model_copy(
        update={
            "files": [
                e.model_copy(
                    update=dict(zip(("sha256", "size"), digest_file(inputs[e.path])))
                )
                for e in m.files
            ]
        }
    )
    with pytest.raises(ocr.ReviewRequired, match="every forced OCR page"):
        check_publish_quality(m, inputs)


@pytest.mark.parametrize(
    "rotation,skew", [(90, 0), (180, 0), (270, 0), (0, 3), (90, -2)]
)
def test_rotated_skewed_quantities_and_original_preserved(tmp_path, rotation, skew):
    image = make_pdf(tmp_path / "base.pdf")
    image = image.rotate(rotation + skew, expand=True, fillcolor="white")
    pdf = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(pdf), pagesize=image.size)
    c.drawImage(ImageReader(image), 0, 0, *image.size)
    c.showPage()
    c.save()
    before = digest_file(pdf)
    result = ocr_page(pdf, "PDF", 1, tmp_path / "cache", before[0])
    # Linux/macOS Tesseract may capitalize Salt differently; the quantity and
    # ingredient spelling remain exact after case normalization.
    assert "1/2 teaspoon salt" in result["text"].casefold()
    assert "200 grams beans" in result["text"]
    assert result["rotation_ccw"] == (360 - rotation) % 360
    assert abs(result["deskew_ccw"] + skew) <= 0.5
    assert digest_file(pdf) == before
    again = ocr_page(pdf, "PDF", 1, tmp_path / "cache", before[0])
    assert result == again


def test_quality_flags_are_not_accuracy_claims():
    result = {
        "text": "1/2 teaspoon salt",
        "mean_confidence": 94,
        "words": [
            {"text": "1/2", "confidence": 70},
            {"text": "teaspoon", "confidence": 96},
            {"text": "salt", "confidence": 96},
            {"text": "beans", "confidence": 98},
        ],
    }
    assert "uncertain_quantity" in ocr.assess(
        result, orientation_margin=20, skew_angle=0
    )
    assert "ambiguous_orientation" in ocr.assess(
        result, orientation_margin=0, skew_angle=0
    )
    assert ocr.assess({"words": []}, orientation_margin=0, skew_angle=0) == [
        "no_text_on_nonblank_page"
    ]
    assert (
        ocr.assess({"words": []}, orientation_margin=0, skew_angle=0, blank=True) == []
    )


def snapshot_fixture(tmp_path):
    snapshot = tmp_path / "snapshot" / "library"
    folder = snapshot / "Test" / "Scan (1)"
    folder.mkdir(parents=True)
    make_pdf(folder / "scan.pdf")
    with sqlite3.connect(snapshot / "metadata.db") as db:
        db.executescript("""create table library_id(uuid text);insert into library_id values('synthetic-library');
        create table books(id integer, uuid text, title text, path text);insert into books values(1,'synthetic-book','Scanned Test','Test/Scan (1)');
        create table data(book integer,format text,name text);insert into data values(1,'PDF','scan');
        create table authors(id integer,name text);create table books_authors_link(id integer,book integer,author integer);
        create table tags(id integer,name text);create table books_tags_link(book integer,tag integer);""")
    files = []
    for p in snapshot.rglob("*"):
        if p.is_file():
            sha, size = digest_file(p)
            files.append(
                {"path": str(p.relative_to(snapshot)), "sha256": sha, "size": size}
            )
    atomic_write(
        snapshot.parent / "snapshot-manifest.json", canonical({"files": files})
    )
    return snapshot


def test_pending_review_blocks_publish_and_correction_finalizes_new_version(
    tmp_path, published, monkeypatch
):
    _, _, store, runtime, lib, _ = published
    monkeypatch.setattr(
        ocr,
        "assess",
        lambda result, **kw: [] if kw.get("blank") else ["uncertain_quantity"],
    )
    cache = tmp_path / "ocr-cache"
    build = tmp_path / "build-review"
    m, inputs, _ = build_snapshot(
        snapshot_fixture(tmp_path), [1], build, cache, progress=lambda x: None
    )
    report = read_report(build)
    assert len(report["pending_ids"]) == 1
    old_control, version = store.read_version("control/active.json")
    old_active = runtime.active()
    objects = store.list("objects")
    with pytest.raises(ocr.ReviewRequired):
        publish(store, m, inputs, expected_version=version, activate=runtime.activate)
    assert (
        store.read("control/active.json") == old_control
        and runtime.active() == old_active
        and store.list("objects") == objects
    )
    with pytest.raises(ocr.ReviewRequired):
        finalize(build, cache, tmp_path / "not-ready")
    item = next(i for i in report["items"] if i["pending"])
    review_id = item["review_id"]
    with pytest.raises(IntegrityError):
        ocr.decide(cache, review_id, "f" * 64, "accept")
    with pytest.raises(IntegrityError):
        ocr.decide(cache, review_id, item["result_sha256"], "correct", text="")
    ocr.decide(
        cache,
        review_id,
        item["result_sha256"],
        "correct",
        text="Reviewed saffron recipe. Use 1/2 teaspoon salt.",
    )
    original_hash = digest_file(inputs["runtime/index.sqlite"])
    new = finalize(build, cache, tmp_path / "finalized")
    assert (
        new.publication_id != m.publication_id
        and digest_file(inputs["runtime/index.sqlite"]) == original_hash
    )
    new_inputs = {
        k: Path(v)
        for k, v in json.loads(
            (tmp_path / "finalized" / "inputs.json").read_bytes()
        ).items()
    }
    r = publish(
        store, new, new_inputs, expected_version=version, activate=runtime.activate
    )
    assert r["status"] == "active"
    found = lib.search("saffron")["results"]
    assert len(found) == 1
    citation = found[0]["citation"]
    assert citation["locator"]["physical_page"] == 2
    assert citation["extraction"]["provenance"] == "ocr-reviewed-correct"
    assert "Reviewed saffron" not in json.dumps(citation)
    assert "text" not in citation["locator"]["ocr"]["decision"]
    # Blank and text pages retain their original physical order.
    with lib.db(new.publication_id) as db:
        assert db.execute("select count(*) from sections").fetchone()[0] == 4


def test_review_page_escapes_text_and_validates_images(tmp_path):
    from cookbook.ocr import key_for, sha

    config = {"sha256": "a" * 64, "page": 1}
    review_id = key_for(config)
    directory = tmp_path / "v2" / review_id
    directory.mkdir(parents=True)
    im = Image.new("RGB", (30, 30), "white")
    for name in ("original", "corrected"):
        im.save(directory / (name + ".png"))
    result = {
        "text": "<script>alert(1)</script>",
        "words": [],
        "mean_confidence": 0,
        "reasons": ["sparse_text"],
        "rotation_ccw": 0,
        "deskew_ccw": 0,
        "original_image_sha256": digest_file(directory / "original.png")[0],
        "corrected_image_sha256": digest_file(directory / "corrected.png")[0],
    }
    payload = {"config": config, "result": result}
    record = {"payload": payload, "result_sha256": sha(canonical(payload))}
    atomic_write(directory / "result.json", canonical(record))
    assert (
        ocr.write_review_page(
            tmp_path, [{"review_id": review_id}], tmp_path / "report.html"
        )
        == 1
    )
    page = (tmp_path / "report-pages" / (review_id + ".html")).read_text()
    assert "<script>" not in page and "&lt;script&gt;" in page
    ocr.decide(tmp_path, review_id, record["result_sha256"], "nontext")
    assert ocr.effective(record, tmp_path, review_id)["text"] == ""
    (directory / "corrected.png").write_bytes(b"changed")
    with pytest.raises(IntegrityError):
        ocr.load_record(tmp_path, review_id)


def test_legacy_build_cannot_bypass_new_gate(published):
    m, inputs, store, runtime, _, _ = published
    old = runtime.active()
    before = store.read("control/active.json")
    legacy = m.model_copy(update={"schema_version": 1})
    with pytest.raises(ocr.ReviewRequired):
        publish(store, legacy, inputs, expected_version=None, activate=runtime.activate)
    assert runtime.active() == old and store.read("control/active.json") == before
