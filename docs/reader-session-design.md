# Reader session contention and failure diagnosis

## Problem

[Diagnose and fix intermittent HTTP 503 responses in the hosted reader](https://github.com/rickono/cookbook-mcp/issues/131) records six unexplained live navigation failures. Synthetic requests against `3ea1662` reproduce a separate mechanism: two same-cookie activity writes conflict because the retry compares the winner's new `seen` with an older snapshot. A frozen clock masks this failure. Failure bodies and logs currently cannot distinguish every cause.

## Usage

The reader asks one session owner to authorize, create, or end a session. HTTP code owns cookies, CSRF validation, redirects, and rendering. It never handles session versions or refresh-token rotation.

```python
outcome = await sessions.authorize(cookie, Access.ACTIVE)
if isinstance(outcome, SignIn):
    return expired()
return await deliver(outcome.subject, outcome.csrf)

created = await sessions.begin(verified, ProviderTokens.parse(tokens))
await sessions.end(grant, LogoutScope.DEVICE)
```

## Shape

Keep the encrypted owner record and its existing key. `reader_sessions.py` owns every operation on `reader/owners/*`. It exposes `SessionBook.authorize`, `begin`, and `end`. `Grant` exposes subject and CSRF only, with a private handle for ending its session. Token fields have no printable representation. `reader.py` continues owning encrypted login transactions.

```python
class SessionBook:
    async def authorize(self, cookie: str | None, access: Access) -> Grant | SignIn:
        raise NotImplementedError

    async def begin(self, verified, tokens: ProviderTokens) -> NewSession | SessionLimit:
        raise NotImplementedError

    async def end(self, grant: Grant, scope: LogoutScope) -> None:
        raise NotImplementedError
```

All mutations decide against a fresh record inside one bounded CAS loop. Definite precondition failures permit rereading and deciding again. Ambiguous writes propagate failure. No retry repeats a provider exchange or a personal mutation. Preserve other devices, and never recreate a removed session.

Activity has a fixed proposed timestamp per decision pass. Retry expiry checks use current time; a renewal poll starts a new pass. An activity update changes only `seen`, monotonically, when the fresh authorization-critical fields still permit admission. A newer committed stamp already satisfies an older proposal. No coalescing window or deferred timestamp is introduced. Three unsuccessful competing writes still produce a categorized failure, preserving exact idle accounting and truthful storage failures.

Passive session and publication checks perform no common-path write. Logout also does not advance activity. Authorization linearizes at the session read; an already in-flight read may finish while logout commits. Subsequent requests see removal. Keep the seven-day idle and thirty-day absolute limits, 100-session cap, and existing verification requirements.

A renewal commits `renewing` with an optional random `lease` nonce before calling the provider once. A fresh lease held by another request makes a sibling wait and reread within its deadline. A stale lease ends the session. Preserve the five-second provider timeout and ten-second lease. Do not shield or detach renewal. Cancellation leaves a fail-closed lease; no request replays the refresh token. Old records with `renewing` and no nonce remain valid held leases.

Settlement order matters: absent entry means sign-in and revoke the new token; a lease-free entry already containing the new access token means our settlement committed and must not revoke that token; a different lease means sign-in; our lease permits settlement. Deletion and logout use fresh records and revoke the tokens actually removed. If a removal committed but surfaced a definite conflict, retain the removed-token set and revoke only tokens no longer stored. An unconfirmed logout never reports success.

`reader_diagnostics.py` is a standard-library leaf. Context-local traces collect bounded stage durations, attempts, conflicts, a random request ID, and a validated deployment revision. Stages distinguish session read/write, token verification, renewal claim/provider/wait/settlement, personal state, location resolution, content delivery, search, reports, and callback work. A fixed category set distinguishes contention, renewal pending, outer deadline, session storage, identity, personal state, library, content, reports, and internal failure. Use the outer timeout's `expired()` to distinguish it from inner timeouts. Preserve the innermost failed stage after context unwinding.

Every reader response gets a request ID. Every 503 gets category and responsible stage headers, including route-returned 503s. Endpoint-rendered HTML and JSON also retain these fields in the body. Preserve existing personal-state response semantics and callback cleanup. Emit a closed JSON record without cookies, digests, subjects, CSRF, tokens, queries, locations, content, raw exception messages, or arbitrary environment strings. Record successful requests too, so overlapping winners remain visible. Bound the number of stage records and aggregate repeated polls.

Instrument dispatch at existing call sites. Keep existing route registration; do not add a route framework or a second session writer. Any interface deviation must be documented before accepting it.

## Synthesis decision

Candidate A is the base. It keeps revocation and renewal atomic in one object and avoids migration. The independent cross-judge agreed. Candidate B contributes the fail-closed cancellation position, failure metadata in HTML, and additional HTTP fault scenarios. Reject B's three-object migration because old replicas cannot sign in against its new record and logout/renewal need additional cross-object consistency rules.

Reject A's sixty-second activity coalescing, shielded renewal, route registry, and live-evidence implementation gate. Reject the judge's deferred activity graft because it changes idle accounting. Keep bounded contention failures with precise diagnosis. These are synthesis decisions rather than claims about existing policy.

## Tradeoffs accepted

- One confirmed activity update per advancing timestamp retains the current write rate.
- Sustained contention can still return a truthful 503 after the retry budget.
- Waiting renewal siblings add bounded storage reads.
- A cancelled exchange may require sign-in. A late thread-based storage write may still commit; a 503 does not claim non-commit.
- Mixed old/new replicas retain old replica 503 behavior temporarily. The additive nonce preserves record readability and rollback.

## Alternatives considered

Separate activity and credentials eliminate shared activity writes but add migration, reads, and cross-object revocation rules. Process locks cannot protect replicas. Browser retry cannot safely replay mutations. A timestamp-only patch leaves multiple session writers and unguarded lifecycle races.

## Verification

Use minted identities and LocalStore through the real ASGI endpoint, including two independent reader instances sharing a store. Barrier fixtures enforce competing read/write orders. First run a navigation regression against the old code and capture its failure category; then prove it passes after the change. Cover activity pairs, passive/activity order, exact idle boundaries, single renewal, refusal, stale/cancelled leases, logout during renewal, cross-device preservation, lease and settlement self-conflicts, removal self-conflicts, ambiguous logout, callback concurrency, old-record compatibility, storage/content/personal/location faults, route-returned 503s, and sentinel redaction. Preserve existing personal ambiguity tests. No OCR, source books, production requests, deployment, or resource changes.

## Open questions and risks

The original six live failures remain unattributed. Local verification cannot establish live renewal or operational acceptance. Deployment and a repeated live workload require separate operational authorization. No such action is part of this implementation.

## Next implementation step

Add diagnostics and a deterministic HTTP regression, then implement SessionBook and migrate every existing caller in the same branch.

## Implementation notes

The public session types and three operations above are implemented together
with their migrated callers. The private record representation remains a decoded
dictionary inside SessionBook; it is never returned to a route. No separate
codec/domain-object hierarchy is needed for the unchanged encrypted record.

One safety refinement to settlement failure cleanup: a write exception can mean
that settlement committed. Before revoking a newly issued refresh token after
such an exception, SessionBook rereads the owner record and revokes only if that
token is absent from every stored entry. If the confirmation read also fails,
the token is left unrevoked and the original failure propagates. This avoids
revoking a live stored token after an ambiguous successful settlement. It can
leave an unreachable token at the provider when storage cannot confirm the
outcome. Cancellation still propagates immediately, leaving its lease in place.

Endpoint-generated JSON failures use the category as `error` and include `stage`
and `request`. Route-returned failures retain their existing `error` value and
add `category`, `stage`, and `request`, preserving personal-state ambiguity
semantics. HTML failures contain category/stage metadata and a visible reference.
The internal dispatch receives the request trace so sign-in reasons do not need
an additional public diagnostics accessor. Deployment revisions accept only a
40–64 character hexadecimal revision or SHA-256 digest; unrecognized environment
values are recorded as null. Stage aggregates are bounded by the Stage enum.

Verification is serving-only and synthetic. The release selector includes the
new HTTP race suite. These checks do not attribute the original live failures
and do not establish real provider or deployed object-store behavior.
