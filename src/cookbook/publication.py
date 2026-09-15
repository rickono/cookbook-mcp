"""Immutable publication assembly, verification, CAS activation and independent restore."""

from __future__ import annotations
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from typing import NamedTuple
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .storage import (
    IntegrityError,
    atomic_write,
    canonical,
    digest_file,
    file_lock,
    safe_key,
    verify,
)

HEX = r"^[a-f0-9]{64}$"


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str = Field(pattern=HEX)
    size: int = Field(ge=0)
    role: str = Field(pattern=r"^(backup|runtime|asset)$")

    @model_validator(mode="after")
    def validate_path(self):
        safe_key(self.path)
        return self

    @property
    def key(self):
        return "objects/" + self.sha256


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=2, ge=1, le=2)
    locator_version: str = "epub-spine-v1"
    publication_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    created_at: str
    files: list[Entry]

    @model_validator(mode="after")
    def complete(self):
        if len({e.path for e in self.files}) != len(self.files):
            raise ValueError("duplicate inventory path")
        if (
            sum(
                e.path == "runtime/index.sqlite" and e.role == "runtime"
                for e in self.files
            )
            != 1
        ):
            raise ValueError("one runtime index required")
        hashes = {}
        for e in self.files:
            if e.sha256 in hashes and hashes[e.sha256] != e.size:
                raise ValueError("inconsistent object size")
            hashes[e.sha256] = e.size
        return self


def load_manifest(store, pointer):
    pub = pointer["publication_id"]
    if not re.fullmatch("[a-f0-9]{32}", pub):
        raise IntegrityError("invalid publication")
    raw = store.read("publications/" + pub + "/manifest.json")
    if hashlib.sha256(raw).hexdigest() != pointer["manifest_sha256"]:
        raise IntegrityError("manifest checksum mismatch")
    m = Manifest.model_validate_json(raw)
    if m.publication_id != pub:
        raise IntegrityError("publication identity mismatch")
    return m


