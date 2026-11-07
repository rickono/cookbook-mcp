# Local PostgreSQL reader trial

The reader runs against PostgreSQL through its existing `begin`, `authorize`, and `end` session interface. The trial uses the actual HTTP handlers, signed JWT verification, encrypted credentials, and synthetic publication fixtures. It makes no provider or R2 calls.

The implementation is on `prototype/local-postgres-sessions`. Hosted configuration still selects the existing R2 authority. PostgreSQL requires the optional `postgres` dependency and an explicit `Reader(session_database=...)` argument. Application startup does not create or migrate tables.

## Reproduction command

The command uses installed PostgreSQL binaries and requires no database account or paid service:

```sh
uv run --extra postgres python scripts/try_postgres_reader.py --postgres-bin /Library/PostgreSQL/17/bin
```

The runner creates a private temporary cluster with a Unix socket and no TCP listener. It uses UTF-8, logged tables, `fsync=on`, and `synchronous_commit=on`. Each test starts with fresh tables. A server marker and socket check prevent the fixture from resetting an unrelated database. The runner stops PostgreSQL and removes the cluster after the tests finish.

## Observed behavior

The local trial passes 48 HTTP and database checks. The existing reader suite passes another 115 tests with its original session authority.

- Sign-in, catalog and text reading, continuation links, secure cookie attributes, CSRF, and both logout scopes work through the PostgreSQL adapter.
- A passive session check leaves the session rows unchanged. An active request changes only the requesting device's `seen` column. Credentials and sibling sessions retain their stored values. Guarded storage methods reject any attempted `reader/owners/` access during the request test.
- Two independent reader instances handle concurrent activity for the same cookie and for different devices. A fresh primary read checks every protected request. There is no positive authorization cache.
- Concurrent sign-in and all-device logout respect the owner generation. An activity request paused before its write cannot restore a session after logout.
- Concurrent renewal exchanges the refresh token once, including when distinct device rows share that token. A durable claim belongs to the keyed token identity. Successful renewal updates every live reference's credentials while preserving each device's creation, CSRF, and activity. A confirmed nonrotating renewal permits a future exchange after the new access token expires. An ambiguous exchange permanently fences the identity against sibling reuse and sign-in. Stale leases and provider timeouts require sign-in without replaying the exchange.
- Settlement rechecks idle expiry, absolute expiry, and logout. A provider response that crosses either deadline does not grant access. Activity uses the claim timestamp rather than time spent waiting for the provider.
- A lost settlement acknowledgement can recognize the committed result without another exchange. An unconfirmed touch returns 503 without delivering catalog content. A lock timeout also returns a redacted 503.
- Equal refresh tokens produce the same keyed identity despite different ciphertexts. The last device removal queues one revocation. A provider failure leaves durable retry work. A subsequent lifecycle operation retries eligible work. A retired credential cannot create another session.
- Application restart retains sessions. An immediate PostgreSQL restart also retains the live session and its sibling's confirmed logout. A fresh encryption key selects a different authority epoch and cannot admit the previous epoch's cookies.

The activity interval remains zero, and route activity classification remains unchanged. This trial does not adopt the proposed 60-second interval or passive image delivery.

## Implementation boundaries

`reader_sessions_postgres.py` owns admission, transactions, refresh coordination, encrypted credentials, and revocation work. Mutations lock the owner before the device row. Ordinary activity takes a shared owner lock, so different devices do not serialize behind one owner update. Logout and token retirement take an exclusive owner lock.

JWT verification and provider requests run outside SQL transactions. The threaded connection pool closes during the hosted app's shutdown. Read Committed isolation is explicit. Pool transactions follow [Psycopg's transaction contexts](https://www.psycopg.org/psycopg3/docs/advanced/pool.html).

`reader_session_schema.sql` is an explicit trial schema. OAuth correlation records remain in the existing store. Bookmarks, reports, and published content keep their existing storage boundaries.

## Limits of the result

The passing tests establish the demonstrated local behavior. They do not measure a hosted speedup. No latency comparison was run, and the test host had other active workloads. Synthetic publication data and a local socket cannot represent a remote database's network latency or placement.

Production selection still requires a pinned hosted comparison, real provider acceptance, a restricted database role, schema migration and retention procedures, managed failover guarantees, and the fenced cutover described in the [authority design](reader-session-authority-design.md). Cleanup retries currently run during lifecycle operations. A continuously running cleanup worker is not part of this local trial.

Recovery here covers restart on the same data directory. Disk loss, database restore, promotion, and an old primary that continues serving require separate fencing and recovery tests. Deployment and session migration have not occurred.
