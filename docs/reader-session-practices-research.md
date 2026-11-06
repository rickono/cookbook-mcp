# Session storage: primary-source findings

Research date: **2026-11-06**. All linked official documentation/source was accessed on that date. Rolling pages generally provide no publication date; versions are identified below. NIST SP 800-63B-4 was published July 2025. Recommendations and derived bounds below are design judgments, not claims that a standard mandates this architecture.

## Contract versus design discretion

The supplied brief and [owner policy, issue 94](https://github.com/rickono/cookbook-mcp/issues/94) establish opaque Secure/HttpOnly host-only cookies, encrypted server-side tokens, seven-day inactivity, thirty-day absolute lifetime, durable multi-device sessions, checks on every protected request, device/all-device revocation, one refresh exchange, and no stale positive authorization cache. Full owner-object rewrites and per-image durable timestamps are implementation choices. A nonzero activity-coalescing interval, including 60 seconds, needs explicit policy agreement; it is not already accepted.

## What established systems actually do

**Per-request persistence exists; full remote owner-object replacement is not a general recommendation.** These frameworks expose materially different policies:

- [Django 5.2, “When sessions are saved”](https://docs.djangoproject.com/en/5.2/topics/http/sessions/#when-sessions-are-saved): saves modified sessions by default; `SESSION_SAVE_EVERY_REQUEST=True` explicitly enables every-request saves. Reading a session does not itself extend expiry; expiration follows modification. Thus Django's default does not implement exact request-based sliding inactivity automatically. Its `cached_db` backend writes through to the database, whereas cache-only sessions can disappear through eviction/restart. Framework caching is not evidence that stale authorization meets this application's contract.
- [Express session 1.19.0, `resave`/`rolling`](https://expressjs.com/en/resources/middleware/session/#resave): typically recommends `resave:false` when the store supports `touch`, warning that full resaves can overwrite concurrent changes. `rolling` renews the cookie; that is distinct from storage persistence. [connect-redis README](https://github.com/tj/connect-redis#disabletouch) describes refreshing TTL for unchanged sessions; its [implementation, `touch`, lines 71–79](https://github.com/tj/connect-redis/blob/master/index.ts#L71-L79) issues `EXPIRE`, whereas `set` serializes the session. This commonly still means one small remote write per request, not zero writes.
- [Spring Session Redis API 4.0.0, optimized writes/expiration](https://docs.spring.io/spring-session/docs/current/api/org/springframework/session/data/redis/RedisIndexedSessionRepository.html): tracks changed properties and writes those, rather than every attribute. It checks logical expiry even though cleanup TTL is later. [SaveMode](https://docs.spring.io/spring-session/docs/current/api/org/springframework/session/SaveMode.html) distinguishes changed attributes from always saving everything; [FlushMode](https://docs.spring.io/spring-session/docs/current/api/org/springframework/session/FlushMode.html) distinguishes immediate writes from saving around response commit. Neither setting by itself proves cross-request throttling or no last-access writes.

Inference: authorization reads, idle touches, token rotation, and application-state mutations should have separate storage operations. None of these sources endorses rewriting every device's encrypted token state for each image request.

## Idle semantics and background traffic

[OWASP Session Management, automatic expiration](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html#automatic-session-expiration) requires server-enforced idle and absolute expiration, describing inactivity since the last HTTP request. It also explains that an attacker can manufacture activity. Its example timeouts are much shorter than seven/thirty days; those owner choices should not be presented as OWASP defaults.

[NIST SP 800-63B-4 §5.1.2–5.2](https://pages.nist.gov/800-63-4/sp800-63b.html#session) separates subscriber presence from token possession: access/refresh tokens can outlive the authentication session. Its assurance-level reauthentication requirements are context-specific, not an automatic mandate or compliance claim for this reader.

Recommendation: authorize passive polls and protected assets, but define which events extend inactivity separately. A minute timer, visibility/focus check, prefetch, or token renewal is not reliable evidence of human activity. Consider foreground navigation/search and explicit reading interaction as qualifying events; count images caused by those actions only under a documented policy. Visibility alone cannot prove presence; client events remain forgeable. Long silent reading deserves a deliberate UX decision. Never let an unattended background tab renew indefinitely; absolute expiry remains fixed.

For bounded touches, let `s` be authoritative persisted activity, `I=7 days`, and `Δ` the proposed interval. At server-authoritative time `t`, first reject expired/revoked sessions. For qualifying activity, atomically advance `s` monotonically only when `t-s >= Δ`, conditioning on the current session generation and revocation state. Concurrent workers use shared persisted state, not process-local debounce. Never upsert a missing session during touch.

Derived bounds, assuming successful due touches, a consistent clock, and no positive local override:

- Checking `t < s+I` can expire a session up to `Δ` early relative to its last qualifying activity, but never late. Restart preserves that same bound. A due touch that fails must not be silently counted as durable activity; reject/retry safely or expose the failure.
- Checking `t < s+I+Δ` avoids that particular early cutoff but permits up to `Δ` extra inactivity. Cap either rule by the original absolute deadline. This grace is a policy change.
- Exact idle semantics require a durable small touch for every qualifying request, or another equally durable authoritative activity mechanism. Volatile deferred flushes have no fixed bound across repeated crashes/outages unless the design supplies one.

Keep logical authorization expiry separate from cleanup TTL. Include timestamp rounding and clock error in the stated bound.

## Revocation and refresh

Recommendation: read current session validity and owner revocation generation from one coherent authority on every protected request. A positive cache with TTL `C` allows stale access for approximately `C`; invalidation messages alone can be lost or delayed. Negative caching can deny access unnecessarily but does not authorize a revoked session. JWT signature validity alone cannot establish current session validity.

Commit device revocation or the all-device generation increment before reporting logout success; perform provider cleanup afterward. Serialize creation against the owner generation and define which side of logout a concurrent sign-in belongs to. Touch/refresh settlement must condition on both session and owner generations. Requests authorized before logout can already be in flight; define the authorization linearization point rather than promising recall of delivered data.

[Auth0 rotation](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation#automatic-reuse-detection) invalidates a reused token's family. Its [configuration rules](https://auth0.com/docs/secure/tokens/refresh-tokens/configure-refresh-token-rotation#configure-in-the-dashboard) allow overlap only for the immediately preceding generation. By comparison, [Supabase sessions](https://supabase.com/docs/guides/auth/sessions#what-is-refresh-token-reuse-detection-and-what-does-it-protect-from) document a default ten-second reuse interval and a parent-token recovery exception. These are provider-specific rules, not interchangeable idempotency guarantees.

Recommendation: durably claim refresh with nonce/generation, exchange once outside the transaction, then conditionally settle encrypted replacement tokens. A lease fences storage commits, not provider calls: expiry must not permit blindly repeating an ambiguous exchange. Require reauthentication when recovery cannot prove safety. After an ambiguous settlement, reread to determine whether it committed; do not revoke a replacement token that may now be authoritative. Local transactions cannot atomically commit an external provider exchange.

## Durable authority alternatives

**Per-device records plus bounded activity:** smaller encrypted records remove cross-device full-object contention. Retain a durable owner generation for all-device revocation. Cross-record reads must form a coherent authorization decision; ordinary independent GETs do not automatically supply that. This option reduces write volume but retains remote read latency and multi-record race complexity.

**Shared transactional authority:** separate owner generation, device session, activity, and token-generation state behind the existing SessionBook boundary. Support fresh validation plus conditional small updates. Choose a deployment only after specifying transaction isolation, durable acknowledgment, failover behavior, and operational ownership.

[PostgreSQL 18 isolation](https://www.postgresql.org/docs/18/transaction-iso.html) supplies snapshots/locking and serializable transactions with retry requirements. [WAL settings](https://www.postgresql.org/docs/18/runtime-config-wal.html#GUC-SYNCHRONOUS-COMMIT) distinguish local durable commit, synchronous replication, and unsafe-for-this-contract acknowledged-write loss with asynchronous commit. Read the authority, not a lagging replica; local durability alone does not guarantee lossless failover.

[Redis transactions](https://redis.io/docs/latest/develop/using-commands/transactions/) provide isolated execution and WATCH-based CAS, but no rollback of runtime command errors. [Persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) distinguishes snapshots from AOF: every-second fsync can lose recent writes. [Replication](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/) explicitly says WAIT does not create strong consistency and acknowledged writes can disappear on failover. Losing revocation or refresh claims is a security failure, not merely lost activity. “Redis” alone is therefore insufficient as a durability specification; an ephemeral Redis cache is not the durable authority.

For either option, encrypt tokens with keys outside the store, restrict backups, and prevent restored backups from resurrecting revoked sessions (for example, invalidate pre-restore sessions through an independently preserved generation/key boundary). Cut over with old workers drained or fenced; dual authorities without ordered revocation/refresh ownership are unsafe. Validate races, restart/failure recovery, expiry bounds, and migration before provider selection or production changes.
