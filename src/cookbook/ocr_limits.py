"""Fail-closed OCR admission using Linux cgroup v2, not environment assertions."""

import json
from pathlib import Path
import sys
import time

MAX_MEMORY = 2 * 1024**3
MAX_PIDS = 64
MAX_CPUS = 2
MAX_SECONDS = 300
CGROUP = Path("/sys/fs/cgroup")
MESSAGE = (
    "OCR requires the resource-isolated launcher: "
    "python scripts/ocr_sandbox.py run --help. Native macOS OCR is disabled; "
    "network sandboxing, ulimit and RSS polling are not a hard RAM boundary."
)


class OcrIsolationError(RuntimeError):
    pass


def kernel_limits(root=CGROUP):
    """Read effective limits from the private cgroup namespace's root."""
    try:
        memory = int((root / "memory.max").read_text())
        swap = int((root / "memory.swap.max").read_text())
        pids = int((root / "pids.max").read_text())
        quota, period = map(int, (root / "cpu.max").read_text().split())
        if not (
            0 < memory <= MAX_MEMORY
            and swap == 0
            and 0 < pids <= MAX_PIDS
            and 0 < quota <= MAX_CPUS * period
            and period > 0
        ):
            raise ValueError("unsafe resource limits")
        return dict(memory=memory, swap=swap, pids=pids, quota=quota, period=period)
    except (OSError, ValueError) as error:
        raise OcrIsolationError(MESSAGE) from error


def require_ocr_limits():
    """Check kernel limits and the live PID-1 watchdog before heavy work."""
    if sys.platform != "linux":
        raise OcrIsolationError(MESSAGE)
    limits = kernel_limits()
    try:
        if Path("/proc/self/cgroup").read_text().strip() != "0::/":
            raise ValueError("private cgroup namespace required")
        command = Path("/proc/1/cmdline").read_bytes().split(b"\0")
        if b"/guard/ocr_worker.py" not in command:
            raise ValueError("watchdog must be PID 1")
        proof = json.loads(Path("/run/ocr/guard.json").read_text())
        remaining = proof["deadline"] - time.monotonic()
        if proof["limits"] != limits or not 0 < remaining <= MAX_SECONDS:
            raise ValueError("watchdog deadline/limits invalid")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise OcrIsolationError(MESSAGE) from error
    return limits
