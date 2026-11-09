# Neon compatibility trial

On November 8, 2026, an isolated project on the owner's Free plan was created in `aws-us-west-2`, using PostgreSQL 17 and a fixed 0.25 CU endpoint. Existing projects were untouched. No production backend, provider credentials, or customer sessions were moved. API keys, database passwords, and raw trial files remain outside Git.

The direct connection verified the server certificate. Startup options were accepted. The server reported a writable primary, `synchronous_commit=on`, `fsync=off`, and `synchronous_standby_names=walproposer`, with Neon tenant and timeline settings present. This matches Neon's [documented parameter settings](https://neon.com/docs/reference/compatibility) and [quorum storage architecture](https://neon.com/docs/introduction/architecture-overview).

Explicit initialization succeeded. A separate runtime login connected with no administrative role attributes or role memberships. The generic PostgreSQL preflight refused `fsync=off`, as intended. The explicit Neon preflight passed against this database after adding the provider-specific policy.

Twelve assembled HTTP checks passed using three independent reader applications, synthetic text/image fixtures, synthetic JWTs, and a fake identity provider. They covered two-device sign-in, catalog delivery, a shared cookie on another worker, concurrent same-cookie renewal with one exchange, device logout preserving the other device, new sign-in, and all-device logout reaching another worker. No OCR, model inference, real OAuth exchange, or live library reads occurred.

## Hosted request timings

A separate comparison ran on the existing Fly machine in `sjc`, against R2 and the same Free Neon endpoint. Both sides used the candidate package from `edac1cd`, identical synthetic content, and fake provider tokens. The package and three Linux driver wheels were extracted into a temporary directory. The production image, installed environment, and secrets were unchanged.

The comparison alternated the authorities over five rounds. Each response's status and content were checked, including exact bytes from an EPUB range request. The following request times exclude browser rendering. Each row has five samples per authority. Values are milliseconds, shown as median and minimum to maximum.

| Journey | R2 | Neon |
| --- | ---: | ---: |
| Catalog | 1,893.52 [1,857.36, 2,333.71] | 160.79 [160.42, 227.71] |
| Passive session check | 324.24 [255.15, 380.29] | 24.84 [24.32, 24.97] |
| Text | 1,922.52 [1,825.64, 1,984.14] | 164.95 [164.68, 165.38] |
| Book view | 1,890.07 [1,857.81, 2,452.26] | 164.53 [163.54, 165.18] |
| Book information | 1,955.56 [1,831.45, 2,101.25] | 164.89 [163.74, 167.52] |
| Source range | 1,940.50 [1,838.70, 3,584.11] | 161.72 [160.82, 162.34] |
| Two simultaneous tabs, batch time | 4,148.64 [2,528.24, 4,547.06] | 231.10 [230.42, 252.48] |

All 80 comparison requests succeeded. A further 35 Neon requests covered five batches each of one, two, and four devices. All succeeded. Four-device batches had a median of 168.00 ms, ranging from 166.87 to 256.82 ms. These short bursts do not establish sustained throughput or a capacity ceiling.

Storage waits dominated catalog time. Median process CPU was 9.05 ms for R2 and 5.92 ms for Neon. Session storage stages accounted for a median 99.87% and 98.26% of request time respectively. Separate Neon probes measured a 22.42 ms median single-query round trip and a 68.11 ms median one-row transaction. Those probes were outside the HTTP samples. The result supports the small endpoint for the tested workload. It does not establish how many users the endpoint supports continuously.

The Fly machine had one CPU and low load during measurement. Available memory was about 213 MiB before measurement and 169 MiB afterward. The measurement process peaked at about 154 MiB RSS. The comparison used the existing exact-touch behavior on both sides. No authorization cache or relaxed idle interval was introduced.

Two setup attempts failed before measurement. The first encountered a Fly SSH authorization error. The second used `sslrootcert=system`, which failed certificate verification with the deployed libpq. The successful run explicitly used `/etc/ssl/certs/ca-certificates.crt`. No failed request was included in a latency sample. All synthetic R2 objects and PostgreSQL rows were removed and their absence verified. Raw outputs and private scripts remain outside Git.

The measured package predates the subsequent startup fix that rejects an empty database URL with the R2 backend. That fix does not change request handling for either valid backend configuration. The corrected release still requires its own Linux image validation before activation.

## Recovery checks

A committed synthetic write survived a compute restart. A later check kept an open connection across another restart. That connection was rejected afterward, its old backend was absent, and the existing reader pool reconnected. The reader continued to reject a session whose logout had committed before restart, and fresh sign-in worked.

A point-in-time branch restored the database to before a synthetic logout. The old key admitted that restored session, demonstrating the rollback hazard. A fresh session key rejected the old cookie, and fresh sign-in worked. The temporary branch and source probe rows were removed.

These exercises establish restart recovery and the restore procedure's key fence. They do not induce a physical network partition or prove arbitrary provider failover fencing. Production remains on R2. Real-provider acceptance, the remaining operational checks, and controlled cutover in the [deployment guide](reader-session-deployment.md) remain pending. No paid upgrade has occurred.
