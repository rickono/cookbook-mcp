"""Private stdio worker: synthetic R2 namespace only; no real session keys."""

import base64
import cProfile
import hashlib
import json
import os
import signal
import sys
import time

from cookbook.hosted import s3_store
from cookbook.storage import Conflict

prefix = sys.argv[1]
assert (
    prefix.startswith("research/session-134/benchmark-") and len(prefix.split("/")) == 3
)
store = s3_store(
    os.environ.get("READER_S3_ENDPOINT_URL") or os.environ["S3_ENDPOINT_URL"],
    os.environ["READER_S3_BUCKET"],
    os.environ["READER_AWS_ACCESS_KEY_ID"],
    os.environ["READER_AWS_SECRET_ACCESS_KEY"],
)
keys = set()


def interrupted(signum, frame):
    raise SystemExit(128 + signum)


for sig in (signal.SIGHUP, signal.SIGTERM):
    signal.signal(sig, interrupted)
print(json.dumps({"ready": True, "image": os.environ.get("FLY_IMAGE_REF")}), flush=True)
try:
    for line in sys.stdin:
        request = json.loads(line)
        started = time.perf_counter()
        profiler = cProfile.Profile() if request.get("profile") else None
        if profiler:
            profiler.enable()
        result = {"ok": True}
        try:
            if request["op"] == "ping":
                pass
            else:
                assert request["key"].startswith("reader/owners/")
                key = prefix + "/" + hashlib.sha256(request["key"].encode()).hexdigest()
                keys.add(key)
                if request["op"] == "read":
                    raw, version = store.read_version(key)
                    result.update(
                        data=base64.b64encode(raw).decode() if raw else None,
                        version=version,
                    )
                elif request["op"] == "put":
                    result["version"] = store.put_bytes(
                        key,
                        base64.b64decode(request["data"]),
                        expected=request["expected"],
                    )
                else:
                    raise ValueError("unknown operation")
        except Conflict:
            result = {"ok": False, "conflict": True}
        except Exception:  # noqa: BLE001 - redact provider errors across the relay
            result = {"ok": False, "conflict": False}
        result["worker_ms"] = (time.perf_counter() - started) * 1000
        if profiler:
            profiler.disable()
            import pstats

            stats = pstats.Stats(profiler).stats
            result["profile"] = [
                {
                    "function": str(key),
                    "calls": value[1],
                    "self_ms": value[2] * 1000,
                    "cumulative_ms": value[3] * 1000,
                }
                for key, value in sorted(
                    stats.items(), key=lambda item: item[1][3], reverse=True
                )[:25]
            ]
        print(json.dumps(result), flush=True)
finally:
    for sig in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(sig, signal.SIG_IGN)
    failures = 0
    for key in keys:
        try:
            store.delete(key)
            assert store.read_version(key) == (None, None)
        except Exception:  # noqa: BLE001 - report cleanup failure without private error text
            failures += 1
    store.client.close()
    if failures:
        print(
            json.dumps({"cleanup_prefix": prefix, "cleanup_failures": failures}),
            file=sys.stderr,
            flush=True,
        )
    try:
        print(json.dumps({"cleanup_failures": failures}), flush=True)
    except BrokenPipeError:
        pass
