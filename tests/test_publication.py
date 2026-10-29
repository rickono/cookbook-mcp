import pytest
from conftest import fixture_build

from cookbook.publication import (
    Runtime,
    load_manifest,
    publish,
    restore,
    synthetic_gc_plan,
)
from cookbook.storage import Conflict, IntegrityError, digest_file


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
    from pydantic import ValidationError

    from cookbook.publication import Entry

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


def test_activation_exception_reports_actual_remote_and_runtime_and_recovers(
    published, tmp_path
):
    m, inputs, store, runtime, lib, first = published
    m2, i2 = fixture_build(tmp_path / "activation-failure")
    _, version = store.read_version("control/active.json")

    def unavailable(pointer):
        raise OSError("Injected activation outage")

    result = publish(store, m2, i2, expected_version=version, activate=unavailable)
    assert result["status"] == "pending_activation"
    assert result["activation_error"] == "OSError"
    state = runtime.status()
    assert state["status"] == "pending_activation"
    assert state["remote_pointer"]["publication_id"] == m2.publication_id
    assert state["runtime_pointer"]["publication_id"] == m.publication_id
    restore(store, first, tmp_path / "retained-working")
    restore(store, result, tmp_path / "retained-pending")
    fresh = Runtime(store, runtime.root)
    assert fresh.resume_cached() == m.publication_id
    assert fresh.recover() == m2.publication_id
    assert fresh.status()["status"] == "active"


def test_rollback_selects_verified_retained_publication_with_cas(published, tmp_path):
    m, inputs, store, runtime, lib, first = published
    m2, i2 = fixture_build(tmp_path / "next")
    _, version = store.read_version("control/active.json")
    publish(store, m2, i2, expected_version=version, activate=runtime.activate)
    raw, version = store.read_version("control/active.json")
    with pytest.raises(Conflict):
        runtime.rollback(first, expected_version=None)
    assert store.read("control/active.json") == raw
    result = runtime.rollback(first, expected_version=version)
    assert result["status"] == "active"
    assert runtime.status()["runtime_pointer"]["publication_id"] == m.publication_id
    assert runtime.manifest(m2.publication_id) == m2
    with pytest.raises(IntegrityError):
        runtime.rollback(
            dict(first, manifest_sha256="f" * 64), expected_version=version
        )


def test_recovery_refuses_unreadable_current_eligibility(published, tmp_path):
    from cookbook.withdrawal import KEY

    m, inputs, store, runtime, lib, first = published
    m2, i2 = fixture_build(tmp_path / "pending")
    _, version = store.read_version("control/active.json")
    pending = publish(store, m2, i2, expected_version=version, activate=lambda p: None)
    store.put_bytes(KEY, b"[{}]")
    with pytest.raises(IntegrityError, match="invalid"):
        runtime.recover()
    assert runtime.active()["publication_id"] == m.publication_id
    assert load_manifest(store, pending) == m2


def test_administrative_status_recovery_and_explicit_rollback(
    published, tmp_path, monkeypatch, capsys
):
    import json

    from cookbook.cli import main
    from cookbook.storage import canonical

    m, inputs, store, runtime, lib, first = published
    m2, i2 = fixture_build(tmp_path / "pending-admin")
    _, version = store.read_version("control/active.json")
    publish(store, m2, i2, expected_version=version, activate=lambda p: None)
    pointer_file = tmp_path / "prior.json"
    pointer_file.write_bytes(canonical(first))

    def command(name, *extra):
        monkeypatch.setattr(
            "sys.argv",
            [
                "cookbook",
                name,
                "--store",
                str(store.root),
                "--runtime",
                str(runtime.root),
                *extra,
            ],
        )
        main()
        return json.loads(capsys.readouterr().out)

    status = command("publication-status-local")
    assert status["status"] == "pending_activation"
    assert status["runtime_pointer"]["publication_id"] == m.publication_id
    assert (
        command("recover-local")["runtime_pointer"]["publication_id"]
        == m2.publication_id
    )
    result = command("rollback-local", "--pointer", str(pointer_file))
    assert result["status"] == "active"
    assert result["remote_pointer"]["publication_id"] == m.publication_id


@pytest.mark.parametrize("failure", ["corrupt", "missing", "review_source"])
def test_failed_finalization_keeps_working_evidence_and_no_new_manifest(
    published, tmp_path, failure
):
    from test_content_approval import candidate, scan_build

    from cookbook.quality import finalize
    from cookbook.storage import canonical
    from cookbook.transcription_review import ReviewStore

    m, inputs, objects, runtime, lib, first = published
    snapshot, scopes = candidate()
    build = tmp_path / "synthetic-scan"
    scan_build(build, snapshot)
    reviews = ReviewStore(tmp_path / "review.json")
    if failure == "review_source":
        snapshot["edition"]["source_sha256"] = "f" * 64
    reviews.save_candidate(snapshot, selections=scopes)
    if failure == "corrupt":
        (build / "original.bin").write_bytes(b"corrupt")
    elif failure == "missing":
        (build / "original.bin").unlink()
    old_remote = objects.read("control/active.json")
    old_index = digest_file(inputs["runtime/index.sqlite"])
    out = tmp_path / "failed-finalization"
    with pytest.raises((IntegrityError, FileNotFoundError)):
        finalize(build, tmp_path / "cache", out, transcription_review=reviews.path)
    assert not (out / "manifest.json").exists()
    assert objects.read("control/active.json") == old_remote
    assert runtime.active()["publication_id"] == m.publication_id
    assert digest_file(inputs["runtime/index.sqlite"]) == old_index
    assert objects.read(
        "publications/" + m.publication_id + "/manifest.json"
    ) == canonical(m.model_dump())
    assert lib.search("beans")["results"]


def test_atomic_runtime_switch_failure_retains_staged_and_working_versions(
    published, tmp_path, monkeypatch
):
    import os

    m, _, store, runtime, _, first = published
    m2, i2 = fixture_build(tmp_path / "atomic-switch")
    _, version = store.read_version("control/active.json")
    replace = os.replace

    def interrupted(source, destination):
        if destination == runtime.root / "active.json":
            raise OSError("Injected atomic switch failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", interrupted)
    result = publish(store, m2, i2, expected_version=version, activate=runtime.activate)
    assert result["status"] == "pending_activation"
    assert runtime.status()["runtime_pointer"]["publication_id"] == m.publication_id
    assert runtime.manifest(m2.publication_id) == m2
    assert runtime.manifest(m.publication_id) == m
    monkeypatch.setattr(os, "replace", replace)
    assert Runtime(store, runtime.root).recover() == m2.publication_id
