"""Synthetic runtime boundary checks; no extraction or OCR is invoked."""

from concurrent.futures import ThreadPoolExecutor
import os
import threading

import pytest
from pydantic import ValidationError

from cookbook.library import Library
from cookbook.publication import Manifest, Runtime, publish
from cookbook.storage import IntegrityError
from conftest import fixture_build


def test_reuse_immutable_metadata_and_runtime_isolation(
    published, manifest_loads, tmp_path
):
    m, _, store, runtime, lib, _ = published
    view = runtime.manifest(m.publication_id)
    expected = lib.search("salt")
    for mutate in (
        lambda: setattr(view, "publication_id", "a" * 32),
        lambda: setattr(view, "files", ()),
        lambda: setattr(view.files[0], "sha256", "a" * 64),
        lambda: view.files.clear(),
    ):
        with pytest.raises((AttributeError, TypeError, ValidationError)):
            mutate()
    assert lib.search("salt") == expected
    assert manifest_loads == {"read": 1, "parse": 1}
    # Even an instance pointing at the same root owns its own metadata.
    Runtime(store, runtime.root).manifest(m.publication_id)
    assert manifest_loads == {"read": 2, "parse": 2}
    other = Runtime(store, tmp_path / "empty")
    with pytest.raises(IntegrityError):
        other.manifest(m.publication_id)
    assert manifest_loads == {"read": 2, "parse": 2}


@pytest.mark.parametrize(
    "damage",
    ["remove", "quarantine", "truncate", "corrupt", "replace", "in_place", "identity"],
)
def test_changed_manifest_never_serves_stale_and_repair_reloads(
    published, manifest_loads, damage
):
    m, _, _, runtime, _, _ = published
    pub = m.publication_id
    runtime.manifest(pub)
    path = runtime.root / "versions" / pub / "manifest.json"
    raw = path.read_bytes()
    original = path.stat()
    before = dict(manifest_loads)
    if damage == "remove":
        path.unlink()
    elif damage == "quarantine":
        path.parent.rename(path.parent.with_name("quarantined"))
    elif damage == "truncate":
        path.write_bytes(b"")
    elif damage == "corrupt":
        path.write_bytes(b"{" + b"!" * (len(raw) - 1))
    elif damage == "identity":
        path.write_bytes(raw.replace(pub.encode(), b"a" * 32))
    else:
        changed = raw.replace(b"epub-spine-v1", b"epub-spine-v2")
        assert len(changed) == len(raw) and changed != raw
        if damage == "replace":
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(changed)
            os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
            replacement.replace(path)
        else:
            path.write_bytes(changed)
            os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        assert runtime.manifest(pub).locator_version == "epub-spine-v2"
        assert manifest_loads["parse"] == before["parse"] + 1
    if damage not in ("replace", "in_place"):
        with pytest.raises((IntegrityError, ValidationError)):
            runtime.manifest(pub)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(raw)
    before = dict(manifest_loads)
    assert runtime.manifest(pub).locator_version == m.locator_version
    assert manifest_loads == {k: v + 1 for k, v in before.items()}
    runtime.manifest(pub)
    assert manifest_loads == {k: v + 1 for k, v in before.items()}


def test_lru_eviction_reloads_without_deleting_publications(
    published, manifest_loads, tmp_path
):
    m, _, store, original, _, _ = published
    runtime = Runtime(store, original.root, _manifest_capacity=2)
    lib = Library(runtime)
    pubs = [m.publication_id]
    for i in range(2):
        new, inputs = fixture_build(tmp_path / f"retained-{i}", repeats=i + 1)
        _, version = store.read_version("control/active.json")
        publish(store, new, inputs, expected_version=version, activate=runtime.activate)
        pubs.append(new.publication_id)
    before = dict(manifest_loads)
    for pub in [pubs[0], pubs[1], pubs[0], pubs[2], pubs[0]]:
        result = lib.search("salt", publication_id=pub)
        assert result["publication_id"] == pub and result["results"]
    assert manifest_loads == {k: v + 3 for k, v in before.items()}
    result = lib.search("salt", publication_id=pubs[1])
    assert result["publication_id"] == pubs[1] and result["results"]
    assert manifest_loads == {k: v + 4 for k, v in before.items()}
    for pub in pubs:
        for filename in ("manifest.json", "runtime/index.sqlite"):
            assert (runtime.root / "versions" / pub / filename).is_file()


def test_concurrent_cold_requests_share_one_complete_load(
    published, monkeypatch, manifest_loads
):
    m, _, _, runtime, _, _ = published
    entered, release = threading.Event(), threading.Event()
    start = threading.Barrier(8)
    original = Manifest.model_validate_json

    def parse(raw):
        entered.set()
        assert release.wait(5)
        return original(raw)

    monkeypatch.setattr(Manifest, "model_validate_json", parse)

    def read():
        start.wait(timeout=5)
        view = runtime.manifest(m.publication_id)
        return view.publication_id, [
            (e.path, e.sha256, e.size, e.key) for e in view.files
        ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read) for _ in range(8)]
        try:
            assert entered.wait(5)
        finally:
            release.set()
        results = [f.result(timeout=5) for f in futures]
    assert all(
        r == (m.publication_id, [(e.path, e.sha256, e.size, e.key) for e in m.files])
        for r in results
    )
    assert manifest_loads == {"read": 1, "parse": 1}


