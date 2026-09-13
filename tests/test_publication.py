import pytest
from cookbook.publication import (
    Runtime,
    publish,
    restore,
    load_manifest,
    synthetic_gc_plan,
)
from cookbook.storage import Conflict, IntegrityError, digest_file
from conftest import fixture_build


def test_full_restore_and_empty_runtime(published, tmp_path):
    m, inputs, store, runtime, lib, result = published
    restore(store, result, tmp_path / "restored")
    for e in m.files:
        assert digest_file(tmp_path / "restored" / e.path) == (e.sha256, e.size)
    fresh = Runtime(store, tmp_path / "fresh")
    assert fresh.recover() == m.publication_id
    assert not (tmp_path / "fresh" / "backup").exists()


def test_corruption_and_missing_never_switch(published, tmp_path):
    m, inputs, store, runtime, lib, r = published
    m2, i2 = fixture_build(tmp_path / "other")
    old = runtime.active()
    raw, version = store.read_version("control/active.json")
    key = m2.files[0].key
    store.path(key).write_bytes(b"corrupt")
    with pytest.raises(IntegrityError):
        publish(store, m2, i2, expected_version=version, activate=runtime.activate)
    assert runtime.active() == old and store.read("control/active.json") == raw
    store.path(key).unlink()
    saved = store.put_file
    store.put_file = lambda k, p: None if k == key else saved(k, p)
    with pytest.raises(FileNotFoundError):
        publish(store, m2, i2, expected_version=version, activate=runtime.activate)
    assert runtime.active() == old and store.read("control/active.json") == raw


def test_stale_publish_cas_and_pending(published, tmp_path):
    m, inputs, store, runtime, lib, r = published
    m2, i2 = fixture_build(tmp_path / "other")
    with pytest.raises(Conflict):
        publish(store, m2, i2, expected_version=None, activate=runtime.activate)
    assert runtime.active()["publication_id"] == m.publication_id
    _, version = store.read_version("control/active.json")
    result = publish(store, m2, i2, expected_version=version, activate=lambda p: None)
    assert (
        result["status"] == "pending_activation"
        and runtime.active()["publication_id"] == m.publication_id
    )
    assert runtime.recover() == m2.publication_id


def test_corrupt_restore_keeps_prior(published, tmp_path):
    m, inputs, store, runtime, lib, r = published
    m2, i2 = fixture_build(tmp_path / "other")
    _, v = store.read_version("control/active.json")
    publish(store, m2, i2, expected_version=v, activate=lambda p: None)
    store.path(m2.files[0].key).write_bytes(b"corrupt")
    with pytest.raises(IntegrityError):
        runtime.recover()
    assert runtime.active()["publication_id"] == m.publication_id
    assert not (runtime.root / "versions" / m2.publication_id).exists()


def test_gc_shared_and_pending_fail_closed(published, tmp_path):
    m, inputs, store, runtime, lib, r = published
    m2, i2 = fixture_build(tmp_path / "other")
    _, v = store.read_version("control/active.json")
    pending = publish(store, m2, i2, expected_version=v, activate=lambda p: None)
    store.put_bytes("objects/" + "f" * 64, b"orphan")
    assert synthetic_gc_plan(store, [r], [pending]) == ["objects/" + "f" * 64]
    with pytest.raises(IntegrityError):
        synthetic_gc_plan(store, [r], [])
    assert set(e.key for e in m.files) & set(e.key for e in m2.files)


def test_path_traversal_and_manifest_corruption(published, tmp_path):
    from cookbook.publication import Entry
    from pydantic import ValidationError

    with pytest.raises((IntegrityError, ValidationError)):
        Entry(path="../bad", sha256="0" * 64, size=0, role="asset")
    m, inputs, store, runtime, lib, r = published
    store.path("publications/" + m.publication_id + "/manifest.json").write_bytes(b"{}")
    with pytest.raises(IntegrityError):
        load_manifest(store, r)