def validate_version(pointer, destination):
    """Verify cached runtime state without depending on the object store."""
    raw = (destination / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != pointer["manifest_sha256"]:
        raise IntegrityError("cached manifest checksum mismatch")
    m = Manifest.model_validate_json(raw)
    if m.publication_id != pointer["publication_id"]:
        raise IntegrityError("cached publication mismatch")
    for e in m.files:
        if e.role == "runtime" and digest_file(destination / e.path) != (
            e.sha256,
            e.size,
        ):
            raise IntegrityError("runtime checksum mismatch")
    import sqlite3

    with sqlite3.connect(
        (destination / "runtime/index.sqlite").as_uri() + "?mode=ro&immutable=1",
        uri=True,
    ) as db:
        if db.execute("pragma integrity_check").fetchone()[0] != "ok":
            raise IntegrityError("invalid index")
        if (
            db.execute("select publication_id from info").fetchone()[0]
            != m.publication_id
        ):
            raise IntegrityError("index publication mismatch")
    return m


def publish(
    store,
    manifest: Manifest,
    inputs: dict[str, Path],
    *,
    expected_version,
    activate,
    transfer_workers=1,
    readback_attempts=1,
    progress=None,
):
    """Caller serializes publisher/GC. activate must confirm this exact runtime ID."""
    from .quality import check_publish_quality

    if not 1 <= transfer_workers <= 4:
        raise ValueError("transfer workers must be between one and four")
    if not 1 <= readback_attempts <= 3:
        raise ValueError("readback attempts must be between one and three")
    check_publish_quality(manifest, inputs)
    raw = canonical(manifest.model_dump())
    mid = manifest.publication_id
    pointer = {
        "publication_id": mid,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }
    # Immutable manifest reserves every reference before any object is transferred.
    key = "publications/" + mid + "/manifest.json"
    if store.exists(key):
        if store.read(key) != raw:
            raise IntegrityError("immutable publication conflict")
    else:
        store.put_bytes(key, raw)

    def upload(e):
        if digest_file(inputs[e.path]) != (e.sha256, e.size):
            raise IntegrityError("local input changed")
        if not store.exists(e.key):
            store.put_file(e.key, inputs[e.path])

    def readback(e):
        from botocore.exceptions import ConnectionClosedError, ReadTimeoutError

        for attempt in range(readback_attempts):
            try:
                verify(store, e.key, e.sha256, e.size)
                return
            except (ConnectionClosedError, ReadTimeoutError):
                if attempt + 1 == readback_attempts:
                    raise

    def transfer(entries, operation, phase):
        # The main thread observes every result before the next phase. Any
        # worker failure leaves the active pointer untouched.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=transfer_workers) as pool:
            pending = {pool.submit(operation, e): e for e in entries}
            completed_bytes = 0
            for completed, future in enumerate(as_completed(pending), 1):
                future.result()
                completed_bytes += pending[future].size
                if progress:
                    progress(
                        {
                            "phase": phase,
                            "completed": completed,
                            "total": len(entries),
                            "completed_bytes": completed_bytes,
                        }
                    )

    transfer(manifest.files, upload, "upload")
    transfer(list({e.sha256: e for e in manifest.files}.values()), readback, "readback")
    load_manifest(store, pointer)
    store.put_bytes(
        "control/active.json", canonical(pointer), expected=expected_version
    )
    if activate(pointer) != mid:
        return {"status": "pending_activation", **pointer}
    return {"status": "active", **pointer}


def restore(store, pointer, destination: Path, *, runtime_only=False):
    m = load_manifest(store, pointer)
    if destination.exists():
        raise IntegrityError("restore destination must be new")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    needed = sum(e.size for e in m.files if not runtime_only or e.role == "runtime")
    needed += len(canonical(m.model_dump()))
    if shutil.disk_usage(destination.parent).free < needed:
        raise IntegrityError("insufficient restore space")
    stage = Path(tempfile.mkdtemp(prefix=".restore-", dir=destination.parent))
    try:
        for e in m.files:
            if runtime_only and e.role != "runtime":
                continue
            p = stage / e.path
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            verify(store, e.key, e.sha256, e.size, p)
        atomic_write(stage / "manifest.json", canonical(m.model_dump()))
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return m


class _RuntimeEntry(NamedTuple):
    path: str
    sha256: str
    size: int
    role: str

    @property
    def key(self):
        return "objects/" + self.sha256


class _RuntimeManifest(NamedTuple):
    """Read-only runtime view; publication construction/serialization stays mutable."""

    schema_version: int
    locator_version: str
    publication_id: str
    created_at: str
    files: tuple[_RuntimeEntry, ...]

    @classmethod
    def from_manifest(cls, manifest):
        return cls(
            manifest.schema_version,
            manifest.locator_version,
            manifest.publication_id,
            manifest.created_at,
            tuple(
                _RuntimeEntry(e.path, e.sha256, e.size, e.role) for e in manifest.files
            ),
        )


def _fingerprint(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


class Runtime:
    def __init__(self, store, root: Path, *, _manifest_capacity=3):
        if _manifest_capacity < 1:
            raise ValueError("manifest capacity must be positive")
        self.store, self.root = store, root
        self._manifest_capacity = _manifest_capacity
        self._manifests = OrderedDict()
        # Only metadata lookup/load/eviction uses this lock. It never acquires
        # the activation lock or spans library queries, downloads or rendering.
        self._manifest_lock = threading.Lock()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _invalidate_manifest(self, publication_id):
        with self._manifest_lock:
            self._manifests.pop(publication_id, None)

    def active(self):
        try:
            return json.loads((self.root / "active.json").read_text())
        except FileNotFoundError:
            return None

    def activate(self, pointer):
        with file_lock(self.root / ".activation.lock"):
            # Validate the remote pointer before using its ID as a filesystem path.
            load_manifest(self.store, pointer)
            destination = self.root / "versions" / pointer["publication_id"]
            if not destination.exists():
                restore(self.store, pointer, destination, runtime_only=True)
            try:
                m = validate_version(pointer, destination)
            finally:
                self._invalidate_manifest(pointer["publication_id"])
            atomic_write(self.root / "active.json", canonical(pointer))
            return m.publication_id

    def resume_cached(self):
        """Called before serving; damaged local state must never report ready."""
        destination = None
        try:
            pointer = self.active()
            if pointer is None:
                return None
            if not re.fullmatch("[a-f0-9]{32}", pointer["publication_id"]):
                raise IntegrityError("invalid cached publication")
            destination = self.root / "versions" / pointer["publication_id"]
            self._invalidate_manifest(pointer["publication_id"])
            return validate_version(pointer, destination).publication_id
        except Exception:
            active = self.root / "active.json"
            if active.exists():
                # Preserve evidence; do not expose a pointer whose bytes failed validation.
                import uuid

                active.rename(
                    self.root / ("invalid-active-" + uuid.uuid4().hex + ".json")
                )
                if destination is not None and destination.exists():
                    destination.rename(
                        self.root / ("invalid-version-" + uuid.uuid4().hex)
                    )
            if destination is not None:
                self._invalidate_manifest(destination.name)
            raise

    def recover(self):
        raw, _ = self.store.read_version("control/active.json")
        if raw:
            return self.activate(json.loads(raw))
        raise IntegrityError("no publication")

    def manifest(self, publication_id):
        if not re.fullmatch("[a-f0-9]{32}", publication_id):
            raise IntegrityError("unavailable publication")
        path = self.root / "versions" / publication_id / "manifest.json"
        with self._manifest_lock:
            try:
                current = _fingerprint(path.stat())
                cached = self._manifests.get(publication_id)
                if cached is not None and cached[0] == current:
                    self._manifests.move_to_end(publication_id)
                    return cached[1]
                # A failed reload must not leave a previously valid entry resident.
                self._manifests.pop(publication_id, None)
                for _ in range(2):
                    with path.open("rb") as source:
                        before = _fingerprint(os.fstat(source.fileno()))
                        raw = source.read()
                        after = _fingerprint(os.fstat(source.fileno()))
                    if before != after or after != _fingerprint(path.stat()):
                        continue
                    manifest = Manifest.model_validate_json(raw)
                    if manifest.publication_id != publication_id:
                        raise IntegrityError("publication identity mismatch")
                    immutable = _RuntimeManifest.from_manifest(manifest)
                    if after != _fingerprint(path.stat()):
                        continue
                    self._manifests[publication_id] = (after, immutable)
                    if len(self._manifests) > self._manifest_capacity:
                        self._manifests.popitem(last=False)
                    return immutable
                raise IntegrityError("publication changed during manifest load")
            except OSError as error:
                self._manifests.pop(publication_id, None)
                # Retained versions are managed administratively; never fetch an
                # arbitrary manifest or substitute the active publication here.
                raise IntegrityError("unavailable publication") from error


def synthetic_gc_plan(store, retained: list[dict], pending: list[dict]):
    """Dry-run only. Caller supplies full inventory under publisher/maintenance lock.

    Real cleanup and grace policy are deliberately not enabled in this POC.
    """
    refs = {e.key for p in retained + pending for e in load_manifest(store, p).files}
    known = {
        "publications/" + p["publication_id"] + "/manifest.json"
        for p in retained + pending
    }
    if set(store.list("publications")) != known:
        raise IntegrityError("incomplete publication reference inventory")
    return sorted(set(store.list("objects")) - refs)


def retention_plan(store, successful: list[dict], pending: list[dict]):
    """Read-only plan: current + two previous successes, plus every pending stage.

    Complete reference inventory and publisher serialization are preconditions.
    No deletion is executed by the application during the local POC.
    """
    inventory = successful + pending
    manifests = {p["publication_id"]: load_manifest(store, p) for p in inventory}
    known = {"publications/" + pid + "/manifest.json" for pid in manifests}
    if set(store.list("publications")) != known:
        raise IntegrityError("incomplete publication reference inventory")
    if len({p["publication_id"] for p in successful}) != len(successful):
        raise IntegrityError("duplicate successful publication")
    retained = successful[:3] + pending
    live = {e.key for p in retained for e in manifests[p["publication_id"]].files}
    return {
        "retained": [p["publication_id"] for p in retained],
        "manifests_to_remove": [
            "publications/" + p["publication_id"] + "/manifest.json"
            for p in successful[3:]
            if p["publication_id"] not in {x["publication_id"] for x in pending}
        ],
        "objects_to_remove": sorted(set(store.list("objects")) - live),
    }
