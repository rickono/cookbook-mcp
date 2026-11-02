# Assembled reader release verification

Implements the repeatable verification and integration-fix portion of
[Prove the complete hosted reader journey and release acceptance](https://github.com/rickono/cookbook-mcp/issues/107)
under [the full reader contract](https://github.com/rickono/cookbook-mcp/issues/98).
Prepared base: `integration/spec-98` at
`74b21a8f0de1a4b9d88b4bb1a4bd0500ad25fbd5`, containing #99–106.
**Release acceptance remains pending external evidence.** Parent integration and
code review can proceed; merging this work does not establish release acceptance.
The implementation and local preview do not establish a deployed release.

## Repeatable safe checks

Run from the repository root:

```sh
python3 scripts/verify_reader_release.py
uv run pytest -q tests/test_reader_preview.py
uv run ruff check scripts/verify_reader_release.py tests/reader_release_fixture.py tests/test_reader_release.py
uv run ruff format --check scripts/verify_reader_release.py tests/reader_release_fixture.py tests/test_reader_release.py
git diff --check
```

The explicit allowlist runs assembled HTTP, MCP client, dashboard, authorization,
manifest, serving-rendering and legacy/owner report regressions plus browser-script
DOM simulations. It never discovers the ingestion/model/OCR suite. Existing Linux
serving-enforcement tests skip on macOS; a skip is not enforcement proof. Keep the
separate mandatory OCR launcher and all resource ceilings unchanged.

The `Reader release` GitHub Actions workflow repeats this explicit selection on
Ubuntu with Python 3.12, Node 22 and the locked dependencies. Its synthetic decoder
checks execute the Linux serving limits; it does not discover or invoke OCR tests.

`tests/test_reader_release.py` adds a single cross-feature HTTP journey over real
Library, publication and storage adapters: sign-in, catalog, section search,
complete continuation reconstruction, supported synthetic JPEG delivery, bookmark,
publication update without moving pinned text, current-location adoption, new app
and second session, scanned description-only durable receipt/retry, and all-device
logout. Sibling HTTP tests cover native BookModel occurrences, both independent
search groups, authored reference/original returns, retirement/withdrawal, resume,
failed renewal, conditional writes, original refusals, timeouts, concurrent receipts,
rate limits and lost responses. The native keyword service is an injected external
stand-in; this does not prove Typesense behavior.

The timing probe prints one cold observation and twenty warm observations for
**local in-process ASGI section search plus HTML reading**. It verifies successful
responses, reports nearest-rank p95 and makes no hosted performance assertion.
It has no network shaping, native keyword service, browser paint/action timing,
mixed-format latency workload or production cold-start measurement. Do not use its
numbers as the parent five-second or 200ms acceptance result. Raw run logs and
synthetic artifacts stay outside Git.

## Integration fixes

Search-mounted reading now carries trusted first-party response stylesheets into
the live document, including the reading stylesheet formerly lost with the
parsed response head. The existing first-party script initialization remains.
A mount-departure event clears personal/report drafts and invalidates continuation
handlers. Late continuation responses after departure or authorization expiry
cannot insert old text into a subsequent view or rewrite its URL. Late report
responses cannot resurrect a cleared draft/status. Regression tests first failed
on the old behavior and passed after each corresponding change. Source text is
still inserted as text, and mutations are never automatically replayed.

## Local browser harness

`tests/reader_release_fixture.py` creates the assembled production application,
using synthetic identity, a hand-authored three-section EPUB index, a generated
raster and separate LocalStore adapters. It adds no HTTP routes or authentication
bypass. It binds no production identity, storage, source material or search engine.
Provide an already browser-trusted local TLS certificate and key outside Git:

```sh
PYTHONPATH=tests:src uv run uvicorn reader_release_fixture:app --factory \
  --host 127.0.0.1 --port 9443 --no-access-log \
  --ssl-certfile /absolute/private/cert.pem --ssl-keyfile /absolute/private/key.pem
```

Default origin is `https://127.0.0.1:9443`; optional `SYNTHETIC_READER_ORIGIN` must
match the local certificate/origin. Temporary fixture storage lives outside Git
and is regenerated at each process start; use HTTP tests for durable restart proof.
Do not deploy this synthetic factory.

Open `/reader/login`. Its synthetic same-origin issuer has no `/authorize` route,
so the expected 404 address contains the real transaction's `state`. Navigate to
`/reader/callback?code=synthetic&state=<that-state>&iss=https%3A%2F%2F127.0.0.1%3A9443%2F`
in the same browser to simulate the external provider response, then exercise
catalog/search/read/continuation/bookmarks/original selection/return/logout.
This tests production callback correlation and browser cookie custody, not a real
provider login. Scanned reporting and faults are covered by the HTTP/DOM selection;
this small browser fixture does not claim all mixed-format acceptance scenarios.
Stop the process after inspection. No TLS trust or browser security changes are
part of this harness.

## Observed evidence and absent prerequisites

Local verification on 2026-11-01 (America/Chicago), macOS, Python 3.12.11,
Node v22.23.1. Fixture identities are invented (`book-0`, `section-0`, `image-0`);
publication IDs are generated per run and source hashes derive solely from the
synthetic fixture. The base above plus this commit identify the tested code; there
is **no tested deployment**. Later synthetic loopback browser observations are
recorded in [reader-local-preview.md](reader-local-preview.md). The owner accepted
the polished layout and explicitly removed kitchen mode from the requested scope.

| Gate | Observation or remaining requirement |
| --- | --- |
| Assembled HTTP and regressions | 161 passed on macOS with six Linux-only skips. [Linux CI](https://github.com/rickono/cookbook-mcp/actions/runs/41380576790) subsequently passed all 167, including serving enforcement; the preview boundary test also passed. |
| Browser scripts | 43 Node DOM simulations passed after UI polish, including search-mounted enhancement initialization; these are not browser rendering. |
| Local browser | The initial HTTPS harness failed with `ERR_CERT_AUTHORITY_INVALID`; no trust change was made. The separate synthetic HTTP loopback preview later exercised Chrome catalog, search-mounted reading, saved places and decoded sample originals, with 390/320px reading reflow. This proves local interaction only. |
| Identity and Mac-off | Deployment is now owner-authorized. Dedicated live web-client credentials and verified callback/issuer/rotation configuration still require provisioning. Real login, issued refresh token, actual renewal and Mac-off operation remain unverified. |
| Shared storage | LocalStore conditional-write behavior observed; live S3 consistency/CAS, least-privilege policies, replica/restart durability and backup recovery remain unverified. No production storage credentials/policy evidence supplied. |
| Native search | Real Library native resolution and SQLite section retrieval covered; no running Typesense mixed-publication service supplied. Actual typo/ranking behavior remains unverified. |
| Originals/resource enforcement | Authenticated synthetic JPEG bytes and injected scanned rendering outcomes covered; a sample original decoded in local Chromium. Linux CI passed all six synthetic decoder enforcement checks. Hosted representative originals still require observation. Refusals do not count as successful display or incident repair. |
| Devices/accessibility | Local Chrome 390/320px reading reflow observed. Safari, iPhone/iPad, VoiceOver, full keyboard/focus/contrast/44px target checks, tablet orientations, 1280px desktop, 200/400% zoom and orientation during reading/failure remain unverified. Kitchen mode and its former 52px target requirement were removed at the owner's request. |
| Performance/budgets | No authorized hosted workload or network shaper supplied. Still require 10 Mbps/100ms RTT, at least 20 warm mixed-format repetitions, separate cold start, action acknowledgement <=200ms, first usable text/search p95 <=5s, actionable metadata/text/search <=10s and images <=30s. Browser timeout logic and local timing are not measured network evidence. |
| Privacy | Synthetic HTTP checks cover no-store/CSP/frame/referrer/nosniff, CSRF/Origin, escaping, token custody, logout and expiry. Actual browser cache/storage/history, deployed edge/client logs and CDN behavior need inspection. |

### Pre-deployment browser check

After the main integration landed as
`5ba846efa2b389a8f805690a49ac25e8249b9378`, the local synthetic preview was
checked in Chromium 152.0.7977.169 / Electron 44.10.0. Catalog, search, bookmarks,
native/scanned reading and original views were sampled at 320 and 1280 CSS px.
Computed bounds, visible form labels and foreground/background color contrast
were inspected; this was a focused check, not a complete accessibility audit.

The Books breadcrumb measured 40.6 × 44px. The shared link rule now gives it a
44px minimum width. Rechecking reading with all details expanded found no
sampled targets below 44px, missing input labels, page overflow or text contrast
failures. The sampled catalog, search, bookmarks and original views passed the
same checks. Tab reached the skip link with a visible 3px focus outline; Enter
moved focus to `main#reader-main`. A synthetic 1000 × 1400 original decoded in
the browser. No service worker controlled the page; local/session storage were
empty after removing the obsolete demo kitchen preference left by the prototype.

These observations do not establish Safari/VoiceOver, real device, full keyboard,
zoom, network, identity-provider, cloud persistence or hosted acceptance.

## Reviewable deployment configuration checklist

Provisioning on 2026-11-01 created a dedicated confidential Cookbook Reader web
client, exact hosted callback/logout/origin restrictions, authorization-code and
refresh grants, rotating refresh tokens with seven-day idle/thirty-day maximum
lifetimes, Google login and only the existing API's user-delegated `library:read`
permission. The client has no Management API, machine-to-machine or anonymous
library grant. Existing clients and the API's offline-access setting were retained.

Three separate private US R2 buckets and bucket-scoped runtime keys were created.
Live source-free probes passed conditional create/update/read, stale/duplicate
write refusal, and cross-bucket access denial. An indefinite lock on accepted
owner receipts refused overwrite and deletion. R2's lock-before-precondition
error required a conditional-create conflict adapter; a regression first failed
on that provider error and then passed with unrelated failures still propagated.
Actual operation-level grant limits are documented in the storage contracts.
This provisioning record does not establish a deployed reader, restart/backup
recovery, real login/renewal, Mac-off operation or device/performance acceptance.

The owner has authorized the deployment step; provisioning credentials are still
required before live identity and storage changes can be performed.
Use [hosted-reader.md](hosted-reader.md), [reader-personal.md](reader-personal.md),
[owner-reports.md](owner-reports.md) and [hosted-runtime.md](hosted-runtime.md)
as the exact configuration contracts. Before release, attach source-safe evidence
for every item below, with deployment commit, browser/device versions, synthetic
publication/source identifiers and outcome. Keep credentials, books, images,
passages, personal descriptions, private paths and raw evidence outside Git/GitHub.

- Configure all seven required `READER_*` values together. Exact HTTPS origin must
  match the existing API audience. Keep issuer, audience, owner allowlist and
  `library:read` verifier unchanged; ID tokens never authorize access.
- Use a dedicated confidential Web Application, exact callback/logout/web origins,
  Authorization Code/S256 PKCE, `client_secret_post`, response `iss`, offline API
  access and refresh grant/rotation/lifetimes. Verify nonce when OIDC is enabled.
  Prove real refresh issuance and renewal, denied renewal and both logout scopes.
- Retain the session encryption key privately across replicas/restarts. Verify
  private encrypted session storage, conditional writes, scoped session prefix,
  inactivity/absolute expiry and cleanup that cannot delete live sessions.
- Configure all `PERSONAL_*` values together in a distinct bucket/key; grant only
  GetObject/PutObject on `reader-personal/owners/*`, conditional updates, no expiry
  of metadata/idempotency evidence, and independent confidential backups.
- Configure all `OWNER_REPORTS_*` values together in a distinct bucket/key; scope
  GetObject/PutObject to `owner-observations/receipts/*` and `limits/*`. Preserve
  create-only receipts, conditional rate updates, no receipt lifecycle deletion,
  and independent backups. Keep legacy agent reports separately authorized.
- Verify separation of all bucket/credential authorities and keep runtime library
  storage read-only. Supply policy evidence without key values. Reader routes
  expose no processing, publication, correction or approval controls.
- Force TLS at a trusted edge; preserve public Host, set only explicit trusted
  proxy IPs/CIDRs, block direct backend access and overwrite forwarded headers.
  Disable callback/query/body/header and wire logging; bypass CDN caching on
  `/reader*`. Verify cookies, CSP, cache/referrer/frame headers in the deployed
  browser. Leave the dashboard loopback-only and metadata-only.
- Run the outstanding observed device, accessibility, Typesense, Linux rendering,
  hosted durability/Mac-off and shaped-network journeys above. Record failure and
  recovery as well as success; missing prerequisites remain acceptance blockers.

## Two-axis remediation disposition

Single implementer pass based on `integration/spec-98` at
`a4700cb9244bee3fb7f8941a84b24de0345660ea`:

- SPEC P2 callback URL cleanup: every unsuccessful callback response, including
  generic storage/timeout failures, redirects to the fixed same-origin sign-in
  failure route before UI delivery. Transaction cookies are cleared; no provider
  text is echoed. Correlation, issuer, PKCE and conditional consume remain required.
- SPEC P2 continuation references: later bounded native chunks append authored
  references with source-derived overlap identifiers, safe labels, truthful
  unresolved states and chunk-bound return envelopes. HTTP and script simulations
  cover late references and retry/overlap behavior.
- SPEC P2 device logout: local invalidation and revocation attempt precede a
  same-origin signed-out page. Its explicit Auth0 SSO link starts provider logout
  without an external form redirect; restrictive CSP remains. The page explains
  provider outage and Google/MCP/copied-token/delivered-content limits. Actual
  Chromium/Safari provider navigation still needs observed browser verification.
- STANDARDS P3 configuration duplication: one shared fail-closed storage validator
  handles opt-in, required settings, HTTPS endpoint fallback and construction;
  personal and owner-report authorities keep explicit separate exclusion lists.
- STANDARDS P3 assets: one explicit first-party map supplies both public asset
  dispatch and route registration. Existing private no-store headers are retained.
- EXTERNAL P1 remains open: none of the missing browser/image, live identity,
  shared storage, Typesense, Mac-off, device, VoiceOver or shaped-network evidence
  above was supplied or waived. No host trust, deployment, account, identity or
  production storage changes were made. These fixes do not establish release
  acceptance.

Remediation verification: the full explicit `verify_reader_release.py` allowlist
passed (161 Python tests; six Linux-only skips; 42 Node simulations). Focused Ruff
lint/format, Node syntax checks and `git diff --check` passed. The callback HTTP
selection was rerun after tightening the correlation/replay assertions (36 passed).
These are local synthetic results, with the same external limitations above.