def test_current_plus_two_retention_and_interrupted_stage(published, tmp_path):
    from cookbook.publication import retention_plan

    m, inputs, store, runtime, lib, first = published
    successes = [first]
    for i in range(4):
        m2, i2 = fixture_build(tmp_path / f"b{i}")
        _, v = store.read_version("control/active.json")
        r = publish(
            store,
            m2,
            i2,
            expected_version=v,
            activate=runtime.activate if i < 3 else lambda p: None,
        )
        if i < 3:
            successes.insert(0, r)
        else:
            pending = [r]
    plan = retention_plan(store, successes, pending)
    assert len(plan["retained"]) == 4 and len(plan["manifests_to_remove"]) == 1
    assert m.files[0].key in plan["objects_to_remove"]
    assert m.files[1].key not in plan["objects_to_remove"]
    # Execute the plan only in this disposable synthetic store, then restore all retained versions.
    for key in plan["manifests_to_remove"] + plan["objects_to_remove"]:
        store.delete(key)
    for i, r in enumerate(successes[:3] + pending):
        restore(store, r, tmp_path / f"restored-retained-{i}")


@pytest.mark.parametrize("workers", [1, 4])
def test_transfer_failure_preserves_pointer_and_retry_verifies_all(
    published, tmp_path, workers
):
    m, inputs, store, runtime, lib, first = published
    m2, i2 = fixture_build(tmp_path / "parallel", count=8)
    old_raw, version = store.read_version("control/active.json")
    bad = m2.files[0]
    store.put_bytes(bad.key, b"corrupt")
    events = []
    with pytest.raises(IntegrityError):
        publish(
            store,
            m2,
            i2,
            expected_version=version,
            activate=runtime.activate,
            transfer_workers=workers,
            progress=events.append,
        )
    assert store.read("control/active.json") == old_raw
    assert runtime.active()["publication_id"] == m.publication_id
    store.path(bad.key).unlink()
    events.clear()
    result = publish(
        store,
        m2,
        i2,
        expected_version=version,
        activate=runtime.activate,
        transfer_workers=workers,
        progress=events.append,
    )
    assert result["status"] == "active"
    readbacks = [e for e in events if e["phase"] == "readback"]
    assert readbacks[-1]["completed"] == len({e.sha256 for e in m2.files})
    restore(store, result, tmp_path / "verified-restore")
    for e in m2.files:
        assert digest_file(tmp_path / "verified-restore" / e.path) == (e.sha256, e.size)


@pytest.mark.parametrize("persistent", [False, True])
def test_interrupted_readback_restarts_hash_verification(
    published, tmp_path, persistent
):
    from botocore.exceptions import ReadTimeoutError

    m, inputs, store, runtime, lib, first = published
    m2, i2 = fixture_build(tmp_path / "readback-retry")
    old_raw, version = store.read_version("control/active.json")
    original_open = store.open
    failed = []

    class InterruptedBody:
        def __init__(self, body):
            self.body, self.started = body, False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.body.close()

        def read(self, size):
            if self.started:
                raise ReadTimeoutError(endpoint_url="https://synthetic.invalid")
            self.started = True
            return self.body.read(7)

    def interrupted(key):
        if key == m2.files[0].key and (persistent or not failed):
            failed.append(key)
            return InterruptedBody(original_open(key))
        return original_open(key)

    store.open = interrupted
    if persistent:
        with pytest.raises(ReadTimeoutError):
            publish(
                store,
                m2,
                i2,
                expected_version=version,
                activate=runtime.activate,
                readback_attempts=3,
            )
        assert len(failed) == 3
        assert store.read("control/active.json") == old_raw
        assert runtime.active()["publication_id"] == m.publication_id
        return
    result = publish(
        store,
        m2,
        i2,
        expected_version=version,
        activate=runtime.activate,
        readback_attempts=3,
    )
    assert failed and result["status"] == "active"
    assert runtime.active()["publication_id"] == m2.publication_id
