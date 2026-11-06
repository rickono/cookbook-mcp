# Reader session storage alternatives

Research for [Investigate session-storage overhead on protected reader requests](https://github.com/rickono/cookbook-mcp/issues/134), reviewed on 2026-11-05 against main at `9031857c162b070ad4326d5208f33a87e430bf0c`. See the [combined attribution report](reader-session-storage-research.md) for measurements and reproduction. No production requests, deployment, tracker edits, OCR, or performance experiments were performed for this document.

## Recommendation

Keep the shared encrypted owner record and the current SessionBook lifecycle. Main already removes common-path passive writes and search's serial CSRF preflight. Do not count either as a new optimization. The smallest remaining candidate is to serialize overlapping checks within one browser document, retaining a fresh follow-up when a new trigger arrives during an outstanding check. Prove that this reduces requests in the target workload before implementing it. Do not introduce a server authorization cache or batch activity timestamps. This recommendation follows the current lifecycle's concurrency rules and the unguarded browser triggers, rather than a measured speedup. [S1, S2, S3, S4]

## The old baseline differs from main

The issue's observations describe an inspected deployed `Reader.authenticate` path. They do not establish the behavior or deployment status of today's source. In the historical reproduction revision `3ea1662`, passive session and publication checks skip changing `seen`, but still reach a conditional PUT even when the session has not changed. Retry compares the complete current session with the older snapshot, so another activity stamp can invalidate that comparison. [S5]

Main includes the issue 131 redesign. `reader.py` delegates session decisions to `SessionBook`, and classifies `/reader/session`, `/reader/updates`, and `/reader/logout` as passive. A live, unexpired passive authorization returns without a PUT. Expiry removal, renewal claims and settlement, login, and logout still write. An active authorization normally persists its proposed `seen`; a newer committed stamp can satisfy an older proposal without another write. This is an existing correctness improvement, not a timestamp coalescing window. [S1, S2]

Search also embeds the authorized page's CSRF value and posts directly. Its session GET is now limited to recovery from the specific `csrf_denied` response, with one read-only retry. The independent browser monitor remains. Removing the earlier search preflight and removing passive PUTs are separate changes and cannot each be projected as savings against main again. [S4]

The live outlier in issue 134 remains unattributed by this source review. Historical timing samples cannot price the new path or distinguish provider renewal, a cold key fetch, remote storage delay, and contention. Main's diagnostic stages make those distinctions observable, but no live trace was collected here. [S6]

## Requirements that constrain an optimization

The agreed contract requires server-side tokens, an opaque cookie, shared durable sessions across tabs and restarts, seven-day inactivity expiry, thirty-day absolute expiry, device and all-device logout, and current authorization for every protected request. The client clears delivered content when it learns of expiry or revocation. Already delivered pixels cannot be recalled. [S7]

In the current source, `_ended` rejects equality at either boundary. Each authorization decision checks the current clock against stored `seen` and `created`. Activity proposals remain fixed within a CAS pass; conflict retries reread the owner and recheck expiry using current time. A renewal wait starts another pass. "Exact expiry" here means preserving these admission rules without a new rounding or grace window. It does not promise cancellation of every already admitted response at the expiry instant. The design explicitly allows an in-flight authorization to finish across logout, while subsequent requests observe removal. [S1, S2]

Logout removes the device entry or all entries in a fresh owner record, preserves competing changes through CAS, and attempts revocation of refresh tokens actually removed. Renewal first commits a nonce-bearing lease, exchanges once, and settles only while entitled to that session. Siblings wait and reread. A cancelled exchange leaves a fail-closed lease, and a stale lease requires sign-in. Ambiguous writes must not be treated as confirmed success or blindly replayed. These rules apply across reader processes, not only tabs in one process. [S1, S2]

Auth0 documents that rotation invalidates the exchanged refresh token and reuse detection can invalidate its token family. A process-local lock, browser coordination, or retry after an uncertain provider exchange cannot replace the durable lease. [P1]

## Bounded alternatives

The operation counts below describe a normal valid-token request for a single configured owner, without conflicts or expiry. They are source-derived, not measured latency estimates. Multiple allowed owners may require multiple owner reads because authorization scans the allowlist. [S1]

| Alternative | Operation that changes | Preserves the contract? | Judgment |
| --- | --- | --- | --- |
| Retain main's SessionBook | Passive checks use one owner read and no PUT. Advancing active requests normally use one read and one PUT. | Yes, with current bounded failures and lifecycle behavior. | Baseline for the probe. |
| Serialize same-document monitor checks | Avoid concurrent duplicate session requests; retain a fresh queued follow-up. | Yes, with the restrictions below. | Smallest candidate. |
| Delay or round activity stamps | Reduces active PUT frequency. | No, without another durable activity record. | Reject under exact idle expiry. |
| Cache a session or authorization grant | Avoids authoritative reads during cache lifetime. | No, for positive cache reuse after revocation. | Reject ordinary TTL caching. |
| Split per-device records or activity objects | Reduces unrelated device contention or object size. | Possible only with a new consistency and migration design. | Defer until contention evidence warrants it. |
| Replace object CAS with a transactional authority | Can combine an active admission and timestamp update in one database operation. | Possible with durable lifecycle transactions and renewal leases. | Larger infrastructure change; defer. |

### Serialize browser checks without remembering authorization

`reader_session.js` starts checks from a minute timer, `pageshow`, `focus`, and visible `visibilitychange`. Its `busy` flag covers logout only. Two triggers can therefore create concurrent session GETs in the same document. [S3]

A bounded design keeps one outstanding monitor fetch and one pending-follow-up flag. Triggers during that fetch set the flag. After completion, a queued check makes a fresh request. A burst during the first request needs at most one follow-up for that burst. Sustained new triggers can require further serialized checks; a fixed total cap would discard later revalidation requests.

Keep the timer and all current event triggers. Do not turn a prior 200 into reusable authorization, introduce a successful-result TTL, skip checks because the document was recently active, or let one tab's 200 authorize another. The fresh follow-up matters because logout may commit after the outstanding request's authorization read but before a later focus event. Reusing its success for that event would conceal that ordering. A 401 must still dispatch `reader-expired`, clear protected DOM and drafts, and navigate to sign-in. Network errors and 503 responses must not become a fabricated success. Preserve logout's separate busy state and explicit retry behavior. [S3, S7]

All protected content requests retain their own server authorization. Independent tabs still check independently. Server rotation, both logout scopes, exact idle and absolute admission, and durable restart behavior remain in SessionBook. The browser only reduces duplicate monitor work. A new document starts with no coordination state. This candidate does not reduce the remote read needed by an ordinary navigation, guarantee lower navigation latency, or solve long individual session requests. [S1, S2, S3]

### Defer, round, or batch activity timestamps

Suppose the last durable `seen` is `s`, and activity at `s + d` is acknowledged without persisting its timestamp. After restart, the store cannot distinguish that history from one with no activity. Expiring at `s + IDLE` ends the active history early. Assuming an extra window permits access too late for the inactive history. Writing a future stamp permits late expiry; rounding down permits early expiry. A timer that flushes later also loses the distinction on a crash.

Thus exact idle accounting requires a durable observation of each newly advancing accepted timestamp, or an already committed later timestamp. An append-only activity log moves the write rather than eliminating it, and adds reconstruction and logout ordering work. Absolute expiry still needs the original immutable creation time. Main already implements the safe "later committed stamp satisfies an older proposal" case. The issue 131 design explicitly rejects a sixty-second coalescing window and deferred stamps. [S1, S2]

### Cache authorization or coordinate only within a process

A positive cache entry can outlive device removal, all-device removal, token replacement, or a renewal lease. Rechecking its idle and absolute deadlines locally does not detect those changes. A signed or encrypted cookie with expiry has the same revocation problem unless every request also consults current authority. A TTL merely bounds stale authorization; it does not preserve the present promise. [S1, S7]

A conditional GET or HEAD that checks the current object version still needs a remote round trip. It may reduce transferred bytes or decryption work, but it does not remove the network check. A cached record cannot safely drive a later unconditional write. The storage adapter's `If-Match` protects an individual object version, not a cached grant. [S8, P2]

Process-local locks can reduce local competition, but another replica can still commit logout or renewal. They cannot replace CAS. Distributed invalidation would require a durable, ordered protocol with restart recovery, admission blocking during uncertain state, and acknowledgement from every serving replica before logout succeeds. That is a new authorization service, not a small cache patch. The current encrypted record deliberately avoids this dependency. [S1, S2]

Main already memoizes token verification by raw access token within one `_authorize` call, including its conflict and wait passes. A new cross-request verification-result cache must separately preserve time-dependent claim checks, allowed identity and scope, key policy, and replacement tokens. It cannot replace the owner read. Keep this out of the smallest change until stage attribution demonstrates a material cost. The verifier currently validates claims through `jwt.decode` and uses `PyJWKClient` for key selection. This review makes no claim about measured cold-worker key behavior. [S1, S9]

### Split activity, credentials, or devices into separate objects

Per-device objects can prevent one device's activity from conflicting with another's. They still require exact durable activity writes, and same-cookie tabs still compete. Splitting activity from credentials adds reads unless another authority combines them. Neither schema alone removes the normal authentication round trip. [S1, S2]

A safe replacement needs device removal that cannot be undone by a late activity or renewal writer. All-device logout needs an owner generation or equivalent shared authority checked at admission, with an ordering proof covering generation changes, login, renewal settlement, and session creation. Restarts must reload that authority. Restored stale records must never revive revoked sessions. Provider revocation still needs the tokens actually removed or an explicit durable cleanup obligation.

The current CAS seam is per object. An owner epoch plus device and activity objects cannot be treated as an atomic snapshot merely because each write is conditional. A design must also preserve the 100-session cap, creation times, token confidentiality, and ambiguous-write handling. Mixed old and new replicas need an explicit cutover or compatible migration: an old replica can neither enforce a new epoch nor find a session stored only in the new schema. The issue 131 synthesis rejected a three-object migration for precisely this additional consistency burden. [S1, S2, S8, P2]

### Use a transactional session authority

A shared transactional store could atomically admit an active request and advance `seen`, reducing the client-side read-then-PUT sequence. Activity remains a durable write. Passive requests still consult current authority. Owner-row locking or another proved serialization rule must cover login, the session cap, all-device logout, device updates, and renewal claims.

PostgreSQL documents that concurrent updates wait and re-evaluate their predicates against updated rows. It also warns that Read Committed commands can observe inconsistent combinations across rows. This supports a candidate atomic admission/update, not a proof that an arbitrary multi-row session design is correct. [P3]

Provider exchange remains outside a database transaction and still needs a durable lease plus settlement rules. Restarts, failover, uncertain commit acknowledgement, scoped credentials, backups, and migration become operational requirements. A separate Redis or SQL service is therefore a larger investigation. There is no evidence here that it is faster in this deployment, or that moving the same remote wait to another service is worthwhile.

## Checks and measurement needed before a change

The current synthetic suites contain exact passive idle-boundary checks, advancing activity races, passive/activity ordering, bounded CAS failures, shared-store readers, single-exchange renewal, stale and cancelled leases, logout during renewal, ambiguous settlement and logout, both logout scopes, and restart persistence. They are evidence of intended behavior and regression targets. They were inspected, not rerun for this document. [S10]

For the browser candidate, add event-driven tests that hold a session response while firing focus, visibility, pageshow, and timer triggers. Assert one outstanding fetch and one queued follow-up per overlapping burst. Deliver an old 200 after simulated logout and require the queued fresh 401 to clear the page. Check network rejection, 503, expiry, and logout-busy handling without replaying mutations. Existing browser tests cover logout and expiry but do not assert coalescing of those event triggers. [S3, S11]

A full-path probe should use the real HTTP boundary, synthetic identities, an advancing clock, and two reader instances sharing a synthetic store. Count reads, PUTs, conflicts, token checks, provider exchanges, and renewal polls separately for active, passive, and overlapping workloads. Include storage faults and exact idle and absolute boundaries. Record diagnostics' request IDs and revision with category and stage for failures. Stage durations include store calls and associated processing; they are not CPU-only or network-only profiles, and nested stages must not be summed as disjoint costs. [S1, S6]

End-to-end acceptance needs a separately authorized comparison against an identified deployed revision, with successful and failed requests reported separately. Compare the same navigation and monitor-trigger workload, retain outliers with request IDs, and price only operations actually removed. Source inspection and synthetic delay injection cannot establish hosted storage latency, real refresh behavior, production tail latency, or the cause of the earlier outlier. No operational authorization is implied by this recommendation. [S6, S7]

## Sources

Repository links are pinned to the reviewed main revision, except the explicitly historical baseline.

- S1: [SessionBook lifecycle, expiry, CAS, renewal, and logout](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/reader_sessions.py#L118-L385).
- S2: [Issue 131 session design and synthesis decisions](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/docs/reader-session-design.md).
- S3: [Browser check triggers and logout state](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/reader_session.js#L1-L61).
- S4: [Search bootstrap from its existing grant](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/reader.py#L416-L434) and [specific CSRF recovery](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/reader_search.js#L18-L59).
- S5: [Historical authenticate and unconditional write at 3ea1662](https://github.com/rickono/cookbook-mcp/blob/3ea1662/src/cookbook/reader.py#L220-L313).
- S6: [Issue 134 evidence and limits](https://github.com/rickono/cookbook-mcp/issues/134) and [closed diagnostic categories, stages, and timing aggregation](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/reader_diagnostics.py#L29-L245).
- S7: [Agreed session and privacy contract](https://github.com/rickono/cookbook-mcp/issues/94#issuecomment-6565744519) and [documented current serving behavior and limits](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/docs/hosted-reader.md#L109-L146).
- S8: [Local and S3 conditional-write seams](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/storage.py#L146-L250).
- S9: [Token verifier](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/server.py#L29-L79).
- S10: [Session race and fault tests](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/tests/test_reader_session_races.py) and [HTTP restart, logout, expiry, and renewal tests](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/tests/test_reader_http.py).
- S11: [Browser logout and expiry tests](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/tests/reader_session.test.mjs).
- P1: [Auth0 refresh-token rotation and automatic reuse detection](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation), consulted 2026-11-05.
- P2: [Amazon S3 conditional-write semantics](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html), consulted 2026-11-05. This describes the protocol mechanism, not a verification of the hosted R2 service.
- P3: [PostgreSQL 18 transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED), consulted 2026-11-05. This is a candidate design input, not a selected dependency.
