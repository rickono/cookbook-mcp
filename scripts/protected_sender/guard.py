"""Sender PID 1. Deliberately cannot satisfy OCR worker admission."""

import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

from ocr_limits import CGROUP, MAX_SECONDS, kernel_limits


def require_sender():
    limits = kernel_limits()
    if (
        sys.platform != "linux"
        or Path("/proc/self/cgroup").read_text().strip() != "0::/"
    ):
        raise RuntimeError("Private Linux cgroup required")
    if b"/sender/guard.py" not in Path("/proc/1/cmdline").read_bytes().split(b"\0"):
        raise RuntimeError("Sender PID-1 guard required")
    proof = json.loads(Path("/run/sender/guard.json").read_text())
    remaining = proof["deadline"] - time.monotonic()
    if proof["limits"] != limits or not 0 < remaining <= MAX_SECONDS:
        raise RuntimeError("Sender watchdog proof invalid")
    return limits, remaining


def events(name, field):
    return int(
        dict(line.split() for line in (CGROUP / name).read_text().splitlines()).get(
            field, 0
        )
    )


def main():
    os.umask(0o077)
    seconds = int(sys.argv[1])
    if os.getpid() != 1 or not 1 <= seconds <= MAX_SECONDS or sys.argv[2] != "--":
        raise ValueError("Invalid sender supervisor invocation")
    limits = kernel_limits()
    deadline = time.monotonic() + seconds
    Path("/run/sender/guard.json").write_text(
        json.dumps({"limits": limits, "deadline": deadline})
    )
    require_sender()
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    cancelled = False

    def cancel(*_):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    oom, pids = events("memory.events", "oom_kill"), events("pids.events", "max")
    with Path("/output/job.log").open("wb", buffering=0) as log:
        child = subprocess.Popen(
            sys.argv[3:], stdin=subprocess.DEVNULL, stdout=log, stderr=log
        )
        while True:
            if events("memory.events", "oom_kill") > oom:
                reason, code = "memory_limit", 137
                break
            if events("pids.events", "max") > pids:
                reason, code = "process_limit", 125
                break
            if cancelled:
                reason, code = "cancelled", 130
                break
            if time.monotonic() >= deadline:
                reason, code = "deadline", 124
                break
            status = child.poll()
            if status is not None:
                reason, code = (
                    "completed" if status == 0 else "child_failed",
                    status if status >= 0 else 128 - status,
                )
                break
            time.sleep(0.05)
    Path("/output/sender-result.json").write_text(
        json.dumps({"reason": reason, "exit_code": code, "limits": limits})
    )
    os._exit(code)


if __name__ == "__main__":
    main()
