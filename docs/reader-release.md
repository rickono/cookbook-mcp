# Assembled reader release verification

Implements the repeatable verification and integration-fix portion of
[Prove the complete hosted reader journey and release acceptance](https://github.com/rickono/cookbook-mcp/issues/107)
under [the full reader contract](https://github.com/rickono/cookbook-mcp/issues/98).
Prepared base: `integration/spec-98` at
`74b21a8f0de1a4b9d88b4bb1a4bd0500ad25fbd5`, containing #99–106.
**Release acceptance remains pending external evidence.** Parent integration and
code review can proceed; merging this work does not establish release acceptance.
No deployment, provider/account changes, OCR, ingestion or inference was performed.

## Repeatable safe checks

Run from the repository root:

```sh
python3 scripts/verify_reader_release.py
uv run ruff check scripts/verify_reader_release.py tests/reader_release_fixture.py tests/test_reader_release.py
uv run ruff format --check scripts/verify_reader_release.py tests/reader_release_fixture.py tests/test_reader_release.py
git diff --check
```

The explicit allowlist runs assembled HTTP, MCP client, dashboard, authorization,
manifest, serving-rendering and legacy/owner report regressions plus browser-script
DOM simulations. It never discovers the ingestion/model/OCR suite. Existing Linux
serving-enforcement tests skip on macOS; a skip is not enforcement proof. Keep the
separate mandatory OCR launcher and all resource ceilings unchanged.

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
the live document, including the reading/kitchen stylesheet formerly lost with the
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
catalog/search/read/continuation/bookmarks/original selection/kitchen/return/logout.
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
is **no tested deployment**. There is **no observed reader browser version**.

| Gate | Observation or remaining requirement |
| --- | --- |
| Assembled HTTP and regressions | 150 passed; six Linux-only serving checks skipped. |
| Browser scripts | 41 Node DOM simulations passed; these are not browser rendering. |
| Browser attempt | T3 preview reached `chrome-error://chromewebdata/`; snapshot timed out after 15s; navigation explicitly failed `ERR_CERT_AUTHORITY_INVALID` for the local self-signed certificate. No protected reader view or image was observed. A browser-trusted local TLS endpoint is absent. No interstitial bypass or trust change was made. |
| Identity and Mac-off | No dedicated live web-client credentials, verified callback/issuer/rotation configuration, authorized hosted deployment or Mac-off test environment supplied. Real login, issued refresh token and actual renewal remain unverified. |
| Shared storage | LocalStore conditional-write behavior observed; live S3 consistency/CAS, least-privilege policies, replica/restart durability and backup recovery remain unverified. No production storage credentials/policy evidence supplied. |
| Native search | Real Library native resolution and SQLite section retrieval covered; no running Typesense mixed-publication service supplied. Actual typo/ranking behavior remains unverified. |
| Originals/resource enforcement | Authenticated synthetic JPEG bytes and injected scanned rendering outcomes covered. No browser-visible decoded original or Linux serving-enforcement run observed. Refusals do not count as successful display or incident repair. |
| Devices/accessibility | No Safari, iPhone/iPad, VoiceOver or equivalent device test session supplied. Keyboard, focus, contrast, actual 44/52px targets, 320px reflow, 390px phone, tablet orientations, 1280px desktop, 200/400% zoom and orientation during reading/failure remain unverified. |
| Performance/budgets | No authorized hosted workload or network shaper supplied. Still require 10 Mbps/100ms RTT, at least 20 warm mixed-format repetitions, separate cold start, action acknowledgement <=200ms, first usable text/search p95 <=5s, actionable metadata/text/search <=10s and images <=30s. Browser timeout logic and local timing are not measured network evidence. |
| Privacy | Synthetic HTTP checks cover no-store/CSP/frame/referrer/nosniff, CSRF/Origin, escaping, token custody, logout and expiry. Actual browser cache/storage/history, deployed edge/client logs and CDN behavior need inspection. |

## Reviewable deployment configuration checklist

Provisioning and live changes belong to a separate authorized deployment step.
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