@pytest.mark.parametrize("persistent", [False, True])
def test_replacement_during_parse_is_retried_with_bound(
    published, monkeypatch, persistent
):
    m, _, _, runtime, _, _ = published
    path = runtime.root / "versions" / m.publication_id / "manifest.json"
    raw = path.read_bytes()
    original = Manifest.model_validate_json
    calls = []

    def parse(data):
        parsed = original(data)
        calls.append(data)
        if persistent or len(calls) == 1:
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(raw.replace(b"epub-spine-v1", b"epub-spine-v2"))
            replacement.replace(path)
        return parsed

    monkeypatch.setattr(Manifest, "model_validate_json", parse)
    if persistent:
        with pytest.raises(IntegrityError, match="changed during"):
            runtime.manifest(m.publication_id)
    else:
        assert runtime.manifest(m.publication_id).locator_version == "epub-spine-v2"
    assert len(calls) == 2
    monkeypatch.setattr(Manifest, "model_validate_json", original)
    assert runtime.manifest(m.publication_id).locator_version == "epub-spine-v2"


def test_warm_activation_failure_rollback_and_retained_reads(
    published, tmp_path, monkeypatch
):
    m, _, store, runtime, lib, first = published
    old = lib.search("salt")
    new, inputs = fixture_build(tmp_path / "next", repeats=2)
    _, version = store.read_version("control/active.json")
    second = publish(
        store, new, inputs, expected_version=version, activate=runtime.activate
    )
    assert lib.search("salt")["publication_id"] == new.publication_id
    assert lib.search("salt", publication_id=m.publication_id) == old
    assert runtime.activate(first) == m.publication_id
    assert lib.search("salt") == old
    path = runtime.root / "versions" / new.publication_id / "manifest.json"
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"epub-spine-v1", b"epub-spine-v2"))
    with pytest.raises(IntegrityError, match="checksum"):
        runtime.activate(second)
    assert runtime.active()["publication_id"] == m.publication_id
    path.write_bytes(raw)
    monkeypatch.setattr(
        store, "read", lambda *_: (_ for _ in ()).throw(OSError("offline"))
    )
    assert lib.search("salt") == old
    assert (
        lib.search("salt", publication_id=new.publication_id)["publication_id"]
        == new.publication_id
    )


@pytest.mark.parametrize("damage", ["index", "manifest", "valid_json"])
def test_startup_verification_bypasses_warm_cache_and_quarantines(published, damage):
    m, _, _, runtime, lib, _ = published
    lib.search("salt")
    version = runtime.root / "versions" / m.publication_id
    if damage == "index":
        (version / "runtime/index.sqlite").write_bytes(b"bad")
    elif damage == "manifest":
        (version / "manifest.json").write_bytes(b"bad")
    else:
        path = version / "manifest.json"
        path.write_bytes(path.read_bytes().replace(b"epub-spine-v1", b"epub-spine-v2"))
    with pytest.raises(IntegrityError):
        runtime.resume_cached()
    assert runtime.active() is None
    with pytest.raises(IntegrityError):
        runtime.manifest(m.publication_id)
    assert runtime.recover() == m.publication_id
    assert lib.search("salt")["results"]


def test_reads_during_activation_keep_exact_publication(
    published, tmp_path, monkeypatch
):
    from cookbook import publication

    m, _, store, runtime, lib, _ = published
    old = lib.search("salt")
    new, inputs = fixture_build(tmp_path / "next", repeats=2)
    _, version = store.read_version("control/active.json")
    second = publish(
        store, new, inputs, expected_version=version, activate=lambda _: None
    )
    entered, release = threading.Event(), threading.Event()
    original = publication.validate_version

    def validate(pointer, destination):
        result = original(pointer, destination)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(publication, "validate_version", validate)
    with ThreadPoolExecutor(max_workers=3) as pool:
        activation = pool.submit(runtime.activate, second)
        try:
            assert entered.wait(5)
            assert pool.submit(lib.search, "salt").result(timeout=5) == old
            new_result = pool.submit(
                lib.search, "salt", publication_id=new.publication_id
            ).result(timeout=5)
            assert new_result["publication_id"] == new.publication_id
        finally:
            release.set()
        assert activation.result(timeout=5) == new.publication_id
    assert lib.search("salt") == new_result
    assert lib.search("salt", publication_id=m.publication_id) == old


def test_file_change_during_read_retries_before_parsing(
    published, monkeypatch, manifest_loads
):
    from pathlib import Path

    m, _, _, runtime, _, _ = published
    path = runtime.root / "versions" / m.publication_id / "manifest.json"
    raw = path.read_bytes()
    changed = raw.replace(b"epub-spine-v1", b"epub-spine-v2")
    opened = Path.open
    changed_once = False

    class ChangingRead:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.source.close()

        def fileno(self):
            return self.source.fileno()

        def read(self):
            nonlocal changed_once
            result = self.source.read()
            if not changed_once:
                changed_once = True
                # Same inode and size; fstat after reading must detect the write.
                path.write_bytes(changed)
            return result

    def open_file(target, *args, **kwargs):
        source = opened(target, *args, **kwargs)
        if target == path and args == ("rb",):
            return ChangingRead(source)
        return source

    before = dict(manifest_loads)
    monkeypatch.setattr(Path, "open", open_file)
    assert runtime.manifest(m.publication_id).locator_version == "epub-spine-v2"
    assert manifest_loads == {"read": before["read"] + 2, "parse": before["parse"] + 1}
    runtime.manifest(m.publication_id)
    assert manifest_loads == {"read": before["read"] + 2, "parse": before["parse"] + 1}
