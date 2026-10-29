"""Publisher-level OCR gate and a new-build finalizer; no mutation of published versions."""

import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .ocr import POLICY, ReviewRequired, effective, load_record
from .storage import IntegrityError, atomic_write, canonical, digest_file

QUALITY_PATH = "quality/ocr-review.json"


def make_report(publication_id, items, *, forced_ocr_sources=()):
    return {
        "publication_id": publication_id,
        "policy": POLICY,
        "items": items,
        "forced_ocr_sources": sorted(forced_ocr_sources),
        "pending_ids": [
            i["review_id"] for i in items if i["reasons"] and i["decision"] is None
        ],
    }


def read_report(build):
    return json.loads((build / "ocr-review.json").read_bytes())


def check_publish_quality(manifest, inputs):
    if manifest.schema_version < 2:
        raise ReviewRequired("legacy build requires quality evaluation")
    entry = next((e for e in manifest.files if e.path == QUALITY_PATH), None)
    index = next(e for e in manifest.files if e.path == "runtime/index.sqlite")
    if entry is None or QUALITY_PATH not in inputs:
        raise ReviewRequired("missing OCR quality report")
    if digest_file(inputs[QUALITY_PATH]) != (entry.sha256, entry.size):
        raise IntegrityError("OCR report changed")
    if digest_file(inputs[index.path]) != (index.sha256, index.size):
        raise IntegrityError("index changed")
    report = json.loads(inputs[QUALITY_PATH].read_bytes())
    if (
        report["policy"] != POLICY
        or report["publication_id"] != manifest.publication_id
    ):
        raise IntegrityError("OCR report mismatch")
    if report["pending_ids"]:
        raise ReviewRequired("OCR review required")
    items = {i["section_id"]: i for i in report["items"]}
    forced_sources = set(report.get("forced_ocr_sources", []))
    if len(items) != len(report["items"]):
        raise IntegrityError("duplicate OCR review rows")
    with sqlite3.connect(
        inputs[index.path].resolve().as_uri() + "?mode=ro&immutable=1", uri=True
    ) as db:
        db.row_factory = sqlite3.Row
        from .extract import VERSION

        info = db.execute(
            "select publication_id,extraction_version from info"
        ).fetchone()
        if tuple(info) != (manifest.publication_id, VERSION):
            raise ReviewRequired("build requires current extraction policy")
        seen = set()
        sources = set()
        for row in db.execute(
            "select id,source_id,text,locator,provenance from sections"
        ):
            loc = json.loads(row["locator"])
            sources.add(row["source_id"])
            ocr = loc.get("ocr")
            if row["source_id"] in forced_sources and (
                not ocr
                or loc.get("text_selection") != "forced-ocr"
                or not row["provenance"].startswith("ocr")
            ):
                raise ReviewRequired("every forced OCR page requires an assessment")
            if not ocr:
                if "ocr" in row["provenance"]:
                    raise ReviewRequired("missing OCR assessment")
                continue
            item = items.get(row["id"])
            seen.add(row["id"])
            if item is None or item["source_id"] != row["source_id"]:
                raise IntegrityError("missing indexed OCR review")
            if ocr != {
                k: v
                for k, v in item.items()
                if k not in ("section_id", "source_id", "book_title", "calibre_id")
            }:
                raise IntegrityError("OCR index/report mismatch")
            if (
                item["policy"] != POLICY
                or item["source_sha256"] != row["source_id"].split(":")[-1]
                or item["physical_page"] != loc["physical_page"]
            ):
                raise IntegrityError("OCR source mismatch")
            if (
                item["section_text_sha256"]
                != hashlib.sha256(row["text"].encode()).hexdigest()
            ):
                raise IntegrityError("OCR text changed")
            if item["reasons"]:
                decision = item["decision"]
                if (
                    not decision
                    or decision["result_sha256"] != item["result_sha256"]
                    or decision["decision"] not in ("accept", "correct", "nontext")
                ):
                    raise ReviewRequired("OCR review required")
            decision = item["decision"]
            if (
                decision
                and decision["decision"] == "correct"
                and decision.get("corrected_text_sha256") != item["section_text_sha256"]
            ):
                raise IntegrityError("reviewed correction mismatch")
            if decision and decision["decision"] == "nontext" and row["text"]:
                raise IntegrityError("reviewed nontext page mismatch")
            if item["pending"]:
                raise ReviewRequired("OCR review required")
        from .transcription_review import ReviewStore

        content_rows = list(
            db.execute("select * from sections where provenance='scanned-content-v1'")
        )
        if content_rows:
            path = "quality/content-review.json"
            entry = next((e for e in manifest.files if e.path == path), None)
            if (
                entry is None
                or path not in inputs
                or digest_file(inputs[path]) != (entry.sha256, entry.size)
            ):
                raise IntegrityError("missing or changed content review history")
            expected = {
                s["id"]: s for s in ReviewStore(inputs[path]).publication_sections()
            }
            for row in content_rows:
                section = expected.get(row["id"])
                if (
                    section is None
                    or row["text"] != section["text"]
                    or json.loads(row["locator"]) != section["locator"]
                    or row["source_id"].split(":")[-1] != section["source_sha256"]
                ):
                    raise IntegrityError("content approval/index mismatch")
                search = list(
                    db.execute(
                        "select text from search where section_id=?", (row["id"],)
                    )
                )
                if [r[0] for r in search] != (
                    [section["text"]] if section["eligible"] else []
                ):
                    raise IntegrityError("content approval/search mismatch")
            if {r["id"] for r in content_rows} != set(expected):
                raise IntegrityError("missing reviewed content")
        if seen != set(items):
            raise IntegrityError("unmatched OCR report rows")
        if not forced_sources.issubset(sources):
            raise IntegrityError("forced OCR source missing from index")


