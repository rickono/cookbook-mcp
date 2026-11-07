# Deploy the PostgreSQL session authority

Use this sequence after the local trial. The new backend is selectable, but deployment and the database purchase remain pending. The reviewed trial at `f2585c0` is the base. Production preparation is on `feat/reader-postgres-deploy` and requires its own review and Linux checks.

## Choose and verify the service

The reader currently runs in Fly's `sjc` region. Fly documents Managed Postgres availability there. The Basic plan is $38 per month plus database storage usage at $0.28 per GB per 30-day month. See [Fly's regions](https://docs.fly.io/reference/regions) and [Managed Postgres pricing](https://docs.fly.io/postgres). The owner's provider and budget choice is pending. No new paid resource has been created.

Before activation, verify the provider's acknowledged-write durability and old-primary fencing through its documentation, configuration, and a synthetic recovery exercise. Availability or automatic failover alone does not establish that a committed logout or refresh claim survives promotion. This gate is still open. Use a direct writable-primary endpoint, not a read replica or transaction-pooling endpoint. Require verified TLS for a public endpoint. Verify the encryption boundary for any private-network endpoint.

## Prepare the database explicitly

1. Create a dedicated database and a restricted login with direct grants. Keep its credentials separate from schema-administrator credentials. The runtime login must have no superuser, database creation, role creation, replication, row-security bypass, database object creation, or schema metadata mutation privileges. All direct and indirect role memberships are rejected, including `NOINHERIT` and grants with `SET FALSE`. An administrative membership could otherwise enable its own `SET ROLE` permission.
2. Save the administrator connection string in a private file with mode `0600`. Use the provider's direct primary endpoint.
3. Initialize the schema and grant the runtime login access to the session tables:

```sh
uv run --extra postgres python -m cookbook.session_database initialize --dsn-file /private/path/admin-dsn --runtime-role reader_runtime
```

4. Check with a separate private file containing the runtime connection string:

```sh
uv run --extra postgres python -m cookbook.session_database check --dsn-file /private/path/runtime-dsn
```

The initializer is atomic and repeatable for the supported version. Repeat initialization with the same provisioning login; existing version metadata must be a table it owns. It checks the runtime login before creating tables, resolves administrative built-ins in `pg_catalog`, and refuses existing unversioned session tables. It never adopts a trial database or upgrades a live schema implicitly. The schema version and source digest must match the deployment image. Runtime startup validates the primary, durable settings, logged tables, schema metadata, and privileges without changing schema. The runtime login must not own any session or metadata table. Fixed refusal reasons identify version, privilege, or durability problems. Credentials and driver exceptions are excluded from output.

## Prove the release before cutover

1. Run the disposable PostgreSQL HTTP and provisioning checks and the explicit serving regression selection. Require the Linux CI job and native `linux/amd64` image build to pass. The source-free Typesense startup smoke check stays enabled.
2. Review the production preparation changes. The earlier council approval covers the local-trial commit only.
3. Pin the release image digest. Record the current Fly machine configuration, attached volume, old image digest, and secret version privately. Preserve the current machine, volume, library credentials, reports, and personal metadata.
4. Run synthetic before/after journeys from the hosted region against both authorities with the same release image and content fixtures. Count failures separately. Require a worthwhile improvement in total request time and fresh authorization checks. Do not use the Mac-versus-relay ratio as production evidence.
5. Exercise renewal with the real identity provider and a disposable session, both logout scopes, concurrent requests, database disconnection, process restart, and the chosen provider's failover path. Never replay an ambiguous refresh exchange. Verify replacement-token cleanup after a request timeout.

The Mac image build reached the existing Typesense smoke check, then QEMU reported a segmentation fault while running the amd64 server. The native Linux CI image build is the required result. The smoke check has not been disabled.

## Fence the old authority and cut over

1. Inventory every running reader worker and verify the intended image and configuration. Stop external admission, drain active requests and provider exchanges, and prevent another writer from starting during the change. Record the short outage and require fresh reader sign-in after cutover.
2. Before admitting new sessions, attempt eligible provider cleanup for the old R2 sessions. Keep token material in private process memory and out of logs and Git. Include every allowlisted owner, even one with no existing record.
3. Fence old session writes with credential revocation or an equivalent verified restriction. A marker alone is insufficient while an old writer can still complete. Verify old credentials cannot write a synthetic object. Preserve a fail-closed marker for each legacy owner so an old R2 image cannot establish a parallel authority after rollback.
4. Keep OAuth correlation storage working. It currently uses the same private reader R2 credential, so fencing must include replacement access for the new worker. Do not revoke that credential without preparing its replacement. Bookmarks, reports, and the published library have separate storage and credentials.
5. Stage the new database URL, the explicit PostgreSQL backend, and a fresh encryption key atomically in the service secret manager. The settings are `READER_SESSION_BACKEND=postgres` and `READER_SESSION_DATABASE_URL`. Never put a URL or password in shell arguments, Git, issue bodies, or CI output. The R2 backend rejects a configured database URL rather than silently ignoring it.
6. Update the existing Fly machine to the pinned image and staged secret version, preserving its current volume and resource settings. Check database preflight and private readiness before restoring admission. Re-enable routing and require fresh sign-in. Do not copy live refresh tokens between authorities or serve both authorities concurrently.
7. Verify sign-in, catalog, search, text, original delivery, token renewal, device logout, all-device logout, and fresh checks from a second browser. Record release and image identifiers with source-safe timing summaries.

The exact credential-fencing and machine-update commands must be prepared against the selected service and the current live configuration before execution. Do not treat this sequence as an already completed cutover.

## Operate and recover

The PostgreSQL adapter retries due revocations every 60 seconds, independently of HTTP activity. Cleanup continues through the due backlog in batches of at most eight concurrent provider calls. Failed tokens stay durable and are attempted once per drain. Maintenance expires sessions under the owner lock, removes ended device rows, and clears completed retirement ciphertexts. Token-identity fences remain because deleting them could permit reuse of a consumed token. Sweep failures emit the fixed `session_maintenance_failed` event without exception text or identifiers.

The image smoke imports psycopg and its pool, loads bundled libpq, and reads the packaged schema before starting the source-free keyword server. Psycopg remains pinned at 3.3.8: the [official release notes](https://www.psycopg.org/psycopg3/docs/news.html) identify its fix for an SSL configuration regression introduced in 3.3.7. An arbitrary release-age cutoff is not used as a reason to restore that regression.

A claimed provider exchange continues after an HTTP timeout and settles or retires its returned token. If settlement and confirmation both fail during a database outage, the tracked task retains the returned credential and retries confirmation and reference-checked retirement without another provider exchange. It never revokes based on an unavailable confirmation read. Graceful shutdown waits for that reconciliation before closing the pool, so database recovery may be necessary before shutdown finishes. A forced process termination during the outage can still lose an unpersisted provider response; local admission stays fail closed, and provider cleanup remains best effort in that failure case.

Shutdown stops maintenance, drains exchanges, finishes the current cleanup batch, and closes the pool. Runtime connections have a five-second server-side idle-transaction timeout, releasing locks when a disconnected client leaves a transaction idle. New connections and authorization reads reject recovery-mode replicas. A confirmed database read is still required on every protected request.

Rollback must retain PostgreSQL authority. Do not redeploy an R2-only image or revive legacy objects. If the new authority is unavailable, fail closed. A database restore requires fresh out-of-database encryption/authority keys and fresh sign-in before restored rows can be served. A version row restored from the same backup is not a recovery fence. Test this procedure before relying on it.

Provider durability, hosted timing, real-provider acceptance, recovery tests, the credential fence, and the final release review remain activation gates. The next external dependency is the owner's provider and budget choice.
