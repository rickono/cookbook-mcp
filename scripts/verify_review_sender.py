"""Rerunnable source-free enforcement checks; no providers or source payloads."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ocr_sandbox import NAME, ROOT, docker, preflight, run_job
from review_sender import run_check

HEARTBEAT = """
import os,time
os.setsid()
while True:
 with open('/output/heartbeat','a') as stream:stream.write('alive\\n')
 time.sleep(.05)
"""
START = f'import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",{HEARTBEAT!r}])\ntime.sleep(.2)\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="cookbook-review-sender:synthetic")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a fresh verification directory")
    report = {"vm": preflight(), "checks": []}
    args.output.mkdir(parents=True, mode=0o700)
    fixtures = args.output / "fixtures"
    fixtures.mkdir(mode=0o700)
    shutil.copy(ROOT / "tests/sender_checks.py", fixtures / "checks.py")
    # Short-lived private fixture identity, never a provider credential.
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=sender-synthetic",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(fixtures / "key.pem"),
            "-out",
            str(fixtures / "cert.pem"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (fixtures / "secret").write_text("synthetic-not-a-provider-key")
    (fixtures / "secret").chmod(0o600)

    def record(name, detail):
        report["checks"].append({"case": name, **detail})
        (args.output / "verification.json").write_text(json.dumps(report, indent=2))
        print(name, "PASS", flush=True)

    def run(name, command, expected=0, seconds=15, memory=64 * 1024**2):
        out = args.output / name
        code = run_check(
            args.image,
            out,
            command,
            inputs=fixtures,
            memory=memory,
            pids=12,
            cpus=0.5,
            seconds=seconds,
        )
        if code != expected:
            raise AssertionError((name, code, (out / "job.log").read_text()))
        if docker("ps", "-aq", "--filter", f"name=^/{NAME}$").stdout.strip():
            raise AssertionError("Completed sender left the shared slot occupied")
        heartbeat = out / "heartbeat"
        size = heartbeat.stat().st_size if heartbeat.exists() else None
        time.sleep(0.2)
        assert size is None or heartbeat.stat().st_size == size
        state = json.loads((out / "container-state.json").read_text())
        assert not state["Running"] and state["Pid"] == 0
        record(name, {"exit_code": code, "state": state, "heartbeat_stopped": True})

    run(
        "protocol-ledger-https",
        ["python", "/inputs/checks.py"],
        seconds=60,
        memory=128 * 1024**2,
    )
    run(
        "memory-with-detached-child",
        [
            "python",
            "-c",
            START
            + "chunks=[]\nfor _ in range(16):\n b=bytearray(8*1024**2)\n for i in range(0,len(b),4096):b[i]=1\n chunks.append(b)\ntime.sleep(2)",
        ],
        137,
    )
    run(
        "process-limit",
        [
            "python",
            "-c",
            "import subprocess,sys,time\nfor _ in range(24):\n try:subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])\n except OSError:break\ntime.sleep(2)",
        ],
        125,
    )
    run("deadline", ["python", "-c", START + "time.sleep(30)"], 124, seconds=2)
    run("parent-exit", ["python", "-c", START])
    run("parent-error", ["python", "-c", START + "raise SystemExit(7)"], 7)
    run(
        "cpu-throttling",
        [
            "python",
            "-c",
            "from pathlib import Path\nimport time\ndef count():return int(dict(line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines())['nr_throttled'])\nbefore=count()\nuntil=time.monotonic()+1\nwhile time.monotonic()<until:pass\nassert count()>before",
        ],
    )

    for mode in ("cancel", "kill-host"):
        out = args.output / mode
        state_directory = args.output / (mode + "-state")
        cmd = [
            sys.executable,
            str(ROOT / "scripts/review_sender.py"),
            "synthetic",
            "--image",
            args.image,
            "--output",
            str(out),
            "--state",
            str(state_directory),
            "--memory-mib",
            "64",
            "--pids",
            "12",
            "--cpus",
            ".5",
            "--seconds",
            "7",
            "--",
            "python",
            "-c",
            "import ledger\nledger.initialize('/state/pilot.sqlite',prior_spend=0,prior_liabilities=0,prior_attempts={})\nledger.reserve('/state/pilot.sqlite','crash','crash',1,{'a'*64+'/1':6})\n"
            + START
            + "time.sleep(30)",
        ]
        cid = None
        with (args.output / (mode + ".log")).open("w") as log:
            host = subprocess.Popen(cmd, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 12
                while not (out / "heartbeat").exists() and time.monotonic() < deadline:
                    if host.poll() is not None:
                        raise AssertionError("Sender exited before heartbeat")
                    time.sleep(0.1)
                assert (out / "heartbeat").exists()
                cid = json.loads((out / "launch.json").read_text())["container"]
                # An offline OCR job competes for exactly the same atomic slot.
                try:
                    run_job(
                        "cookbook-mcp:poc",
                        args.output / (mode + "-conflict"),
                        ["python", "-c", "print(1)"],
                    )
                except RuntimeError as error:
                    if "Conflict" not in str(error) or NAME not in str(error):
                        raise
                else:
                    raise AssertionError("OCR overlapped sender")
                assert (
                    docker(
                        "inspect", cid, "--format", "{{.State.Running}}"
                    ).stdout.strip()
                    == "true"
                )
                if mode == "cancel":
                    host.terminate()
                else:
                    host.kill()
                host.wait(timeout=10)
                if mode == "kill-host":
                    time.sleep(7.5)
                    state = json.loads(
                        docker("inspect", cid, "--format", "{{json .State}}").stdout
                    )
                    assert (
                        not state["Running"]
                        and state["Pid"] == 0
                        and state["ExitCode"] == 124
                    )
                    # A stopped stale slot still rejects launchers until verified cleanup.
                    try:
                        run_check(
                            args.image,
                            args.output / "stale-conflict",
                            ["python", "-c", "print(1)"],
                        )
                    except RuntimeError as error:
                        if "Conflict" not in str(error) or NAME not in str(error):
                            raise
                    else:
                        raise AssertionError("Stale slot silently replaced")
                else:
                    assert not docker(
                        "ps", "-aq", "--filter", f"name=^/{NAME}$"
                    ).stdout.strip()
                size = (out / "heartbeat").stat().st_size
                time.sleep(0.2)
                assert (out / "heartbeat").stat().st_size == size
                record(
                    mode, {"heartbeat_stopped": True, "slot_contention_checked": True}
                )
            finally:
                if host.poll() is None:
                    host.kill()
                    host.wait(timeout=5)
                # Never remove by shared name: only this launcher's recorded ID.
                if cid is not None:
                    docker("rm", "--force", cid, check=False)
        resume = """
import ledger
path='/state/pilot.sqlite'
assert ledger.snapshot(path)['liabilities']==1
assert ledger.snapshot(path)['attempts']=={'a'*64+'/1':1}
try:ledger.reserve(path,'crash','crash',1,{'a'*64+'/1':6})
except ValueError:pass
else:raise AssertionError('uncertain request resent')
try:ledger.initialize(path,prior_spend=0,prior_liabilities=0,prior_attempts={})
except FileExistsError:pass
else:raise AssertionError('ledger reset on restart')
"""
        code = run_check(
            args.image,
            args.output / (mode + "-resumed"),
            ["python", "-c", resume],
            state=state_directory,
            memory=64 * 1024**2,
            pids=12,
            cpus=0.5,
            seconds=10,
        )
        assert code == 0, (mode, "durable restart failed")
        record(
            mode + "-durable-restart",
            {"liability_retained": True, "duplicate_refused": True},
        )


if __name__ == "__main__":
    main()
