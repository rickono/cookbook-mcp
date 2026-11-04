"""Launch source-free sender checks in the existing atomic resource slot.

Live sending is intentionally unavailable. This launcher cannot add networking
to the OCR worker, change resource ceilings, or run native workloads.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from ocr_sandbox import NAME, docker, mount, preflight

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cookbook.ocr_limits import (
    MAX_CPUS,
    MAX_MEMORY,
    MAX_PIDS,
    MAX_SECONDS,
)


def run_check(
    image,
    output,
    command,
    *,
    inputs=None,
    state=None,
    memory=MAX_MEMORY,
    pids=MAX_PIDS,
    cpus=MAX_CPUS,
    seconds=MAX_SECONDS,
):
    if not (
        32 * 1024**2 <= memory <= MAX_MEMORY
        and 8 <= pids <= MAX_PIDS
        and 0 < cpus <= MAX_CPUS
        and 1 <= seconds <= MAX_SECONDS
    ):
        raise ValueError("Sender limits exceed existing policy")
    if not command:
        raise ValueError("Synthetic command required")
    preflight()
    image_id = docker("image", "inspect", image, "--format", "{{.Id}}").stdout.strip()
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("New/empty output directory required")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    args = [
        "create",
        "--name",
        NAME,
        "--label",
        "cookbook.review.sender=synthetic-v1",
        "--pull",
        "never",
        "--network",
        "none",
        "--cgroupns",
        "private",
        "--memory",
        str(memory),
        "--memory-swap",
        str(memory),
        "--cpus",
        str(cpus),
        "--pids-limit",
        str(pids),
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--log-driver",
        "none",
        "--restart",
        "no",
        "--stop-timeout",
        "1",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=134217728,mode=1777",
        "--tmpfs",
        "/run/sender:rw,noexec,nosuid,nodev,size=1048576,mode=1777",
        "--shm-size",
        "16m",
        "--workdir",
        "/sender",
        "--env",
        "PYTHONPATH=/sender",
        "--entrypoint",
        "/usr/local/bin/python",
        "--mount",
        mount(output, "/output", False),
    ]
    if inputs is not None:
        args += ["--mount", mount(inputs, "/inputs")]
    if state is not None:
        Path(state).mkdir(parents=True, exist_ok=True, mode=0o700)
        args += ["--mount", mount(state, "/state", False)]
    args += [image_id, "/sender/guard.py", str(seconds), "--", *command]
    cid = None
    handlers = {}

    def interrupted(*_):
        raise KeyboardInterrupt

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, interrupted)
        cid = docker(*args).stdout.strip()
        conf = json.loads(docker("inspect", cid).stdout)[0]
        hc = conf["HostConfig"]
        if not (
            hc["Memory"] == memory
            and hc["MemorySwap"] == memory
            and hc["PidsLimit"] == pids
            and hc["NanoCpus"] == int(cpus * 1e9)
            and hc["NetworkMode"] == "none"
            and hc["CgroupnsMode"] == "private"
            and hc["ReadonlyRootfs"]
            and not hc["Privileged"]
            and hc["RestartPolicy"]["Name"] == "no"
            and hc["CapDrop"] == ["ALL"]
            and "no-new-privileges" in hc["SecurityOpt"]
        ):
            raise RuntimeError("Docker did not preserve sender isolation")
        expected = {"/output"} | ({"/inputs"} if inputs is not None else set())
        if state is not None:
            expected.add("/state")
        if {
            m["Destination"] for m in conf["Mounts"] if m["Type"] == "bind"
        } != expected:
            raise RuntimeError("Unexpected sender bind mount")
        if inputs is not None and any(
            m["RW"] for m in conf["Mounts"] if m["Destination"] == "/inputs"
        ):
            raise RuntimeError("Inputs must remain read-only")
        (output / "launch.json").write_text(
            json.dumps(
                {
                    "image": image_id,
                    "container": cid,
                    "memory": memory,
                    "pids": pids,
                    "cpus": cpus,
                    "seconds": seconds,
                    "network": "none",
                    "synthetic": True,
                },
                indent=2,
            )
        )
        docker("start", cid)
        try:
            result = docker("wait", cid, timeout=seconds + 15)
            code = int(result.stdout.strip())
        except subprocess.TimeoutExpired:
            docker("kill", cid)
            code = 124
        state = json.loads(docker("inspect", cid, "--format", "{{json .State}}").stdout)
        (output / "container-state.json").write_text(json.dumps(state, indent=2))
        return code
    finally:
        try:
            if cid is not None:
                cleanup = docker("rm", "--force", cid, check=False)
                if cleanup.returncode:
                    raise RuntimeError("Sender cleanup failed; slot remains closed")
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor")
    sub.add_parser("send", help="Always refused pending live admission")
    run = sub.add_parser("synthetic")
    run.add_argument("--image", default="cookbook-review-sender:synthetic")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--inputs", type=Path)
    run.add_argument(
        "--state",
        type=Path,
        help="Private synthetic accounting directory retained across jobs",
    )
    run.add_argument("--memory-mib", type=int, default=128)
    run.add_argument("--pids", type=int, default=12)
    run.add_argument("--cpus", type=float, default=0.5)
    run.add_argument("--seconds", type=int, default=60)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.action == "send":
            raise PermissionError(
                "Live dispatch disabled pending account and concrete workload admission"
            )
        if args.action == "doctor":
            print(json.dumps(preflight(), indent=2))
            return
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        raise SystemExit(
            run_check(
                args.image,
                args.output,
                command,
                inputs=args.inputs,
                state=args.state,
                memory=args.memory_mib * 1024**2,
                pids=args.pids,
                cpus=args.cpus,
                seconds=args.seconds,
            )
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Sender refused: {error}\n")


if __name__ == "__main__":
    main()
