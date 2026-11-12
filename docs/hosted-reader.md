# Hosted reader: sign-in and catalog

Implementation of [Sign in and browse the private hosted library](https://github.com/rickono/cookbook-mcp/issues/99).
This is code and synthetic HTTP verification, not a deployment or observed hosted
login/refresh exchange. Source-bound book reading is described in [reader-content.md](reader-content.md).
Search, bookmarks and reports are separate slices of #98.
Durable bookmark/resume configuration is in [reader-personal.md](reader-personal.md). No Mac relay, second library or ingestion pipeline is used.

## Configuration gate

With no `READER_*` environment variables the existing MCP service runs unchanged.
Any reader setting opts in and requires all seven values below; partial settings
fail startup. Empty placeholder reader variables must be omitted when disabled.

| Variable | Contract |
| --- | --- |
| `READER_ORIGIN` | Exact public HTTPS origin, no trailing slash/path/query; same origin as `COOKBOOK_AUDIENCE`. |
| `READER_CLIENT_ID` | Dedicated confidential Auth0 **Web Application** client, not the native publisher or MCP client. |
| `READER_CLIENT_SECRET` | Client secret supplied by the deployment secret manager; never browser-visible. |
| `READER_SESSION_KEY` | Fernet key, generated privately with `Fernet.generate_key()` and retained across restarts/replicas. Rotation requires migration or deliberate removal of the old encrypted session records. |
| `READER_S3_BUCKET` | Private shared session bucket, distinct from both library and agent-report buckets. |
| `READER_AWS_ACCESS_KEY_ID` | Dedicated session bucket credential, distinct from library/report keys. |
| `READER_AWS_SECRET_ACCESS_KEY` | Secret for that credential. |

Optional `READER_S3_ENDPOINT_URL` defaults to `S3_ENDPOINT_URL`; HTTPS is required.
Optional `READER_OIDC=1` requests `openid` and requires signed ID-token issuer,
client audience, lifetime, subject agreement and transaction nonce validation.
Default `0` requests only `library:read offline_access`. Access authorization always
requires a separately verified API access token with exact existing issuer,
audience, owner allowlist and `library:read`. An ID token is never authorization.
Keep the existing `COOKBOOK_*` verifier and JWKS configuration unchanged.

Register exactly `READER_ORIGIN/reader/callback` as the allowed callback and
`READER_ORIGIN/reader` as the allowed logout return. Allowed web origins must be
exactly `READER_ORIGIN`, without wildcard, native loopback or arbitrary redirects.
Enable Authorization Code with S256 PKCE, confidential `client_secret_post`,
Refresh Token grant, API offline access, and appropriate refresh rotation/lifetimes.
Enable the authorization-response `iss` parameter: callbacks missing it or with a
mismatched issuer fail closed. Verify these provider settings before release;
this implementation makes no live identity/account changes.

Terminate TLS at a trusted edge, force HTTPS, preserve the public Host header,
disable callback/query/body/header logging and bypass CDN caching on `/reader*`.
For TLS terminated upstream, set `COOKBOOK_TRUSTED_PROXY_IPS` to explicit verified
proxy IPs/CIDRs so Uvicorn accepts their forwarded HTTPS scheme. Wildcard trust is
refused. Block direct untrusted backend access and ensure the edge overwrites
forwarded headers. Without a trusted HTTPS scheme the reader rejects requests;
never relax its exact origin check to work around a deployment configuration.
Access logging remains disabled in the service. Do not enable HTTP wire/body
logging at the identity or storage clients. Apply provider-side abuse controls to
login at the edge without logging OAuth parameters.

Session storage needs strongly consistent reads and conditional object writes
(`If-Match`/`If-None-Match`). Scope its credential to that bucket's session prefix
only. It has no publication, correction, approval or report authority; retain the
runtime library credential read-only. Use private encrypted storage, access audit
and backups under the same confidentiality policy. The client secret belongs in
the service secret manager; encrypted access/refresh tokens, CSRF values and login
transactions reside in shared storage. Stored object keys hash owner/session/state
identifiers; cookie values never become store paths. LocalStore is used only for
synthetic tests, not a replica-local hosted session fallback.

The R2 deployment implements separation with one dedicated private US bucket and
bucket-scoped key per store. Permanent R2 keys are bucket-scoped rather than
GetObject/PutObject-only prefix grants; their Object Read & Write permission also
permits listing and deletion inside that bucket. Live admission checks verify
denial against the other reader stores and library bucket. No runtime key has
bucket-administration authority. See [receipt retention](owner-reports.md#r2-deployment-permissions)
for the provider-enforced immutable report prefix.

The owned Typesense child does not inherit reader, personal, owner-report or
legacy provider credentials. Its subprocess environment omits those prefixes
alongside library/report credentials; the engine receives only its own generated
loopback API key through a private configuration file. A source-free process
regression verifies the environment without launching an engine or parser.

Keep the encryption key separate from backups. Expired transaction records can be
purged after ten minutes; consumed transaction tombstones can be removed after
that same window. Expired owner sessions are pruned on login/access; unused owner
records may be purged after thirty days. No lifecycle rule may delete live sessions.
The implementation caps active reader sessions at 100 per owner; it reports a limit
instead of silently evicting a device. Retention/cleanup jobs are deployment work.

## HTTP and session behavior

- `GET /reader` and `/reader/catalog`: sign-in entry when unauthorized; otherwise
  an escaped, paginated catalog from the active shared Library. Continuations use
  opaque publication identifiers; “Published” identifies catalog membership, not
  approval or a promise that all of a book's text is available.
- `GET /reader/login?return=catalog`: only the named opaque destination is accepted.
  State, PKCE verifier, nonce and a hashed browser transaction cookie binding are
  stored encrypted for ten minutes. A conditional consume precedes code exchange.
- `GET /reader/callback`: requires single code/state/iss values and the matching
  host-only transaction cookie. Tokens stay server-side. A 303 removes the callback
  values before any reader UI is loaded. Every callback failure (including storage
  failures) redirects to `/reader/signin-failed`, clears the transaction cookie,
  and shows a generic sign-in prompt there. Provider parameters are never echoed.
- `GET /reader/session`: verifies current access and supplies a CSRF token to the
  authorized tab. Passive checks do not extend inactivity. This reusable public
  session boundary supports subsequent reader adapters.
- `POST /reader/logout`: URL-encoded `csrf` and `scope=device|all`, plus the exact
  Origin. Conditional server invalidation precedes attempted refresh revocation.
  Device logout redirects to the same-origin `/reader/signed-out` page, which offers
  an explicit Auth0 SSO sign-out link. Follow that link to end provider SSO; the
  local session is already invalidated even if Auth0 is unavailable. This keeps
  `form-action 'self'` restrictive and avoids an external form redirect.
  All-device logout invalidates every owner reader session.

The session cookie is opaque `__Host-reader`, Secure, HttpOnly, Path=/,
SameSite=Lax, with no Domain. It contains no tokens, claims or private content.
Authorization is checked against shared durable storage on every protected request.
Sessions expire after seven days without reader activity or thirty days absolutely.
Expired access tokens renew only after validating their signature, issuer,
audience, owner and scope, and only with an issued refresh token. Renewed tokens
are verified again. Missing/refused/invalid renewal ends reader access; synthetic
renewal is tested, but **live automatic renewal is unverified**.

Conditional writes serialize refresh and logout across replicas. SessionBook
rereads after a definite conflict and decides against the fresh record. Activity
timestamps move forward without overwriting token or logout changes. Passive
session and publication checks do not write activity. Sustained contention still
returns a bounded 503 rather than acknowledging an uncommitted activity update.
An ambiguous refresh exchange is never replayed with the same rotating token.
Other requests wait and reread within their deadline; an uncompleted ten-second
renewal lease requires sign-in. Cancellation leaves that lease fail-closed.
Storage failure serves no private content. Personal mutations require explicit
retry when persistence is unconfirmed.

Every reader response includes `X-Reader-Request`. Each 503 also includes
`X-Reader-Failure` with its category, stage, and attempt count. Failure bodies
retain the category and request reference, while existing personal-state error
codes keep their meaning. A redacted JSON record includes bounded stage timings
and a validated revision when available. It excludes identities, cookies, tokens,
queries, locations, content, and exception messages. Provider timeouts are
identified as unconfirmed renewal rather than refusal. See
[reader session design](reader-session-design.md) for concurrency and cancellation
constraints. These diagnostics do not establish the cause of earlier live 503s.

Protected responses and OAuth redirects use private no-store, no-referrer, restrictive
CSP, frame denial and nosniff headers. Catalog markup is escaped; no source scripts,
external resources, browser storage, service worker or offline cache is used.
Only public reader code (first-party scripts/styles and the bundled viewer engines)
may enter the browser HTTP cache, with an ETag and `no-cache` revalidation; it
carries no book, account or session data.
The generic session script checks on focus, pageshow and at most every minute;
a 401 clears the view and navigates to sign-in. Logout clears the current view and
requests cache/storage clearing; other live tabs clear on their next check.
Already delivered pixels cannot be recalled. Logout does not end Google or MCP
sessions, nor guarantee immediate invalidation of a copied valid access JWT.

## Verification and remaining release gates

`uv run pytest -q tests/test_reader_http.py tests/test_library_auth.py tests/test_hosted.py tests/test_mcp.py`
uses synthetic publications/keys/provider responses and performs no OCR, ingestion
or model work. HTTP tests cover PKCE/confidential exchange, conditional nonce,
correlation/replay, denied identities, restart/tab persistence, lifecycle/renewal,
CSRF, both logout scopes, storage failures, privacy and MCP separation.

Before release, provision and verify the settings above; prove real hosted login,
refresh issuance and an actual authorized refresh exchange, restart/replica
persistence and catalog browsing while the Mac is offline. Verify Safari/Chromium,
phone/tablet reflow/zoom, keyboard and VoiceOver against the deployed service.
Semantic labels, responsive styling and 44px controls are implemented; no actual
device/accessibility or hosted performance audit is claimed. Keep raw evidence,
credentials and books outside Git/GitHub.

The assembled serving-only regression command, local synthetic browser harness,
configuration checklist and outstanding evidence gates are recorded in
[reader-release.md](reader-release.md). Passing those synthetic checks alone does
not establish release acceptance.
