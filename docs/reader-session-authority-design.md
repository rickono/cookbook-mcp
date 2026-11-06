# Reader session authority

Design recommendation for [Investigate session-storage overhead on protected reader requests](https://github.com/rickono/cookbook-mcp/issues/134), 2026-11-06. This replaces the earlier recommendation to retain the owner-object design. Research and prototypes only; no application change, infrastructure provisioning or deployment has occurred.

## Decision

Move reader-session authority to a shared PostgreSQL primary close to the hosted reader and independent of the owner's Mac. Store one row per device session. Separate activity timestamps from encrypted credentials. Read current authority on every protected request, and update only the requesting session's timestamp when qualifying activity is due. Keep the existing `SessionBook` lifecycle boundary.

Propose a **60-second durable activity interval**, with conservative expiry up to 60 seconds early and no added late-expiry grace. This is a proposed policy change, not an agreed value. Until a nonzero interval is approved, the implementation default remains zero. The same design works with interval zero if exact activity persistence is preferred. Its main gain, eliminating full-owner-object rewrites, does not depend on accepting a nonzero interval.

Recommend treating asset delivery and passive checks as non-activity. Foreground navigation, search submission, requested text continuations and personal/report actions qualify. Keep the seven-day idle duration, thirty-day absolute duration, fresh revocation checks, cookie/CSRF defenses and server-side token rules. Database placement and operational durability must be validated before production selection; no speedup is claimed.

## Why this shape

[Primary-source research](reader-session-practices-research.md) found no universal rule that sessions should never write during a request. Django normally saves modified sessions. Express supports small expiry touches and warns about whole-session resaves under concurrency. Spring Session tracks changed properties. Those patterns distinguish authorization, expiry bookkeeping and credential mutation.

Our current request path couples all three. Every active request normally performs a remote GET and a full encrypted owner-object PUT. Tabs, devices and images share one object version. The [measurements](reader-session-write-followup.md) establish meaningful remote wait, but a concurrent deployment confounds the later timing improvement. They do not establish a permanent latency floor or a winning SDK flag.

The R2 candidate safely reduces PUT frequency, but keeps one R2 GET on every protected request and occasional rewrites of all credentials. It retains cross-device contention and lifecycle writes against R2's per-key write limit. It is a bridge if deployment of a new authority is delayed, not the target architecture. Do not automatically implement both stages.

## Usage and module boundary

HTTP routes keep cookies, Origin/CSRF checks, response rendering and server-owned activity classification. They never handle SQL, versions, owner generations or refresh leases. `SessionBook` owns the pool, admission, activity policy, token validation, refresh coordination and revocation work.

```python
# Protected route, including passive assets.
auth = await sessions.authorize(cookie, Access.ACTIVE if qualifying else Access.PASSIVE)
if isinstance(auth, SignIn):
    return sign_in_response()
return await deliver(auth.subject, auth.csrf)

# Verified OAuth callback.
created = await sessions.begin(verified_identity, ProviderTokens.parse(provider_response))

# Validated Origin/CSRF and logout scope.
await sessions.end(auth, LogoutScope.ALL)
```

The public lifecycle stays `begin`, `authorize`, and `end`; construction/closure manages the database pool. `authorize` returns `Grant | SignIn`; unconfirmed required storage work raises the existing unavailable outcome. `Grant` exposes subject and CSRF, with a private handle for logout. No returned grant authorizes a later request.

`reader_sessions.py` remains the only session owner. `reader.py` selects the authority and classifies activity. The current verifier and provider adapter remain responsible for their identity protocols. Other library storage does not migrate with sessions. OAuth transaction storage can remain on its existing rare login/callback path in this change.

## Private data model

| State | Purpose |
| --- | --- |
| Owner row | Stable owner ID, authority epoch and monotonically increasing all-device revocation generation. |
| Session row | Cookie digest, owner/generation, immutable creation time, last persisted qualifying activity, CSRF, encrypted credentials, credential generation, ended status and refresh lease. |
| Refresh-token identity | Server-private keyed fingerprint or normalized reference, separate from randomized ciphertext. Supports shared-reference checks and retirement. |
| Revocation outbox | Encrypted provider cleanup work, written atomically with token retirement and attempted after commit. |

Each activity update changes only the timestamp in one session row. It neither serializes credentials nor rewrites siblings. Tokens and fingerprint keys remain outside browser state and logs; encryption keys remain outside the database. The database role can access only this private authority. Reading and publication credentials retain their existing boundaries.

## Admission and activity

A malformed cookie is rejected before storage. Otherwise a fresh primary statement joins the device row to its owner generation and epoch. It checks ended status, idle expiry and absolute expiry. No positive result cache or lagging read replica is allowed. A read-only admission linearizes at that coherent read; an already admitted request can finish across a later logout.

Verify the encrypted access token's signature, issuer, audience, owner and scope without holding database locks or a transaction open across a possible JWKS fetch. A later mutation pins the credential version that was verified and rechecks current state. Changed credentials require rereading and verification; they do not inherit the earlier result.

For a due activity update, take the owner `FOR SHARE`, then the session `FOR UPDATE`. Capture primary time after lock waits, recheck current owner/session/credential generations and both deadlines, then conditionally advance `seen`. Non-due activity and passive requests do not write. Use a consistent owner-first lock order for all mutations. `FOR KEY SHARE` is insufficient to block an ordinary generation update. No external provider call runs while locks are held.

A due touch must be confirmed before returning a grant. After an ambiguous commit, a fresh validation can recognize a sufficiently recent persisted stamp. Otherwise fail with 503 and do not run the protected handler. Do not acknowledge activity and flush it later from process memory. A failed due request is not guaranteed activity persistence; an actually committed qualifying request can count even if its response acknowledgement was lost.

Let `s` be persisted activity and `q` the latest admitted qualifying activity. With interval Δ, admission maintains `s >= q−Δ`, and `s` never represents invented future activity. Admission checks `now < min(s+7 days, created+30 days)`, without adding Δ as grace. Thus the timestamp can lag admitted activity by at most Δ, and idle expiry can be up to Δ early. Server-clock discipline and precision must be included in the bound. All required state is durable, so a process restart does not add lag. The finite policy model checks this rule under its stated assumptions.

The server owns activity classification. Timers, focus/visibility session checks, update polls and metadata/image fetches never become a new keepalive loop. Classification is accounting, not proof of human presence: possession of a cookie can manufacture qualifying requests. Absolute expiry is independent. Endpoint classification and the proposed interval both need explicit policy acceptance before release.

## Logout, refresh and token identity

Device logout locks the owner before ending the target session. All-device logout and sign-in take the owner `FOR UPDATE`; the generation change and session updates commit together. A concurrent sign-in is wholly before or after the logout. Touch and settlement never recreate an ended or old-generation row. Confirm the authoritative local revocation before reporting logout success; attempt provider cleanup after commit.

Retire a refresh token only when no live session still references it. Compare a keyed identity such as `HMAC-SHA256(k_fp, provider_context || token)`, not Fernet ciphertext. Equal tokens encrypt differently. Serialize the final-reference check and retirement with sign-in, and reject reintroduction of a retired token identity. Take the owner `FOR UPDATE` for these rare reference-retirement operations, including device logout, so two removals cannot each mistake the other's uncommitted reference as live and leave cleanup unqueued. A normalized token-reference protocol is an alternative only if its locking is proved. Outbox cleanup must recheck eligibility and preserve tokens still in use.

Refresh has three steps: durably claim a nonce and credential generation; exchange once outside the transaction; conditionally settle. Siblings wait and reread. A stale lease requires sign-in and never permits replaying a possibly consumed refresh token. Before settlement, recheck current epoch, owner/session generation, lease/credential version, and idle/absolute deadlines. Use the claim's qualifying activity time, rather than manufacturing activity after waiting on the provider. A rejected settlement never revives a session and queues eligible replacement-token cleanup.

A lost settlement acknowledgement is not permission to exchange again. Recognize an already committed result through its nonce/version and token identity. Revoke a returned token only after establishing that it is not authoritative for a live session. This remains a distributed protocol: a database transaction cannot atomically include Auth0.

## Durability, recovery and cutover

Use logged tables, `fsync=on`, durable commit acknowledgement and primary-only reads. Local WAL durability protects ordinary crash/restart on the same data directory. It does not promise survival of disk loss. An asynchronous replica must not be promoted as though it retained every acknowledged logout or refresh claim. Supported failover requires a documented synchronous durability and old-primary fencing contract. Until then, authority loss means unavailability and deliberate fresh sign-in recovery, not stale fallback.

Do not serve restored session snapshots as current authority. Before any restore/recovery, invalidate every restored session through a fresh out-of-store authority epoch/key and the corresponding session invalidation procedure. An epoch-highwater row restored from the same backup is not an independent fence. Provider cleanup remains best-effort when the only copy of a token was lost. Personal metadata/report backups remain separate and retain their existing requirements.

Prefer a brief, explicit cutover with one fresh sign-in:

1. Provision and verify the isolated authority, role and runtime credentials. Keep published-library access unchanged.
2. Drain or stop all old reader workers and outstanding renewals. Fence legacy session writes; a non-decryptable marker alone is insufficient if an old callback can still write. Revoke old authority credentials or otherwise prevent any old writer from succeeding.
3. Invalidate legacy sessions, attempt eligible provider revocation, start only the new authority and require fresh sign-in. No dual-authority fallback or live rotating-token copy is needed. Bookmarks and reports stay available through their separate stores.
4. Preserve the new authority through later application rollback. An emergency return to the old implementation requires another fenced all-session invalidation and fresh authority; never restore old R2 objects or simply remove fences to revive them.

The database service, credentials, upgrades, monitoring, durable storage and recovery runbook are additional operating work for a personal application. Provider choice and cost remain deployment decisions. A remote database can also be slow: require measured placement and end-to-end acceptance. Single-machine SQLite is a simpler alternative only if the current shared-replica contract is explicitly reduced. Fly volumes are not shared or automatically replicated. Generic Redis/AOF-everysec, Redis `WAIT`, and asynchronously read LiteFS replicas do not establish the required revocation durability.

## Synthesis and verification

The parent and independent judge selected the transactional candidate as the target. The R2 candidate scored better for migration simplicity and cost, but it cannot remove full-owner writes at interval zero. We grafted its conservative idle-bound proof, confirmed-due-touch rule, interval-zero comparator and operation-count/end-to-end gates. We corrected the transactional candidate's settlement predicates, randomized-token identity, lock scope and copy-based migration. We reject its restorable highwater fence and its claim that Serializable transaction retries inherently replay an external provider call. Read Committed plus explicit locks is the specified protocol, not the only possible correct isolation level.

Executed verification:

- `scripts/verify_session_activity_policy.py`: 7,776 finite transitions and 690 final states. It checks conservative idle bounds, fresh revocation, two devices, passive traffic, due-touch failure and restart assumptions. It demonstrates the stale-grant-cache and volatile-write-behind counterexamples, and randomized ciphertext versus stable token identity.
- `scripts/verify_session_authority.py` with PostgreSQL 17.6: ten synthetic protocol scenarios in a private temporary cluster. Actual locks exercise logout/sign-in ordering and demonstrate the `FOR KEY SHARE` pitfall. Checks also cover timestamp-only touches, touch rollback, competing claims, idempotent settlement, stale leases, exact boundaries and restart persistence. The cluster is stopped and removed afterward.
- `docs/prototypes/session_settlement_expiry.py`: real synthetic ASGI reproduction against the current R2 code. Refresh starts one second before the absolute limit, returns two seconds later, and the current endpoint returns 200 where the proposed strict settlement rule requires 401. It is marked as a known expected failure and is not application release coverage.

The SQL prototype deliberately omits JWT/provider integration, encrypted token references/outbox, migration, roles, managed failover and performance. Passing it is evidence for the demonstrated transaction rules, not a production implementation proof.

## Implementation and release gate

First implement the new private schema and `SessionBook` adapter behind the unchanged lifecycle interface, including the corrected settlement and shared-token-reference rules. Do not implement an R2 bridge automatically. Exercise both Δ=0 and the proposed Δ=60 with the actual HTTP and browser fixtures before choosing a release value.

Require two-worker behavioral races for logout against admission/touch/claim/settlement, concurrent sign-in, shared-token retirement, lost commit acknowledgements, stale leases without replay, expiry during provider wait, restore fences and legacy-worker rejection. Add endpoint operation counts proving passive assets/polls never write activity, within-window activity does not write, due activity updates only one timestamp, and background traffic cannot extend idle. Verify fail-closed storage errors without replaying personal/report mutations.

On one pinned deployed image, compare the same catalog, search, text/original and multi-tab journeys against the R2 baseline, with at least five alternating trials, warm/cold distinctions, failures counted separately and request-to-stage correlation. Include authority read/touch latency, pool contention, due-touch spikes, provider renewal and restart/recovery. No adoption or speedup claim precedes that evidence. The original session-check outlier remains unattributed.

## Sources

See [primary-source practices](reader-session-practices-research.md) for framework, OWASP, NIST, Auth0 and Redis evidence. Protocol references: [PostgreSQL row locks](https://www.postgresql.org/docs/18/explicit-locking.html), [isolation](https://www.postgresql.org/docs/18/transaction-iso.html), [durable commits](https://www.postgresql.org/docs/18/runtime-config-wal.html), [R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/), [R2 limits](https://developers.cloudflare.com/r2/platform/limits/), and [Fly volume boundaries](https://docs.fly.io/volumes/overview). Contract: [session decision](https://github.com/rickono/cookbook-mcp/issues/94). Historical rationale: [navigation-race fix](https://github.com/rickono/cookbook-mcp/pull/136).
