"""Publisher-level OCR gate and a new-build finalizer; no mutation of published versions."""

import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .ocr import POLICY, ReviewRequired, effective, load_record
from .storage import (
    IntegrityError,
    atomic_write,
    canonical,
    check_bytes,
    digest_file,
    has_table,
)

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
        if seen != set(items):
            raise IntegrityError("unmatched OCR report rows")
        if not forced_sources.issubset(sources):
            raise IntegrityError("forced OCR source missing from index")
        check_transcription(manifest, inputs, db)


def _inventory_bytes(files_by_path, inputs, logical, what):
    """A backed-up inventory file's bytes, checked against its manifest entry."""
    e = files_by_path.get(logical)
    if e is None or logical not in inputs:
        raise ReviewRequired(f"missing {what}")
    return check_bytes(
        inputs[logical].read_bytes(), e.sha256, e.size, f"{what} changed"
    )


def _stored_ledger(files_by_path, inputs, sha):
    """The correction ledger backed up beside a scanned candidate (possibly empty)."""
    from . import ledger
    from .scanned import INVENTORY

    logical = f"{INVENTORY}/{sha}/{ledger.FILE}"
    return ledger.parse(
        _inventory_bytes(files_by_path, inputs, logical, "scanned correction ledger")
    )


def _check_bindings(db, rows, item, source_id):
    """Every stored correction names this source; every applied one sits on its page.

    The summary's applied ids must be ledger rows whose page is in the source, and every
    unit recording the id must come from that page. The page unit records it, unless the
    quote was found only in the cited section's text from that page: then the cited
    section is the only unit that does.
    """
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        if r["source_id"] != source_id or r["source_sha256"] != item["source_sha256"]:
            raise IntegrityError(f"correction {r['id']} does not bind to its source")
    corrections = item.get("corrections")
    applied = corrections.get("applied") if isinstance(corrections, dict) else None
    if not isinstance(applied, list):
        raise IntegrityError("transcription summary mismatch")
    recorded = {}
    for unit_id, locator, value in db.execute(
        "select s.id,s.locator,u.corrections from transcription_units u "
        "join sections s on s.id=u.section_id where u.source_id=?",
        (source_id,),
    ):
        locator = json.loads(locator)
        pages = locator.get("physical_pages") or [locator.get("physical_page")]
        for c in json.loads(value):
            recorded.setdefault(c.get("id"), []).append(
                (unit_id, locator["kind"], pages)
            )
    for cid in applied:
        if cid not in by_id:
            raise IntegrityError(
                f"applied correction {cid} is not in the stored ledger"
            )
        page, cited = by_id[cid]["physical_page"], by_id[cid]["section_id"]
        units = recorded.get(cid, [])
        if (
            not isinstance(item.get("pages_total"), int)
            or page > item["pages_total"]
            or not units
            or any(page not in pages for _, _, pages in units)
            or (
                ("page", [page]) not in [(kind, pages) for _, kind, pages in units]
                and {unit for unit, _, _ in units} != {cited}
            )
        ):
            raise IntegrityError(f"correction {cid} does not bind to its page")