def finalize(build: Path, cache: Path, output: Path, *, transcription_review=None):
    from .publication import Entry, Manifest

    if output.exists():
        raise IntegrityError("finalized build directory must be new")
    old = Manifest.model_validate_json((build / "manifest.json").read_bytes())
    if old.schema_version < 2:
        raise ReviewRequired("legacy build requires re-extraction")
    inputs = {
        k: Path(v) for k, v in json.loads((build / "inputs.json").read_bytes()).items()
    }
    for entry in old.files:
        if digest_file(inputs[entry.path]) != (entry.sha256, entry.size):
            raise IntegrityError("build changed")
    report = read_report(build)
    updates = []
    for item in report["items"]:
        record = load_record(cache, item["review_id"])
        if record["result_sha256"] != item["result_sha256"]:
            raise ReviewRequired("OCR result changed; rebuild required")
        current = effective(record, cache, item["review_id"])
        if current["pending"]:
            raise ReviewRequired("OCR review required")
        updates.append((item, current))
    output.mkdir(parents=True, mode=0o700)
    pub = uuid.uuid4().hex
    index = output / "index.sqlite"
    shutil.copyfile(inputs["runtime/index.sqlite"], index)
    items = []
    with sqlite3.connect(index) as db:
        db.row_factory = sqlite3.Row
        db.execute("update info set publication_id=?", (pub,))
        for item, current in updates:
            row = db.execute(
                "select * from sections where id=? and source_id=?",
                (item["section_id"], item["source_id"]),
            ).fetchone()
            if row is None:
                raise IntegrityError("OCR section missing")
            text = current["text"] if current["decision"] else row["text"]
            ocr = {k: v for k, v in current.items() if k != "text"}
            ocr["section_text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
            loc = json.loads(row["locator"])
            loc["ocr"] = ocr
            provenance = (
                "ocr-reviewed-" + current["decision"]["decision"]
                if current["decision"]
                else row["provenance"]
            )
            db.execute(
                "update sections set text=?,locator=?,provenance=? where id=?",
                (text, json.dumps(loc), provenance, row["id"]),
            )
            db.execute("update search set text=? where section_id=?", (text, row["id"]))
            items.append(
                {
                    "section_id": row["id"],
                    "source_id": row["source_id"],
                    **{k: item[k] for k in ("book_title", "calibre_id") if k in item},
                    **ocr,
                }
            )
    if transcription_review is not None:
        from .transcription_review import ReviewStore

        # Freeze one atomic store read so concurrent draft/decision writes cannot
        # produce a publication containing mixed review versions.
        review_path = output / "content-review.json"
        atomic_write(review_path, canonical(ReviewStore(transcription_review).export()))
        reviews = ReviewStore(review_path)
        with sqlite3.connect(index) as db:
            for section in reviews.publication_sections():
                source = db.execute(
                    "select * from sources where sha256=?", (section["source_sha256"],)
                ).fetchone()
                if source is None:
                    raise IntegrityError("review source missing from build")
                # Verify original bytes as well as the saved recognition identities.
                if digest_file(inputs[source[3]])[0] != section["source_sha256"]:
                    raise IntegrityError("review original source mismatch")
                existing = db.execute(
                    "select source_id from sections where id=?", (section["id"],)
                ).fetchone()
                if existing and existing[0] != source[0]:
                    raise IntegrityError("selection identity belongs to another source")
                db.execute("delete from sections where id=?", (section["id"],))
                db.execute("delete from search where section_id=?", (section["id"],))
                db.execute(
                    "insert into sections values (?,?,?,?,?,?,?,?,?)",
                    (
                        section["id"],
                        source[0],
                        section["ordinal"],
                        section["title"],
                        section["text"],
                        json.dumps(section["locator"]),
                        "scanned-content-v1",
                        section["kind"],
                        "[]",
                    ),
                )
                if section["eligible"]:
                    db.execute(
                        "insert into search values (?,?,?,?)",
                        (section["id"], source[0], section["title"], section["text"]),
                    )
        inputs["quality/content-review.json"] = review_path
    report = make_report(
        pub, items, forced_ocr_sources=report.get("forced_ocr_sources", [])
    )
    atomic_write(output / "ocr-review.json", canonical(report))
    inputs["runtime/index.sqlite"] = index
    inputs[QUALITY_PATH] = output / "ocr-review.json"
    entries = []
    for e in old.files:
        sha, size = digest_file(inputs[e.path])
        entries.append(Entry(path=e.path, sha256=sha, size=size, role=e.role))
    if transcription_review is not None:
        sha, size = digest_file(inputs["quality/content-review.json"])
        entries = [e for e in entries if e.path != "quality/content-review.json"]
        entries.append(
            Entry(
                path="quality/content-review.json", sha256=sha, size=size, role="backup"
            )
        )
    m = old.model_copy(
        update={
            "publication_id": pub,
            "files": entries,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    check_publish_quality(m, inputs)
    atomic_write(output / "manifest.json", canonical(m.model_dump()))
    atomic_write(
        output / "inputs.json", canonical({k: str(v) for k, v in inputs.items()})
    )
    return m
