"""Container PID 1: verify cgroups, supervise one job, exit to reap its namespace."""

import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

from ocr_limits import CGROUP, MAX_SECONDS, kernel_limits, require_ocr_limits


def event(name, key):
    values = dict(line.split() for line in (CGROUP / name).read_text().splitlines())
    return int(values.get(key, 0))


def main():
    os.umask(0o077)
    seconds = int(sys.argv[1])
    if os.getpid() != 1 or not 1 <= seconds <= MAX_SECONDS or sys.argv[2] != "--":
        raise ValueError("invalid sandbox watchdog invocation")
    limits = kernel_limits()
    deadline = time.monotonic() + seconds
    Path("/run/ocr/guard.json").write_text(
        json.dumps(dict(limits=limits, deadline=deadline))
    )
    require_ocr_limits()
    # Bound job output; these are disk/file limits, not substitutes for cgroups.
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    cancelled = False

    def cancel(*_):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    initial_oom = event("memory.events", "oom_kill")
    initial_pids = event("pids.events", "max")
    reason, code = "completed", 0
    with Path("/output/job.log").open("wb", buffering=0) as log:
        child = subprocess.Popen(
            sys.argv[3:], stdout=log, stderr=log, stdin=subprocess.DEVNULL
        )
        while True:
            # Check failures even when the direct child just exited. An OOM in a
            # detached grandchild must terminate the rest of this workload too.
            if event("memory.events", "oom_kill") > initial_oom:
                reason, code = "memory_limit", 137
                break
            if event("pids.events", "max") > initial_pids:
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
                code = status if status >= 0 else 128 - status
                reason = "completed" if code == 0 else "child_failed"
                break
            time.sleep(0.05)
    Path("/output/sandbox-result.json").write_text(
        json.dumps(
            {
                "reason": reason,
                "exit_code": code,
                "limits": limits,
                "memory_events": (CGROUP / "memory.events").read_text(),
                "pids_events": (CGROUP / "pids.events").read_text(),
            },
            indent=2,
        )
    )
    # Linux kills EVERY process in a PID namespace when its PID 1 exits,
    # including double-forked/setsid descendants. No process-group assumption.
    os._exit(code)


if __name__ == "__main__":
    main()