def check_transcription(manifest, inputs, db):
    """Transcription text is publishable only as the exact import of a backed-up candidate.

    Every source with transcription-provenance rows must be listed in the transcription
    summary, and its index rows, search rows, labels and TOC must equal a fresh import of
    the candidate files and the correction ledger in the inventory.
    """
    from .scanned import (
        CANDIDATE,
        FILES,
        INVENTORY,
        PROVENANCE,
        SUMMARY_PATH,
        SUMMARY_VERSION,
        import_candidate,
    )

    files_by_path = {e.path: e for e in manifest.files}
    transcribed = {
        r[0]
        for r in db.execute(
            "select distinct source_id from sections where provenance=?", (PROVENANCE,)
        )
    }
    entry = files_by_path.get(SUMMARY_PATH)
    if entry is None and SUMMARY_PATH not in inputs:
        if transcribed:
            raise ReviewRequired("transcription text requires a transcription summary")
        return
    if entry is None or SUMMARY_PATH not in inputs:
        raise ReviewRequired("missing transcription summary")
    if digest_file(inputs[SUMMARY_PATH]) != (entry.sha256, entry.size):
        raise IntegrityError("transcription summary changed")
    summary = json.loads(inputs[SUMMARY_PATH].read_bytes())
    if (
        not isinstance(summary, dict)
        or set(summary) != {"version", "sources"}
        or summary["version"] != SUMMARY_VERSION
        or not isinstance(summary["sources"], list)
        or not all(isinstance(i, dict) for i in summary["sources"])
    ):
        raise IntegrityError("transcription summary mismatch")
    items = {i.get("source_id"): i for i in summary["sources"]}
    if len(items) != len(summary["sources"]):
        raise IntegrityError("transcription summary mismatch")
    if set(items) != transcribed:
        raise ReviewRequired(
            "transcription summary does not cover the transcription text"
        )
    if not (
        has_table(db, "transcription_sources") and has_table(db, "transcription_units")
    ):
        raise IntegrityError("scanned index lacks transcription tables")
    labelled = {
        r[0]
        for q in ("transcription_sources", "transcription_units")
        for r in db.execute(f"select distinct source_id from {q}")
    }
    if not labelled.issubset(items):
        raise IntegrityError("scanned index labels an unsummarised source")
    for source_id, item in items.items():
        sha = item.get("source_sha256")
        row = db.execute("select * from sources where id=?", (source_id,)).fetchone()
        if (
            row is None
            or row["format"] != "PDF"
            or source_id != f"pdf:{sha}"
            or row["sha256"] != sha
        ):
            raise IntegrityError("scanned source mismatch")
        original = files_by_path.get(row["original_path"])
        if original is None or original.sha256 != sha:
            raise IntegrityError("source digest mismatch")
        files = {
            name: _inventory_bytes(
                files_by_path, inputs, f"{INVENTORY}/{sha}/{name}", "scanned candidate"
            )
            for name in (CANDIDATE, *FILES)
        }
        if hashlib.sha256(files[CANDIDATE]).hexdigest() != item.get("candidate_sha256"):
            raise IntegrityError("scanned candidate changed")
        rows = _stored_ledger(files_by_path, inputs, sha)
        _check_bindings(db, rows, item, source_id)
        result = import_candidate(
            files,
            source_id=source_id,
            source_sha256=sha,
            physical_pages=item.get("pages_total"),
            ledger=rows,
        )
        # The stored ledger re-derives every applied, stale and ambiguous outcome.
        if item != result["summary"]:
            raise IntegrityError("transcription summary mismatch")
        stored = db.execute(
            "select summary from transcription_sources where source_id=?", (source_id,)
        ).fetchone()
        units = result["units"]
        indexed = [
            (
                r["id"],
                r["ordinal"],
                r["title"],
                r["text"],
                json.loads(r["locator"]),
                r["provenance"],
                r["kind"],
                json.loads(r["images"]),
            )
            for r in db.execute(
                "select * from sections where source_id=? order by ordinal",
                (source_id,),
            )
        ]
        expected = [
            (
                u["id"],
                n,
                u["title"],
                u["text"],
                u["locator"],
                u["provenance"],
                u["kind"],
                u["images"],
            )
            for n, u in enumerate(units)
        ]
        searched = sorted(
            tuple(r)
            for r in db.execute(
                "select section_id,title,text from search where source_id=?",
                (source_id,),
            )
        )
        labels = {
            r["section_id"]: (
                json.loads(r["label"]),
                json.loads(r["check_regions"]),
                json.loads(r["corrections"]),
            )
            for r in db.execute(
                "select * from transcription_units where source_id=?", (source_id,)
            )
        }
        if (
            stored is None
            or json.loads(stored[0]) != item
            or indexed != expected
            or json.loads(row["toc"]) != result["toc"]
            or searched
            != sorted(
                (u["id"], u["title"], u["text"]) for u in units if u["searchable"]
            )
            or labels
            != {
                u["id"]: (
                    u["transcription"]["label"],
                    u["transcription"]["check_regions"],
                    u["transcription"]["corrections"],
                )
                for u in units
            }
        ):
            raise IntegrityError("scanned index does not match the candidate")


def finalize(build: Path, cache: Path, output: Path):
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
