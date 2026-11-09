# Neon compatibility trial

On November 8, 2026, an isolated project on the owner's Free plan was created in `aws-us-west-2`, using PostgreSQL 17 and a fixed 0.25 CU endpoint. Existing projects were untouched. No production backend, provider credentials, or customer sessions were moved. API keys, database passwords, and raw trial files remain outside Git.

The direct connection verified the server certificate. Startup options were accepted. The server reported a writable primary, `synchronous_commit=on`, `fsync=off`, and `synchronous_standby_names=walproposer`, with Neon tenant and timeline settings present. This matches Neon's [documented parameter settings](https://neon.com/docs/reference/compatibility) and [quorum storage architecture](https://neon.com/docs/introduction/architecture-overview).

Explicit initialization succeeded. A separate runtime login connected with no administrative role attributes or role memberships. The generic PostgreSQL preflight refused `fsync=off`, as intended. The explicit Neon preflight passed against this database after adding the provider-specific policy.

Twelve assembled HTTP checks passed using three independent reader applications, synthetic text/image fixtures, synthetic JWTs, and a fake identity provider. They covered two-device sign-in, catalog delivery, a shared cookie on another worker, concurrent same-cookie renewal with one exchange, device logout preserving the other device, new sign-in, and all-device logout reaching another worker. No OCR, model inference, real OAuth exchange, or live library reads occurred.

These results establish initial compatibility. They do not measure hosted capacity or latency, compare Neon with R2, exercise a network partition, or prove provider failover fencing. The client ran on the Mac, not Fly. Production activation remains pending the deployment guide's gates and review of the Neon-specific startup policy.
