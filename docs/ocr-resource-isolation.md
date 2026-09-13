# Resource-isolated OCR

OCR and model trials now run through `scripts/ocr_sandbox.py`. The launcher refuses
native execution or an unsuitable Docker backend. It never falls back to running
the command directly, downloading models, or sending book data to a remote host.

The September 12 Paddle trial's network sandbox imposed no RAM limit. Its initial
process reached a 25.6 GiB physical footprint during system-wide memory pressure
on this 24 GiB Mac. The later failed keychain encryption transition and reset are
logged; a causal connection from memory pressure is a strong inference, not a
proven macOS root cause. The private incident report remains the evidence source.
Lower image resolution did not supply the missing resource boundary.

## Launch path

Docker Desktop is already installed. Its local Linux VM was configured to 4 GiB
and two CPUs before startup, with the prior settings backed up privately. The
launcher checks the **running** daemon's memory, CPU and controller support every
time. It requires the explicit `desktop-linux` context and the user's local
`~/.docker/run/docker.sock`; environment overrides and remote contexts are refused.
It does not start or reconfigure Docker automatically.

```sh
python3 scripts/ocr_sandbox.py doctor
```

If this refuses, leave OCR stopped. Start/configure the existing Docker Desktop
only with the stated VM ceiling; then rerun the doctor. Never bypass the guard to
get a failing model running. The 4 GiB VM ceiling leaves most of this Mac's RAM for
desktop services; it is not a promise that unrelated processes cannot cause host
memory pressure. Host Docker/virtualization overhead is outside the guest's cap.

The local ingestion/test image extends the existing `cookbook-mcp:poc` image; it
adds Tesseract and the pinned development dependencies. Build it after the doctor
passes. This build contains only code/dependency manifests, no book data. It is
separate from the deployed service image.

```sh
docker --context desktop-linux build --pull=false -f Dockerfile.ocr -t cookbook-ocr:safe .
python3 scripts/ocr_sandbox.py run \
  --output "$HOME/cookbook-mcp-data/poc/isolated-tests-NEW" \
  -- python -m pytest -q -p no:cacheprovider --basetemp=/tmp/pytest tests
```

Use a new or empty output directory each time. The repository is mounted read-only
at `/work`, the fresh output at `/output`, and an optional `--inputs PATH` directory
read-only at `/inputs`. Refer to those container paths in the command after `--`.
No host environment credentials or Docker socket are mounted. All derived files
must go under `/output` or the bounded temporary filesystem. Source books stay on
this Mac. Mount only the required private subset, not the live library or a home
directory. Any future Paddle image/dependency/model preparation is a separate
step; the old macOS virtual environment is intentionally disabled, not portable
to this Linux environment. The current safe image contains Tesseract, not Paddle.

The image must already exist locally and contain `python` on its PATH. The launcher
pins its image ID for each job. It overrides the image entry point with the
supervisor, disables network/restarts, drops capabilities, enables
no-new-privileges, uses an unprivileged user and a read-only root filesystem.
There is no generic Docker-option passthrough or native override flag.

## Actual enforcement

- **Host isolation:** Docker Desktop's Linux VM is at most 4 GiB/two CPUs. The
  running backend reported 4,109,680,640 bytes and two CPUs after configuration.
- **Whole-workload memory:** cgroup v2 `memory.max` defaults to 2 GiB, including
  descendants, and `memory.swap.max` is zero. The launcher sets equal Docker
  memory/memory-swap values and the worker reads the kernel files before starting.
- **CPU and process count:** `cpu.max` limits the whole cgroup to two CPUs;
  `pids.max` limits processes and threads together to 64. Numerical-library thread
  hints are set to one, but the kernel limits supply enforcement.
- **Concurrency:** the fixed container name is an atomic slot shared by all
  invocations on this daemon. A failed concurrent create never removes the running
  job. Ordinary launchers admit one job; manually bypassing this launcher is not
  authorized by this workflow.
