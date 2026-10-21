"""Rebuild the active publication with a new correction ledger, and publish the rebuild.

The refresh reruns the build that made the active publication: the same verified
snapshot, the same approved selection and OCR choices, and the same scanned candidates.
Those inputs are recorded in the publication itself (``quality/build-inputs.json``), and
the candidates come back out of its backup inventory, so only the ledger differs.
Publishing goes through the existing lifecycle (publication.publish_build), which leaves
the active publication and every earlier one untouched unless activation is confirmed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import ledger
from .build import BUILD_INPUTS, BUILD_INPUTS_VERSION, build_snapshot
from .publication import load_manifest, publish_build
from .scanned import (
    CANDIDATE,
    FILES,
    INVENTORY,
    SUMMARY_PATH,
    read_build_report,
)
from .storage import atomic_write, check_bytes, digest_file, verify


class RefreshError(Exception):
    """The active publication cannot be rebuilt as recorded; nothing was changed."""


def active(store):
    """The active pointer and its verified manifest."""
    raw, _ = store.read_version("control/active.json")
    if not raw:
        raise RefreshError("no active publication to refresh")
    pointer = json.loads(raw)
    return pointer, load_manifest(store, pointer)


def _manifest_entry(manifest, path):
    return next((e for e in manifest.files if e.path == path), None)


def _read(store, manifest, path):
    """One publication file's bytes, checked against the manifest; None if absent."""
    entry = _manifest_entry(manifest, path)
    if entry is None:
        return None
    with store.open(entry.key) as f:
        return check_bytes(
            f.read(), entry.sha256, entry.size, "object checksum mismatch"
        )


def _restore(store, manifest, path, destination: Path):
    """Write one publication file to ``destination``, checked against the manifest.

    Returns False if the publication has no such file.
    """
    entry = _manifest_entry(manifest, path)
    if entry is None:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    verify(store, entry.key, entry.sha256, entry.size, destination)
    return True


def recorded_inputs(store, manifest):
    """The build inputs the publication recorded, or RefreshError if it predates them."""
    raw = _read(store, manifest, BUILD_INPUTS)
    if raw is None:
        raise RefreshError(
            "the active publication does not record its build inputs; build and publish "
            "it once with `cookbook build` so a refresh can reuse them"
        )
    record = json.loads(raw)
    if record.get("version") != BUILD_INPUTS_VERSION:
        raise RefreshError("unsupported build-inputs record")
    return record


def ledger_changed(store, manifest, rows):
    """True when the ledger's rows for any scanned source differ from those published."""
    raw = _read(store, manifest, SUMMARY_PATH)
    if raw is None:
        return False
    for source in json.loads(raw)["sources"]:
        rows_for = ledger.for_source(rows, source["source_sha256"])
        if hashlib.sha256(ledger.dump(rows_for)).hexdigest() != source["ledger_sha256"]:
            return True
    return False


def rebuild(store, manifest, rows, work: Path, *, ocr_cache=None, progress=None):
    """Build the publication again from its recorded inputs with ``rows`` as the ledger.

    Returns the new build directory under ``work``. The snapshot must still match its
    recorded proof, and each candidate restored from the inventory must match its digest.
    """
    record = recorded_inputs(store, manifest)
    snapshot = Path(record["snapshot"]["path"])
    proof = snapshot.parent / "snapshot-manifest.json"
    if (
        not proof.is_file()
        or digest_file(proof)[0] != record["snapshot"]["proof_sha256"]
    ):
        raise RefreshError("the recorded snapshot is missing or has changed")
    run = work / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    scanned = {}
    for item in record["scanned"]:
        sha = item["source_sha256"]
        directory = run / "candidates" / sha
        for name in (CANDIDATE, *FILES):
            logical = f"{INVENTORY}/{sha}/{name}"
            if not _restore(store, manifest, logical, directory / name):
                raise RefreshError(f"the publication lacks candidate file {name}")
        if digest_file(directory / CANDIDATE)[0] != item["candidate_sha256"]:
            raise RefreshError("a restored candidate does not match its record")
        scanned[sha] = {
            "physical_pages": item["physical_pages"],
            "candidate": directory,
        }
    build = run / "build"
    build_snapshot(
        snapshot,
        record["approved_ids"],
        build,
        Path(ocr_cache or record["ocr_cache"]),
        progress=progress or (lambda event: None),
        force_ocr_ids=record["force_ocr_ids"],
        scanned=scanned,
        ledger=rows,
    )
    atomic_write(run / ledger.FILE, ledger.dump(rows))
    return build


def republish(store, rows, work: Path, *, activate, ocr_cache=None, progress=None):
    """Rebuild and publish the active publication with ``rows`` if they change it.

    Returns {"status": "unchanged"} when the ledger changes nothing that is published;
    otherwise the publish result plus the build directory and its build report. A build
    or publish failure raises with the active publication unchanged.
    """
    pointer, manifest = active(store)
    previous = pointer["publication_id"]
    if not ledger_changed(store, manifest, rows):
        return {"status": "unchanged", "publication_id": previous}
    build = rebuild(store, manifest, rows, work, ocr_cache=ocr_cache, progress=progress)
    result = publish_build(store, build, activate=activate)
    return {
        **result,
        "previous_publication_id": previous,
        "build": str(build),
        "build_report": read_build_report(build),
    }
