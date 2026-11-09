# Protected reader session overhead

The owner reopened the architecture after this investigation. The later [session-authority design](reader-session-authority-design.md) supersedes this document's recommendation to retain the current session layout. Its measurements and evidence limits remain historical findings.

Investigation for [Investigate session-storage overhead on protected reader requests](https://github.com/rickono/cookbook-mcp/issues/134), 2026-11-05.

See the [write-path follow-up](reader-session-write-followup.md) for subsequent SDK, encoding and direct-HTTP experiments, plus the concurrent-deployment limitation.

## Finding and recommendation

Session storage dominates the observed authentication path. The smallest evidence-supported recommendation is to retain the current session design and diagnose the remote PUT path before selecting another optimization. Retained hosted traces now independently price conditional writes. Current main already avoids passive writes and search's serial preflight. Preserve those changes and the shared durable authority. Do not add a positive authorization cache or defer activity timestamps.

The [alternatives analysis](reader-session-storage-alternatives.md) covers expiry, both logout scopes, refresh rotation, concurrent tabs, restarts and schema migration. Serializing monitor requests with a fresh queued follow-up is a bounded candidate, but this capture does not establish duplicate checks. It cannot remove the active-request PUT or its cost. Require a measured duplicate-trigger workload before implementing it.

## Evidence and provenance

Reviewed main at `9031857c162b070ad4326d5208f33a87e430bf0c`. A read-only hosted module-hash probe found exact SHA-256 matches for `reader_sessions.py`, `reader_diagnostics.py`, `reader.py`, `server.py`, and `storage.py`. This verifies those modules at inspection time, not the entire running image or its historical configuration. Captured diagnostic revisions were null, so immutable image attribution remains a follow-up.

A single `flyctl logs --no-tail --json` read retained 100 log envelopes, including 77 reader diagnostic events, over 2026-11-06 03:11:25–03:24:29 UTC. These are existing traffic, not requests generated for this investigation or a randomized experiment. No source content, session credentials, owner identifiers, URLs with queries or private paths enter this report. Raw captures remain outside Git.

| Successful hosted route | Samples | Server wall ms, median [range] | Read stage ms, median [range] | Write stage ms, median [range] |
| --- | ---: | ---: | ---: | ---: |
| `/reader/session` | 15 | 343 [246–530] | 342 [245–529] | No stage recorded |
| `/reader/catalog` | 4 | 1839.5 [1604–1920] | 301.5 [254–312] | 1534.5 [1347–1605] |

Every sample in these two groups returned 200. Each recorded one read and one token verification. Catalog recorded one write each, with zero CAS conflicts. Session checks recorded no writes. Token verification took 1 ms per request after diagnostic rounding. The session group's total recorded wall was 5202 ms, of which 5189 ms was in reads; catalog's four write stages accounted for 6021 of 7203 ms. These totals describe this capture only. Neither group establishes production percentiles or failure rates.

One other `/reader` request recorded 253 ms for token verification. There is no key-fetch trace to call this a cold production worker. No renewal, renewal wait, or conditional conflict was present in the retained live events. The separate synthetic transport experiment below measures rejected remote PUTs. Real hosted renewal and sibling-wait latency remain unmeasured. Server stage wall includes thread scheduling, serialization, encryption, SDK work, remote I/O and any SDK retries. The trace does not isolate network wait from CPU or reveal SDK-level attempts. Stage names identify application operations, not a packet trace.

The historical 5.19-second session-check outlier did not recur among these session traces. Its cause remains unattributed. Do not infer renewal, storage retry, cold keys or contention from its duration alone. Request IDs and fixed stage/category diagnostics should accompany any recurrence. Nested stage durations, particularly renewal wait and content delivery, must not be added as disjoint costs.

## Hosted synthetic transport experiment

`scripts/probe_session_transport.py` uses the configured session-bucket adapter on the hosted machine. It creates two random, synthetic encrypted objects outside `reader/owners/`. It never reads or changes a real session. Both clients use the production adapter's connection pool, timeouts, retries and endpoint. One experimental client unregisters botocore's `Expect: 100-continue` hook. The application clients remain untouched.

The hypothesis was that botocore's one-second continue wait explained the write penalty. A separate instrumented run disproved it. Five default-client updates spent a median 3.07 ms [2.86–4.35] in `wait_for_read`, against 1544.37 ms [1464.46–1736.67] total. Removing that hook avoided the wait call but did not materially change PUT latency. The hook can wait one second in the [botocore request implementation](https://github.com/boto/botocore/blob/1.43.93/botocore/awsrequest.py#L125-L134); that capability is not evidence of a one-second wait in this deployment.

The following separate run did not wrap the transport wait. Each side warmed its pool before timing. Five alternating default/experimental trials each performed an encrypted conditional update, confirmed byte-for-byte GET and version, deliberately stale conditional update, and another unchanged readback. Both sides rejected all five stale writes. Both temporary objects were deleted and confirmed absent after each run. No failures or cleanup failures occurred.

| Variant and operation | Samples | Wall ms, median [range] | Process CPU ms, median [range] | SDK retries |
| --- | ---: | ---: | ---: | ---: |
| default: update | 5 | 1639.11 [1451.95–2031.35] | 2.71 [2.57–3.41] | 0 |
| default: read | 5 | 347.74 [193.89–369.28] | 2.48 [2.43–2.79] | 0 |
| default: conflict | 5 | 331.62 [326.86–410.87] | 2.89 [2.53–4.77] | 0 |
| without_expect: update | 5 | 1570.51 [1496.58–1926.18] | 2.68 [2.49–2.85] | 0 |
| without_expect: read | 5 | 324.04 [319.95–349.76] | 2.7 [2.39–2.88] | 0 |
| without_expect: conflict | 5 | 350.03 [238.02–518.87] | 2.49 [2.46–4.65] | 0 |

The experiment found no measurable improvement from removing Expect. Remote load and scheduling pressure were not independently recorded, so the comparison remains exploratory. The observed wait is external to Python CPU, with no SDK retries in this run. The residual interval can include endpoint processing, transit, sockets and uninstrumented SDK waits; it is not isolated network-transit latency. Read-modify-write admission must still preserve both durability and conditional conflict behavior. Switching off Expect is not recommended from these results.

This test establishes remote PUT and rejected-PUT costs for small synthetic objects. It does not establish owner-record-size sensitivity, hosted renewal latency, high-concurrency percentiles, or a user-visible speedup. Run the probe only with its explicit `--live-synthetic-writes` switch in an environment configured for the private session store. The optional `--profile-expect` switch enables the separate transport-wait profile. Keep raw output private.

## Synthetic HTTP attribution

`tests/test_reader_session_probe.py` drives the real ASGI boundary, encrypted LocalStore CAS, RSA token verification, and two independent Reader instances sharing a store. It injects 20 ms in each owner read and PUT and 80 ms in each synthetic provider exchange. It counts attempts and actual conditional conflicts, verifies served catalog content or authenticated JSON, and checks expected failure categories. Setup, login, token minting and publication creation are outside timing.

The decision being tested was whether current passive authorization still writes and whether contention or renewal repeats provider exchanges. Operation counts decide those questions. The timings explain injected work only. They are not a forecast of hosted latency or a before/after speedup. Five trials per scenario ran sequentially, without interleaving different scenarios. The machine had 10 logical CPUs and load averages 5.51, 4.35 and 3.76 before the run, with other repository tests active. Process CPU includes the ASGI client and all test threads. Wall minus process CPU is not a measurement of network time. Known injected sleeps and counted completed operations establish the synthetic limiter.

| Scenario | HTTP statuses per trial | Owner reads | PUT attempts | Conflicts | Provider exchanges | HTTP wall ms, median [range] | Process CPU ms, median |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| passive | 200 | 1 | 0 | 0 | 0 | 24.15 [23.16–26.01] | 0.94 |
| active | 200 | 1 | 1 | 0 | 0 | 48.1 [44.48–52.32] | 2.23 |
| conflict | 200 | 2 | 2 | 1 | 0 | 95.88 [93.62–102.32] | 2.75 |
| exhausted | 503 | 4 | 3 | 3 | 0 | 171.66 [167.4–173.84] | 2.79 |
| renewal | 200 | 2 | 2 | 0 | 1 | 180.17 [173.89–182.27] | 3.93 |
| refused | 401 | 2 | 2 | 0 | 1 | 181.95 [174.88–183.1] | 3.74 |
| siblings | 200, 200 | 6 | 3 | 1 | 1 | 272.36 [270.85–274.51] | 6.48 |
| storage_fault | 503 | 1 | 0 | 0 | 0 | 25.24 [22.31–25.54] | 0.51 |

Each row contains five trials. The sibling row times the completion of both requests and sums their operation counts. Failed admission and provider refusal are separate scenarios, never successful latency samples. All eight scenarios passed. The ordinary token-verification wrapper measured a median 0.18 ms in both passive and active scenarios with a configured local public key. This excludes remote JWKS behavior. The diagnostics' integer rounding reports these submillisecond checks as zero.

A successful renewal required a claim read and PUT, one provider exchange, and a settlement read and PUT. It performed three verifier calls, including the expired-token allowance. A refused provider required two verifier calls and session removal. Two overlapping renewals produced a real CAS conflict and sibling polls while exchanging only once. Three forced uncommitted conflicts produced four reads, three PUT attempts, and a truthful 503. Existing lifecycle tests cover cancellation, ambiguous commits, expiry and logout races beyond these probe scenarios.

## Reproduce and validate

Use an isolated checkout with locked dependencies. These selected checks are serving-only and synthetic. They invoke no OCR or model inference.

```sh
uv sync --frozen
uv run pytest -q -s tests/test_reader_session_probe.py
uv run pytest -q tests/test_reader_http.py tests/test_reader_session_races.py tests/test_reader_session_summary.py
node --test tests/reader_session.test.mjs
uv run ruff check tests/test_reader_session_probe.py tests/test_reader_session_summary.py scripts/summarize_reader_sessions.py scripts/probe_session_transport.py
```

The lifecycle selection passed 67 Python tests. The summary's privacy and failure-handling tests passed two tests. The monitor/logout selection passed eight Node tests. The probe passed eight scenarios, each with five trials. Focused lint and formatting passed. Keep raw output outside Git. Only the source-safe conclusions belong in this branch.

`python scripts/summarize_reader_sessions.py < PRIVATE_CAPTURE` accepts Fly's concatenated JSON envelopes or direct diagnostic JSON. It emits fixed routes, fixed stage names, numeric durations and counts only. It excludes non-200 durations from success statistics and retains status counts. Missing stages or invalid numbers remain unknown. Tests prove that private sentinel fields and arbitrary route/stage strings cannot escape and that failed requests cannot lower success statistics.

## Remaining acceptance evidence

This research supplies a recommendation, hosted normal-path read/write attribution, remote rejected-write timings, and synthetic renewal/concurrency traces. It does not complete a controlled end-to-end comparison or real-provider renewal timing. Keep issue 134 open for those evidence gaps rather than marking its full-path measurement complete. The earlier session-check outlier remains explicitly unattributed. No deployment, publication change, source processing or resource-ceiling change occurred. Hosted writes were confined to the temporary synthetic transport objects, with confirmed cleanup.

## Controlled end-to-end plan

1. Pin image digest and source hashes before and after each capture. Record deployment region, worker restart, configured owner count, SDK version, storage endpoint region, connection reuse, and unrelated traffic without publishing private configuration.
2. Use the same authenticated browser and books for navigation, search submit-to-DOM, and focus/pageshow/visibility/timer bursts. Retain request IDs and every failure. Run at least five alternating trials per implementation and distinguish warm from fresh-worker cases. The existing search preflight removal is already in the baseline.
3. Match browser request IDs to server spans. Split owner GET and PUT into thread-queue time, process/thread CPU, encryption/JSON time, SDK attempts, connection/TLS setup, and transport wait. Use closed counters only, with no HTTP-body or header logging. Profile separately from headline timings.
4. Exercise passive renewal, active renewal, sibling waits, a definite conflict, and an ambiguous acknowledgement using synthetic identities in a separate configured environment. Keep provider timeout, lease, CAS limits and storage permissions unchanged. Real provider rotation remains an acceptance check, not something synthetic stubs establish.
5. Repeat device/all-device logout across two readers and a restart, exact idle/absolute boundaries, logout during renewal, cancellation, conflict exhaustion and uncertain settlement. Reject any change that serves a revoked session on a later authoritative admission or replays a refresh exchange.
6. Measure duplicate monitor traffic before selecting browser serialization. Any coalesced trigger must retain a fresh queued follow-up; an in-flight old 200 cannot stand in for a later revalidation. A reduction in background work does not imply faster active navigation.
7. Report medians, ranges, errors and completed operations separately. Stop if variation swamps an alleged difference. Do not sum nested spans, count removed preflights twice, or extrapolate these samples to tail percentiles.

## Primary sources

- [SessionBook admission, CAS, expiry and rotation](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/reader_sessions.py).
- [Diagnostic stage definitions and rounding](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/reader_diagnostics.py).
- [Storage GET and conditional PUT implementation](https://github.com/rickono/cookbook-mcp/blob/9031857c162b070ad4326d5208f33a87e430bf0c/src/cookbook/storage.py).
- [Agreed session and caching contract](https://github.com/rickono/cookbook-mcp/issues/94).
- [Release acceptance workload](https://github.com/rickono/cookbook-mcp/issues/107).
- [Historical observations and evidence limits](https://github.com/rickono/cookbook-mcp/issues/134).