- **Deadline and cleanup:** the container's PID 1 runs an independent five-minute
  watchdog. It watches kernel OOM/PID-limit events and the direct child's status.
  Its exit terminates the complete Linux PID namespace, including detached or
  double-forked descendants. The host has an additional deadline and forcibly
  removes its own container on cancellation/failure. This does not rely on a
  process-group kill reaching detached children.
- **Bounded auxiliary output:** no Docker log collection, 16 MiB per-file limit,
  128 MiB `/tmp`, 16 MiB shared memory. Temporary memory is charged to the cgroup.
  These are auxiliary limits, not the RAM enforcement mechanism. The output bind
  has no aggregate disk quota; this launcher is for trusted local experiments,
  not arbitrary hostile code.

Limits can be reduced by command-line options but cannot exceed these ceilings.
The kernel configuration and watchdog are checked again at PDF/DjVu ingestion
and OCR call boundaries, before a parser can trigger implicit OCR.
An environment variable alone cannot admit OCR. Existing source rendering used by
the serving API is unchanged; this protection targets OCR/model jobs, not every
operation in the deployed service.

Exit codes: 137 for a memory-limit kill, 125 for a process-limit event, 124 for the
deadline, 130 for watchdog cancellation, otherwise the child status. The kernel
may kill PID 1 directly on OOM; then `container-state.json` is authoritative and
the worker may not have written `sandbox-result.json`. `launch.json` records exact
limits and image ID; `job.log` contains private command output. Completed,
failed and cancelled jobs are removed by their launcher.

If the **host launcher is forcibly killed**, the container deadline still stops
the workload. A stopped container can remain and keeps the concurrency slot
closed. Inspect only this named slot:

```sh
docker --context desktop-linux inspect cookbook-ocr-resource-slot --format '{{json .State}}'
```

After verifying it is stopped (`Running=false`, `Pid=0`), remove that stopped
container with `docker --context desktop-linux rm cookbook-ocr-resource-slot`.
No broad container/process cleanup is part of this workflow. On daemon failure,
the cgroup/VM bounds and container watchdog remain the protection; resume only
after inspecting the slot. This is resource containment for trusted jobs, not a
security boundary against a user deliberately altering Docker or the guard code.

## Verification

`scripts/verify_ocr_sandbox.py --output NEW_DIRECTORY` runs synthetic probes using
the local `cookbook-mcp:poc` image. Each uses a **64 MiB** cgroup, 12 PIDs and half a
CPU; the memory probe attempts at most 128 MiB inside that boundary. No book/model
is loaded. It verifies actual cgroup values, read-only code, absence of an IPv4
route, observed CPU throttling, memory-limit termination, PID-limit handling,
deadlines, normal/error parent exits with detached children, conflicting launches,
and a host-launcher SIGKILL. Heartbeat files must stop growing, the container PID
must be zero, and completed containers must disappear. The killed-launcher case
also verifies the deliberate stale-slot behavior before cleaning its own slot.

All eight cases passed on this Mac. Admission unit tests additionally verify that
native OCR fails before engine invocation or cache creation, that excessive or
unlimited kernel limits are refused, and that failed preflight does not launch a
payload. Historical private trial scripts and the old Paddle virtual environment
now fail before heavy imports/processing. Prior scripts are preserved as disabled
text artifacts; original books, OCR results, index and review decisions remain
untouched. Full verification records are outside Git under the private
`poc/resource-isolation-20260912` directory.

The full project suite also passed inside the protected image: 71 tests. Ruff
checks and formatting passed. The synthetic rotated-OCR test normalizes letter
case for Linux/macOS Tesseract differences while retaining exact quantity checks.

Primary references: [Docker hard memory, swap and CPU limits](https://docs.docker.com/engine/containers/resource_constraints/),
[cgroup v2 memory and PID controllers](https://docs.kernel.org/admin-guide/cgroup-v2.html),
[Docker Desktop VM resource settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/),
[Linux PID-namespace cleanup](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html).
