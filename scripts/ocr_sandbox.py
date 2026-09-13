"""Launch local OCR only in a verified resource-limited Linux container."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cookbook.ocr_limits import MAX_MEMORY, MAX_PIDS, MAX_CPUS, MAX_SECONDS  # noqa: E402

NAME = "cookbook-ocr-resource-slot"
CONTEXT = "desktop-linux"
VM_MAX = 4 * 1024**3


def docker(*args, timeout=15, check=True):
    # Explicit context plus a sanitized Docker environment prevents remote
    # DOCKER_HOST/context overrides from moving private book mounts elsewhere.
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCKER_")}
    result = subprocess.run(
        ["docker", "--context", CONTEXT, *map(str, args)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if check and result.returncode:
        raise RuntimeError("Docker operation failed: " + result.stderr[:1000])
    return result


def preflight():
    endpoint = json.loads(
        docker(
            "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"
        ).stdout
    )
    expected = "unix://" + str(Path.home() / ".docker/run/docker.sock")
    if endpoint != expected:
        raise RuntimeError("Only the local Docker Desktop socket is allowed")
    info = json.loads(docker("info", "--format", "{{json .}}").stdout)
    if not (
        info["OSType"] == "linux"
        and info["OperatingSystem"] == "Docker Desktop"
        and info["CgroupVersion"] == "2"
        and 0 < info["MemTotal"] <= VM_MAX
        and 0 < info["NCPU"] <= MAX_CPUS
        and all(
            info.get(k)
            for k in ["MemoryLimit", "SwapLimit", "PidsLimit", "CpuCfsQuota"]
        )
    ):
        raise RuntimeError(
            "Need local Docker Desktop: VM <=4 GiB/2 CPUs, cgroup v2 with memory, swap, PID and CPU enforcement"
        )
    return {
        k: info[k] for k in ["MemTotal", "NCPU", "CgroupVersion", "OperatingSystem"]
    }


def mount(source, target, readonly=True):
    source = Path(source).resolve(strict=True)
    if "," in str(source):
        raise ValueError("Comma in mount path is unsupported")
    return f"type=bind,src={source},dst={target}" + (",readonly" if readonly else "")


def run_job(
    image,
    output,
    command,
    *,
    memory=MAX_MEMORY,
    pids=MAX_PIDS,
    cpus=MAX_CPUS,
    seconds=MAX_SECONDS,
    inputs=None,
):
    if not (
        32 * 1024**2 <= memory <= MAX_MEMORY
        and 8 <= pids <= MAX_PIDS
        and 0 < cpus <= MAX_CPUS
        and 1 <= seconds <= MAX_SECONDS
    ):
        raise ValueError("Requested limits exceed the conservative OCR policy")
    if not command:
        raise ValueError("A command is required after --")
    preflight()
    # Pin the local image ID; never pull implicitly, build or install models here.
    image_id = docker("image", "inspect", image, "--format", "{{.Id}}").stdout.strip()
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be a new or empty directory")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    args = [
        "create",
        "--name",
        NAME,
        "--label",
        "cookbook.ocr.sandbox=v1",
        "--pull",
        "never",
        "--memory",
        str(memory),
        "--memory-swap",
        str(memory),
        "--cpus",
        str(cpus),
        "--pids-limit",
        str(pids),
        "--network",
        "none",
        "--cgroupns",
        "private",
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
        "/run/ocr:rw,noexec,nosuid,nodev,size=1048576,mode=1777",
        "--shm-size",
        "16m",
        "--workdir",
        "/work",
        "--entrypoint",
        "python",
        "--mount",
        mount(ROOT, "/work"),
        "--mount",
        mount(ROOT / "scripts/ocr_worker.py", "/guard/ocr_worker.py"),
        "--mount",
        mount(ROOT / "src/cookbook/ocr_limits.py", "/guard/ocr_limits.py"),
        "--mount",
        mount(output, "/output", False),
    ]
    if inputs is not None:
        args += ["--mount", mount(inputs, "/inputs")]
    for key, value in {
        "PYTHONPATH": "/work/src",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }.items():
        args += ["--env", f"{key}={value}"]
    args += [image_id, "/guard/ocr_worker.py", str(seconds), "--", *command]
    # Docker's fixed container name is an atomic cross-process concurrency slot.
    # A failed create must never delete another launcher's workload.
    created = False
    old_handlers = {}

    def interrupted(*_):
        raise KeyboardInterrupt

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, interrupted)
        cid = docker(*args).stdout.strip()
        created = True
        conf = json.loads(docker("inspect", cid).stdout)[0]
        hc = conf["HostConfig"]
        if not (
            hc["Memory"] == memory
            and hc["MemorySwap"] == memory
            and hc["PidsLimit"] == pids
            and hc["NanoCpus"] == int(cpus * 1e9)
            and hc["NetworkMode"] == "none"
            and hc["ReadonlyRootfs"]
            and not hc["Privileged"]
            and hc["RestartPolicy"]["Name"] == "no"
        ):
            raise RuntimeError("Docker did not preserve required limits")
        (output / "launch.json").write_text(
            json.dumps(
                dict(
                    image=image_id,
                    memory=memory,
                    pids=pids,
                    cpus=cpus,
                    seconds=seconds,
                    container=cid,
                    network="none",
                ),
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
        if created:
            # Removing the container kills its complete PID namespace. A daemon
            # outage cannot remove kernel memory/CPU/PID limits or PID-1 deadline.
            cleanup = docker("rm", "--force", cid, check=False)
            if cleanup.returncode:
                raise RuntimeError(
                    "Container cleanup failed; resource slot remains closed: " + cid
                )
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("doctor")
    run = commands.add_parser("run")
    run.add_argument("--image", default="cookbook-ocr:safe")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--inputs", type=Path)
    run.add_argument("--memory-mib", type=int, default=2048)
    run.add_argument("--pids", type=int, default=MAX_PIDS)
    run.add_argument("--cpus", type=float, default=MAX_CPUS)
    run.add_argument("--seconds", type=int, default=MAX_SECONDS)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.action == "doctor":
            print(json.dumps(preflight(), indent=2))
            return
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        raise SystemExit(
            run_job(
                args.image,
                args.output,
                command,
                memory=args.memory_mib * 1024**2,
                pids=args.pids,
                cpus=args.cpus,
                seconds=args.seconds,
                inputs=args.inputs,
            )
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"OCR sandbox refused: {error}\n")


if __name__ == "__main__":
    main()
