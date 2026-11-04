# Protected review sender

The sender is a synthetic verification implementation for
[Establish protected access for PDF comparison experiments](https://github.com/rickono/cookbook-mcp/issues/129).
Live dispatch fails closed in both the CLI and the worker. No environment variable,
configuration field, or command flag enables provider access.

## Isolation

`scripts/review_sender.py` uses the existing Docker preflight and atomic container
name `cookbook-ocr-resource-slot`. It leaves `scripts/ocr_sandbox.py` and OCR
admission unchanged. The sender has a separate PID-1 guard that fails OCR admission.
The VM, cgroup, swap, CPU, PID, file, tmpfs, and watchdog ceilings remain unchanged.

The sender image contains CPython, its standard library, required shared libraries,
TLS roots, and the sender modules. It has no cookbook package, source parser,
renderer, OCR engine, local model runtime, shell, or account home. Its launcher
mounts only a fresh private output directory, optional read-only synthetic
inputs, and optional private accounting state retained across jobs. It inherits
no host environment credentials or Docker socket.

Synthetic jobs use `--network none`. A TLS fixture runs on loopback inside the
same container. There is no provider egress, separate test service, or exception
to the offline OCR worker. The launcher removes only its successfully created
container ID. An occupied or stale slot blocks both launchers.

## Packet and transport admission

`protocol.py` checks an externally pinned manifest digest, source and candidate
identities, effective-correction identity, declared purpose, completeness, physical
page and canonical region scopes, asset hashes, image metadata, transforms,
configuration identity, token envelope, charge reservation, and serialized request
hash. Review and audit packets require declared complete evidence. Image bytes are
never decoded, rendered, rescaled, or repaired by the sender.

The provider endpoint constants specify exact HTTPS URLs. Requests use POST, TLS
verification, no redirects, and no automatic retry. Ambient proxy, endpoint, and
TLS-root overrides are rejected at admission. The executable transport currently
accepts only the loopback fixture URL. Its CA and credential are synthetic private
fixtures, not provider secrets.

The serialized request and received and decoded response bodies each have a
16 MiB bound. Streamed gzip decoding stops at the decoded bound. Truncated bodies,
unsupported encodings, redirects, HTTP failures, and invalid JSON fail the
transaction. Raw responses and receipt metadata occupy separate files.

An independent parent process kills the single HTTP child at an absolute deadline
of at most 240 seconds, including DNS, TLS, write, and read. Admission reserves
30 seconds of the remaining PID-1 watchdog time for cleanup. The container guard
terminates the entire PID namespace on deadline, cancellation, resource events,
or direct-child exit.

## Shared accounting

`ledger.py` stores integer microdollars and canonical edition/page/region counters
in private SQLite state. Initialization requires explicit prior spend, liabilities,
and attempts. Exclusive creation prevents initialization from resetting an
existing ledger. `BEGIN IMMEDIATE` and full synchronous commits serialize
reservations across processes.

Admission commits worst-case charges and all applicable attempts before the HTTP
child starts. Physical pages have six attempts; canonical regions have three.
Roles, providers, and packet names do not create new counters. An uncertain
semantic request remains blocked even with a new request ID. A failed admission
rolls back all counters together.

A successful HTTP response does not settle charges. Timeout, cancellation, and
crash liabilities remain reserved until verified reconciliation. Settlements are
idempotent; conflicting settlements fail. Charges above their reservation retain
the increased liability and block subsequent admission for investigation.

## Verification commands

Read [OCR resource isolation](ocr-resource-isolation.md) before covered workloads.
The following commands use the existing local image without downloading packages
or models:

```sh
python3 scripts/ocr_sandbox.py doctor
docker --context desktop-linux build --pull=false --network=none -f Dockerfile.review-sender -t cookbook-review-sender:synthetic .
python3 scripts/verify_review_sender.py --output /absolute/private/new-verification-directory
```

The verifier requires a fresh private directory and local OpenSSL for a temporary
fixture certificate. It runs protocol, TLS, credential, deadline, accounting, and
crash-recovery checks in the sender container. Restart probes remount the same
committed accounting database after cancellation and host-launcher SIGKILL.
Separate synthetic probes exercise
memory and PID limits, CPU throttling, detached-child termination, cancellation,
OCR slot contention, host-launcher SIGKILL, and stale-slot blocking. Their evidence
stays outside Git. The memory probe attempts at most 128 MiB inside a 64 MiB cgroup.

## Remaining live admission gates

This implementation does not establish provider compatibility or readiness:

- Actual provider projects, scoped credential delivery, model permissions,
  billing, effective data controls, and Jev request/image retention remain unverified.
- Exact reader ordering and checker configurations remain unfrozen. Provider
  schemas, refusals, image fidelity, image-token accounting, rate limits, and
  worst-case charges require verified adapters. Manifest declarations alone
  cannot prove those properties or evidence completeness.
- Source-first role isolation, evidence inclusion in the semantic provider
  payload, and crop/region reconciliation require the admitted preparation and
  adapter path. Hash validation alone does not establish them.
- The authoritative shared pilot ledger must be pinned and reconciled against
  prior charges, attempts, and outstanding liabilities. Synthetic zero balances
  do not establish available pilot funds.
- A later live launcher needs a reviewed separate network namespace and narrowly
  scoped read-only credential mounts. The current launcher admits no live mounts
  or external networking.
- Exact evidence enrollment, all-role cost, and owner workload belong to the
  cohort task. Concrete source processing, private transfer, paid probes, account
  changes, and publication require their applicable authorization.

The task remains open until its actual access and readiness packet is verified.
