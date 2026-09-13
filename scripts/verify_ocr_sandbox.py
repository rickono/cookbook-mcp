"""Small synthetic enforcement tests; no OCR, books, or host memory stress."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from ocr_sandbox import NAME, ROOT, docker, preflight, run_job

HEARTBEAT = """
import os,time
os.setsid()
while True:
 with open('/output/heartbeat','a') as f:f.write('alive\\n')
 time.sleep(.05)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="cookbook-mcp:poc")
    args = parser.parse_args()
    report = {"vm": preflight(), "tests": []}
    args.output.mkdir(parents=True, exist_ok=True)

    def run(name, source, expected, seconds=8):
        out = args.output / name
        code = run_job(
            args.image,
            out,
            ["python", "-c", source],
            memory=64 * 1024**2,
            pids=12,
            cpus=0.5,
            seconds=seconds,
        )
        assert code == expected, (name, code, (out / "job.log").read_text())
        assert not docker("ps", "-aq", "--filter", f"name=^/{NAME}$").stdout.strip()
        heartbeat = out / "heartbeat"
        size = heartbeat.stat().st_size if heartbeat.exists() else None
        time.sleep(0.3)
        assert size is None or heartbeat.stat().st_size == size
        state = json.loads((out / "container-state.json").read_text())
        assert not state["Running"] and state["Pid"] == 0
        detail = (
            json.loads((out / "sandbox-result.json").read_text())
            if (out / "sandbox-result.json").exists()
            else {}
        )
        report["tests"].append(
            {
                "case": name,
                "exit_code": code,
                "heartbeat_bytes_after_exit": size,
                "state": state,
                "supervisor": detail,
            }
        )
        (args.output / "verification.json").write_text(json.dumps(report, indent=2))
        print(name, "PASS", code, flush=True)

    run(
        "kernel-and-filesystem",
        """
from cookbook.ocr_limits import require_ocr_limits
from pathlib import Path
import socket
v=require_ocr_limits()
assert v['memory']==64*1024**2 and v['swap']==0 and v['pids']==12
assert v['quota']/v['period']==.5
try:Path('/work/.sandbox-must-not-write').write_text('bad')
except OSError:pass
else:raise AssertionError('writable source mount')
assert len(Path('/proc/net/route').read_text().strip().splitlines())==1
print('Actual cgroup limits, readonly code and network namespace verified')
""",
        0,
    )
    run(
        "cpu-throttling",
        """
from pathlib import Path
import time
def throttled():
 return int(dict(line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines())['nr_throttled'])
before=throttled()
until=time.monotonic()+1.5
while time.monotonic()<until:pass
assert throttled()>before
print('CPU cgroup throttling observed')
""",
        0,
    )
    start_heartbeat = f'import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",{HEARTBEAT!r}])\ntime.sleep(.2)\n'
    # At most 128 MiB attempted inside a 64 MiB cgroup, touching every page.
    run(
        "memory-with-detached-child",
        start_heartbeat
        + """
chunks=[]
for _ in range(16):
 b=bytearray(8*1024**2)
 for i in range(0,len(b),4096):b[i]=1
 chunks.append(b)
time.sleep(2)
raise AssertionError('memory cap not enforced')
""",
        137,
    )
    run(
        "process-limit",
        """
import subprocess,sys,time
for _ in range(24):
 try:subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])
 except OSError:break
time.sleep(2)
raise AssertionError('PID controller event was not handled')
""",
        125,
    )
    run(
        "deadline-with-detached-child",
        start_heartbeat + "time.sleep(30)",
        124,
        seconds=2,
    )
    run("parent-exit-with-detached-child", start_heartbeat, 0)
    run(
        "parent-failure-with-detached-child", start_heartbeat + "raise SystemExit(7)", 7
    )

    # Race another launcher against a live slot, then kill the HOST launcher.
    # The container PID-1 deadline must work without the host process surviving.
    out = args.output / "host-launcher-killed"
    cmd = [
        sys.executable,
        str(ROOT / "scripts/ocr_sandbox.py"),
        "run",
        "--image",
        args.image,
        "--output",
        str(out),
        "--memory-mib",
        "64",
        "--pids",
        "12",
        "--cpus",
        ".5",
        "--seconds",
        "5",
        "--",
        "python",
        "-c",
        start_heartbeat + "time.sleep(30)",
    ]
    with (args.output / "host-launcher.log").open("w") as log:
        host = subprocess.Popen(cmd, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while not (out / "heartbeat").exists() and time.monotonic() < deadline:
                if host.poll() is not None:
                    raise AssertionError("launcher stopped before workload began")
                time.sleep(0.1)
            assert (out / "heartbeat").exists()
            try:
                run_job(
                    args.image,
                    args.output / "conflicting-run",
                    ["python", "-c", "print(1)"],
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("concurrent job unexpectedly admitted")
            assert (
                docker("inspect", NAME, "--format", "{{.State.Running}}").stdout.strip()
                == "true"
            )
            host.kill()
            host.wait(timeout=5)
            time.sleep(5.5)
            state = json.loads(
                docker("inspect", NAME, "--format", "{{json .State}}").stdout
            )
            assert (
                not state["Running"] and state["Pid"] == 0 and state["ExitCode"] == 124
            )
            size = (out / "heartbeat").stat().st_size
            time.sleep(0.3)
            assert (out / "heartbeat").stat().st_size == size
            report["tests"].append(
                {
                    "case": "concurrency-and-host-SIGKILL",
                    "state": state,
                    "heartbeat_stopped": True,
                }
            )
        finally:
            if host.poll() is None:
                host.kill()
                host.wait(timeout=5)
            # Deliberately killed launcher cannot remove its stopped container.
            # The occupied name is fail-closed until this verified cleanup.
            docker("rm", "--force", NAME)
    (args.output / "verification.json").write_text(json.dumps(report, indent=2))
    print("concurrency-and-host-SIGKILL PASS", flush=True)


if __name__ == "__main__":
    main()
