"""Opt-in transport experiment using disposable synthetic session-bucket objects.

Run on the hosted machine with --live-synthetic-writes. Never reads owner keys.
No application clients/configuration change. No credentials or keys are printed.
"""

import argparse
import json
import os
import secrets
import statistics
import time


def run(profile_expect=False):
    import botocore.handlers
    import urllib3.util
    from cryptography.fernet import Fernet

    from cookbook.hosted import s3_store
    from cookbook.storage import Conflict

    def store():
        return s3_store(
            os.environ.get("READER_S3_ENDPOINT_URL") or os.environ["S3_ENDPOINT_URL"],
            os.environ["READER_S3_BUCKET"],
            os.environ["READER_AWS_ACCESS_KEY_ID"],
            os.environ["READER_AWS_SECRET_ACCESS_KEY"],
        )

    clients = {"default": store(), "without_expect": store()}
    clients["without_expect"].client.meta.events.unregister(
        "before-call.s3", botocore.handlers.add_expect_header
    )
    attempts = []

    def after_call(parsed, **kwargs):
        attempts.append(parsed.get("ResponseMetadata", {}).get("RetryAttempts", 0))

    for client in clients.values():
        client.client.meta.events.register("after-call.s3", after_call)
    cipher = Fernet(Fernet.generate_key())
    keys = {name: "research/session-134/" + secrets.token_hex(24) for name in clients}
    versions = {}
    results = {name: [] for name in clients}
    waits = []
    original_wait = urllib3.util.wait_for_read

    def wait(sock, timeout=None):
        started = time.perf_counter()
        try:
            return original_wait(sock, timeout)
        finally:
            waits.append((time.perf_counter() - started) * 1000)

    def timed(fn, *args, **kwargs):
        waits.clear()
        attempts.clear()
        started, cpu = time.perf_counter(), time.process_time()
        result = fn(*args, **kwargs)
        return result, {
            "wall_ms": (time.perf_counter() - started) * 1000,
            "cpu_ms": (time.process_time() - cpu) * 1000,
            "expect_wait_ms": sum(waits),
            "expect_wait_calls": len(waits),
            "sdk_retries": sum(attempts),
        }

    cleanup_failed = 0
    try:
        # Warm both pools; no creation time is included in the measured updates.
        for name, client in clients.items():
            data = cipher.encrypt(b'{"synthetic":true}')
            versions[name] = client.put_bytes(keys[name], data, expected=None)
            assert client.read_version(keys[name])[0] == data
        if profile_expect:
            urllib3.util.wait_for_read = wait
        for lap in range(5):
            for name, client in clients.items():
                data = cipher.encrypt(
                    json.dumps({"synthetic": True, "lap": lap}).encode()
                )
                previous = versions[name]
                versions[name], update = timed(
                    client.put_bytes, keys[name], data, expected=previous
                )
                (stored, version), read = timed(client.read_version, keys[name])
                assert stored == data and version == versions[name]

                def reject(client, key, previous):
                    try:
                        client.put_bytes(
                            key, b"synthetic stale writer", expected=previous
                        )
                    except Conflict:
                        return True
                    raise AssertionError("stale write accepted")

                rejected, conflict = timed(reject, client, keys[name], previous)
                assert rejected
                assert client.read_version(keys[name]) == (data, versions[name])
                results[name].append(
                    {"update": update, "read": read, "conflict": conflict}
                )
    finally:
        urllib3.util.wait_for_read = original_wait
        for name, client in clients.items():
            try:
                client.delete(keys[name])
                assert client.read_version(keys[name]) == (None, None)
            except Exception:  # noqa: BLE001 - suppress private provider details at probe boundary
                cleanup_failed += 1
            client.client.close()

    def summary(values):
        return {
            "median": round(statistics.median(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    print(
        json.dumps(
            {
                "samples_per_variant": 5,
                "expect_profile_enabled": profile_expect,
                "cleanup_failures": cleanup_failed,
                "results": {
                    name: {
                        operation: {
                            field: summary([r[operation][field] for r in rows])
                            for field in rows[0][operation]
                        }
                        for operation in ("update", "read", "conflict")
                    }
                    for name, rows in results.items()
                },
            },
            sort_keys=True,
        )
    )
    if cleanup_failed:
        raise SystemExit("Synthetic object cleanup was not confirmed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-synthetic-writes", action="store_true", required=True)
    parser.add_argument("--profile-expect", action="store_true")
    args = parser.parse_args()
    try:
        run(profile_expect=args.profile_expect)
    except Exception:  # noqa: BLE001 - suppress private provider details at probe boundary
        raise SystemExit(
            "Transport probe failed; private exception details suppressed"
        ) from None
