# Hosted trial runtime

Current status, October 28, 2026 (UTC): publication
`31f4716be96146c984875e890b9d5b0c` is active on the existing Fly Machine, with
59 native EPUB books and 12 scanned PDF books. The native model retains 7,266
candidate recipe records and 627,907 keyword documents. Exact authenticated
readiness, catalog, search and reading checks pass. Hosted page and region zoom
checks pass for all 12 PDFs, including the largest selected file and the book
with the most pages. Scanned text remains unapproved with 4,329 explicit unresolved
items and one applied source-reviewed correction. One real report remains in the
owner queue; a separate report completed the changed-ledger rebuild and hosted
correction check. A repeated refresh publishes nothing. A higher-resolution zoom
stall remains under investigation in [issue 67](https://github.com/rickono/cookbook-mcp/issues/67);
smaller hosted zoom requests passed after recovery.
See the publication records below and [native recipe interpretation](native-recipe-interpretation.md).

Image selection update, September 13: the existing service now exposes
`list_images` and `inspect_image` before the final `get_image` display. Live
ChatGPT checks confirm candidate inspection without image cards and a single
selected-photo viewer. Deployment details and acceptance evidence are in
[image selection](image-selection.md).

Publication status on September 13, 2026: all 58 authorized EPUB records are uploaded to private R2 and active on the existing Fly Machine as publication `d9e2b701b6864ccaa4aabfd6bc04d32a`. Full remote checksum readback, hosted active-manifest/index validation, the exact 58-book inventory, and health pass. Google publisher sign-in, exact authenticated readiness acknowledgement, 293 hosted MCP calls across all 58 books, and successful-publication history verification now pass. The full build preserves the newer image captions/recipe context and resolves all EPUB TOC links; 57 books have searchable text and one is image-only. See [the full publication record](full-epub-publication.md). The full catalog has now passed authenticated transport checks. Earlier two-book ChatGPT visual acceptance and subsequent viewer deployments remain the recorded in-ChatGPT visual checks.

## Serving and updates

The container runs `cookbook supervise` as unprivileged UID 10001. Its worker, `cookbook serve-hosted`, serves Streamable HTTP on port 8000. The configured resource audience remains `https://cookbook-agent.fly.dev`; the MCP route is `/mcp`. Auth0 issuer, audience, signature, required claims, fixed subject and `library:read` scope are validated for protected requests. The publisher credential must never be placed on Fly.

`GET /healthz` returns only `{"status":"ok"}` without authentication. `GET /readyz` requires an authorized user token and returns the active publication ID and manifest digest, or HTTP 503 when no verified publication is available. Its OAuth challenge points to the resource metadata location for the configured audience. Pydantic URL construction preserves the audience's empty path, so discovery does not silently append a slash to the Auth0 API identifier. MCP Host/Origin validation explicitly permits the configured resource origin; DNS-rebinding protection stays enabled and unrelated hosts are rejected. No bucket or asset is publicly routed.

At startup, a cached publication's manifest digest, runtime file hashes, SQLite integrity, and index publication identity are checked without R2 access. Invalid active state is quarantined within the dedicated runtime directory and never reported ready. The updater immediately tries R2, then waits 60 seconds between completed checks. Failed updates preserve the last verified active pointer; successful updates stage and verify a separate version before atomic activation. Empty runtime storage is reconstructed from R2. Interrupted staging does not replace active state. A staging free-space preflight checks declared runtime byte requirements; this is not a full disk quota or a guarantee against concurrent disk exhaustion.

Older cached versions remain available for citation follow-ups. No real cache-version deletion or cloud garbage collection is enabled. Runtime disk use can therefore grow over repeated publications; a reviewed cache-version pruning policy remains required before prolonged production operation. Existing artifact limits, including the 512 MiB source cache, remain trial limits; larger scanned sources require separate sizing/delivery work.

## Restart behavior

The independent supervisor checks the worker's local `/healthz` every 30 seconds with a five-second request timeout. Failed liveness checks during the initial fifteen minutes do not trigger a restart. Afterwards, three consecutive failures trigger worker process-group termination and replacement. Successful probes reset the failure count. Crashes are detected separately and restarted, including during startup grace. A one-second pause limits rapid crash loops. Shutdown forwards termination and escalates to kill after 15 seconds, including rendering descendants.

R2 and Auth0 are not contacted by the liveness probe, so dependency failures alone do not trigger restarts. Fly's draft Machine policy is `always`, covering a failed supervisor. The Fly routing health check has a one-minute grace because the Fly validator caps it there; this does not change the supervisor's fifteen-minute grace.

## Publisher acknowledgement

`publish-s3` reuses the existing reviewed-build gate, immutable object writes, full streamed readback of every required object, and conditional active-pointer update. It then polls authenticated readiness every five seconds for the exact publication ID **and** manifest digest. Total acknowledgement time is capped at five minutes, including network waits. Redirects are not followed and bearer credentials are never forwarded to another origin. The readiness URL must use HTTPS and match `COOKBOOK_AUDIENCE`'s origin with the exact `/readyz` path.

A timeout returns `pending_activation` with exit code 4 and saves `pending-activation.json` in the supplied private state directory. Neither the old runtime nor uploaded/staged data is removed. Retrying the same `publish-s3` command verifies all required bytes again, awaits confirmation and records success history. `wait-active` is a diagnostic acknowledgement-only command; it performs no publication upload or success-history mutation.

Use `--browser-login` for manual Mac publishing. After upload and full readback, the command opens the approved Google sign-in using the separate Native Auth0 client and S256 PKCE. The loopback listener accepts only the exact callback host/path, random state and configured response issuer. The code exchange uses HTTPS without redirects or a client secret. The access token must pass signed issuer, audience, subject, client, scope and expiry validation; unexpected refresh tokens are rejected. Credentials stay in process memory. Login failure preserves `pending-activation.json` and returns exit code 4, so the same command can be retried. The ten-minute browser wait precedes the five-minute acknowledgement timer; token exchange/validation has a fifteen-second bound.

The alternative `--token-file` option remains available for controlled testing. Such a file must be owner-only; it is reread on each acknowledgement attempt. Do not extract a token from ChatGPT or browser storage.

Once a reviewed build and authorized publisher login are available, the command shape is:

```sh
# Load the private publisher environment using a shell environment loader.
# COOKBOOK_AUDIENCE must also be set to https://cookbook-agent.fly.dev.
PYTHONPATH=src uv run python -m cookbook.cli publish-s3 \
  --build /absolute/path/to/reviewed-build \
  --state-directory /Users/rick/cookbook-mcp-data/publisher \
  --readiness-url https://cookbook-agent.fly.dev/readyz \
  --browser-login
```

These placeholders are documentation, not authorization to upload a build. The current first trial selects only EPUB fixture books (Calibre IDs 5 and 40); the user deferred all PDF/DjVu books to the OCR follow-up. The EPUB-only build passes the quality gate with zero pending decisions. The user approved and completed this exact EPUB trial upload; additional publications remain outside that specific approval. This is not yet the final one-command full-library publisher.

The Mac environment must include `COOKBOOK_ISSUER`, `COOKBOOK_AUDIENCE`, `COOKBOOK_JWKS_URL`, `COOKBOOK_ALLOWED_SUBJECT` and `COOKBOOK_PUBLISHER_CLIENT_ID`. The approved public client ID is `ZOkrXtTQSX1j20ORYXyFAnGUBX8a8E8u`; it is not a secret. `PYTHONPATH=src uv run python -m cookbook.cli check-publisher-login` tests real sign-in and prints only a verification status, without uploading or saving a token. Provider setup and real Google/Auth0 token issuance passed the no-upload check on September 12, 2026. The process printed `login_verified` and exited; the token was not saved. Authenticated hosted readiness and ChatGPT linking remain untested.

## Deployment review artifact

`deploy/fly.trial.toml` targets existing app `cookbook-agent`, SJC, one shared CPU, 1 GB RAM, continuously available, existing `cookbook_data` volume mounted at `/data`. Runtime state is isolated at `/data/cookbook-mcp`; existing `/data/books` and `/data/cookbooks.sqlite3` are not used or modified by this code. Before cutover, the new subdirectory must be created with UID/GID 10001 ownership without recursive ownership changes to old data. This has not been performed on Fly.

The final update must explicitly target Machine `2863795a042368` and preserve volume `vol_r1jynq126n59expr`. Merely running a default `fly deploy` could create additional Machines; this draft file is not a reviewed cutover command. The subject allowlist and runtime-only S3 keys still need hosted secret configuration. No deployment, Machine restart, hosted secret update or book upload was performed during this implementation batch.

Build and validate locally:

```sh
docker build --platform linux/amd64 -t cookbook-mcp:runtime-amd64 .
fly config validate -c deploy/fly.trial.toml
```

The Docker build exports hash-pinned requirements with `uv` on the native build platform, then installs them using target-platform Python/pip. This avoids a reproduced `uv` segmentation fault under the Mac's x86 QEMU emulation. Only source and dependency manifests enter the image; credentials and books are excluded.

The old Fly volume has an independent local recovery copy: 55 files, 3,263,650,412 bytes, all matching their source SHA-256 checksums; copied SQLite integrity is `ok`. Machine/app configuration and image digest are recorded privately. Pull availability of the old image and a full application rollback execution remain untested.

## Verification and remaining gates

The complete suite passed 45 tests; subsequent targeted auth/MCP reruns passed after the audience and Host fixes. Ruff F checks and formatting pass. Tests cover authenticated and anonymous health/readiness, resource metadata for an origin audience, empty-cache recovery, atomic polling updates, source outages while serving cached content, corrupt-state quarantine/recovery, exact acknowledgement, redirect refusal, hard timeout and retry, CLI pending/success history, and real subprocess crash/hang recovery and shutdown. Watchdog timer tests use shortened intervals; production defaults remain 30 seconds, five minutes and three failures.

The final Linux/amd64 image (`sha256:49e1bf47a46a7a613dd7dbe55bf11f9b0a8ac74b0520a136ccb4a84baaa5cf37`) passed a local container check under one CPU and a 1 GiB memory limit, using a read-only root filesystem and disposable runtime storage. Generic health, anonymous MCP/readiness denial, exact resource metadata, and worker replacement after SIGKILL all passed. Idle container memory was 199.6 MiB; this empty-bucket check is not a loaded-library peak measurement. The container used only the runtime read-only R2 credential, performed no uploads, and was removed afterwards. Its temporary credential environment file was deleted. Results are stored privately at `setup/runtime-container-check.json`.

Provider tests previously verified R2 read-only runtime permissions and conditional writes. The two indefinite prefix locks were verified after dashboard reload; a synthetic `control/` update still succeeds. Existing-object lock enforcement will be checked after the approved fixture upload so permanent synthetic objects are not left in the locked namespace.

The subsequent Mac publisher sign-in implementation passed 13 new tests and the real Auth0 login check; the complete suite now passes 58 tests. Ruff F and formatting checks pass. The recorded container image predates these Mac CLI additions; rebuild from the final source before cutover.

The full-page OCR rebuild for Tu Casa Mi Casa completed with 269 pending review pages across five books; 60 tests passed after the forced-OCR implementation. The user subsequently deferred all PDF/DjVu books. The current EPUB-only build passes the quality gate with zero pending decisions; see stage-3-plan.md for the current publication. No human review decisions were applied.

Remaining gates for the EPUB-only trial include first hosted secret and deployment approval, artifact acceptance in ChatGPT, real hosted empty-volume recovery, external uptime/alerts, billing guards, local cache-version retention, and full-library publication approval.

Provider references: [Fly configuration](https://fly.io/docs/reference/configuration/) and [Machine restart policy](https://fly.io/docs/machines/guides-examples/machine-restart-policy/), checked September 12, 2026.


## Approved EPUB cutover — September 12, 2026

Updated only Machine `2863795a042368` in `cookbook-agent`, preserving SJC, shared 1 CPU / 1 GB, and encrypted 10 GB volume `vol_r1jynq126n59expr`. Deployed pinned image `registry.fly.io/cookbook-agent@sha256:a06497754c38c0ff3902d2275997ddeb7d00356085443afb168a7cbf07d226dc`. Its local 1 GB smoke check passed health, authentication denial and worker-crash recovery at approximately 201 MiB idle. The old image was successfully pulled by digest before replacement.

Created only `/data/cookbook-mcp` with UID/GID 10001 and mode 0700. Staged only the runtime read-only R2 keys and fixed subject allowlist as new Fly secrets; the publisher key remains on the Mac. Preserved old app secrets for rollback. Fly's Machine update retained old unused environment keys; every new required environment value, image, service configuration, mount and VM size was verified. Restart policy is `always`, routing uses `/healthz`, and the existing HTTPS endpoint is `https://cookbook-agent.fly.dev/mcp`. No second Machine or volume was created.

Uploaded EPUB-only publication `b7619e4f7b4348aa8d7be7b92b175ee3`, manifest digest `ad3a034d672aa34d7be03500d5d5ea1e7806a370110f94fcea79b3e0b1bfae3a`, with 353 files (466,122,713 bytes) for Calibre IDs 5 and 40 only. The runtime activated this exact publication from initially empty dedicated storage. A subsequent Machine restart and cached manifest/index integrity check passed. All 55 pre-existing volume files (3,263,650,412 bytes) remain SHA-256 identical to the independent recovery inventory. This publication is a fixture backup, not the complete library backup.

The first publisher attempt failed with an unclassified error before writing an active pointer. An isolated full remote readback passed, and retry completed upload/readback and the conditional R2 pointer update. Its authentication callback then found port 8766 occupied by the separate OCR preview server. That specific preview was moved to `127.0.0.1:8767`; its files were not changed. Publisher login resumed on the approved callback port. The Mac is currently locked, so authenticated readiness/MCP validation and success-history acknowledgement remain pending; do not report the publish as fully acknowledged. No production implementation change was needed for these operational retries.

Private evidence and exact rollback command/configuration are under `/Users/rick/cookbook-mcp-data/setup/cutover-20260912`, especially `cutover-status.json`, `machine-verification.json`, `rollback.md`, `rollback-machine-pinned.json`, `readback-reproduction.json`, and the publisher logs. `publish-and-check.py --resume` completes browser login, exact hosted acknowledgement, real MCP calls and success-history recording without reuploading the already verified publication. Tokens remain in memory. The currently waiting login process may expire after ten minutes and can be restarted with that command.

Remaining acceptance: authenticated hosted checks, ChatGPT linking and artifact behavior, external uptime/alerts, billing guards and local version-cache retention. Deferred PDF/DjVu/OCR work and broader library publication remain follow-ups.


## Authenticated hosted acceptance completed

The user completed the reopened Google sign-in. The resumed publisher verified the signed user token, then confirmed HTTP readiness for exact publication `b7619e4f7b4348aa8d7be7b92b175ee3` and manifest digest `ad3a034d672aa34d7be03500d5d5ea1e7806a370110f94fcea79b3e0b1bfae3a`. Twelve real authenticated MCP calls passed against the public HTTPS endpoint: catalog restricted to Calibre IDs 5 and 40, book/TOC lookup, section reading, source-bound citations, section artifacts, EPUB images, searches and publication information. No PDF rendering or OCR was invoked.

The resume process recorded the exact successful publication in R2 only after these checks; a separate runtime-read-only check verified both `control/active.json` and the first `control/successful.json` entry. The process exited successfully, and tokens were kept in memory. Private evidence: `setup/cutover-20260912/hosted-mcp-check.json`, `publisher-state/activation-confirmed.json`, `activation-and-check.log` and the updated `cutover-status.json`. This supersedes the temporary locked-Mac/pending-acknowledgement status above.

The hosted cutover and publisher acknowledgement are complete. ChatGPT linking and in-ChatGPT artifact acceptance are the next gate; they have not been claimed complete by this transport test.


## ChatGPT connection and EPUB acceptance — September 12, 2026

Created personal developer app `Cookbook Library` (`asdk_app_6aa61cf5a948819183031eeb7526ebef`) at the approved MCP endpoint, using the existing Auth0 ChatGPT client with `client_secret_post`. The user entered the secret directly into ChatGPT; it was not read or saved locally. Requested only `library:read` with OIDC disabled. Google sign-in and the existing read grant completed, and ChatGPT showed the connection as active. Refresh discovered all seven tools, each marked READ. Default low-risk permissions remain unchanged.

The ChatGPT conversation verified the exact active publication and both EPUB books, searched Flavor for salt, read a matching recipe section, and returned the exact publication/book/source/section citation and EPUB locator. ChatGPT reported receipt of an authenticated EPUB image block. A targeted `get_artifact` call returned `derived_text`, `text/plain`, an embedded text resource, and a visible File card in ChatGPT. No PDF/DjVu page or OCR tool was invoked. This verifies image receipt by ChatGPT only. A subsequent explicit inline-display test failed: no image appeared in the reply or expanded tool result, confirmed visually in the browser. ChatGPT incorrectly claimed the image was displayed. User-visible image delivery remains an unresolved acceptance issue.

The first unguided attempt exposed three interface issues: empty-query catalog enumeration is not described, the section ID's use as `artifact_id` is not described or advertised in section metadata, and `get_publication_info.formats` lists static supported formats rather than the active inventory. Explicit implementation-grounded follow-up inputs confirmed exact catalog enumeration and section-file delivery. These description/metadata improvements remain follow-up work before broader publication. Original EPUB downloads return `not_available_in_local_poc` and remain unsupported; this connection test does not remove that implementation limit. EPUB image associations remain document-level.

Private evidence: `/Users/rick/cookbook-mcp-data/setup/cutover-20260912/chatgpt-acceptance.json`. The user-visible test is [Test Cookbook Library](https://chatgpt.com/c/6aa61d61-90a4-83ea-bb5d-77c55793a760). To use the app in ChatGPT, select **+ → More → Cookbook Library**. No extra books were published. Broader ebook selection/publication, OCR follow-up, original-file delivery, external monitoring, billing guards and version-cache retention remain separate outstanding work.


## Inline cookbook images fixed — September 12, 2026

The image block reached ChatGPT's model but did not render in the conversation. Added a focused MCP Apps viewer to `get_image`: the versioned `ui://cookbook/image-v2.html` resource declares `text/html;profile=mcp-app`, standard `ui.resourceUri` metadata and the ChatGPT output-template compatibility alias. It renders authenticated JPEG bytes inline, with the book title and expandable document/publication/source/image citation. The UI metadata also carries the citation because ChatGPT's compatibility bridge did not expose the structured result consistently during the first visual test. Generic static HTML contains no book data. It has no external dependencies or network requests; CSP connect/resource domain lists are empty. It accepts only bounded JPEG base64 payloads, uses textContent for source metadata, and only accepts parent-frame protocol messages. Existing model image input remains available.

Deployed only the changed server module and packaged HTML atop the previously pinned EPUB runtime image, excluding unrelated concurrent OCR follow-up changes. Final Linux AMD64 image: `registry.fly.io/cookbook-agent@sha256:fe665fcc9922d409f5abf00bdd019231852bb1ee1f0da61cb4fd903d9e103e20`. The existing Machine's environment, startup, size, mount, services and restart policy were compared with the saved pre-change configuration and are unchanged. Fly reports healthy. No R2 publication or source books changed.

Validation: 11 focused official-MCP-client and authorization tests pass, including template discovery/read, private UI metadata, existing model image blocks and invalid-ID rejection. Three synthetic JavaScript bridge tests cover initialization, image-load success, metadata-only citation delivery, untrusted-message rejection and invalid payload rejection. No OCR/PDF/DjVu execution was used. In the existing ChatGPT acceptance conversation, visually confirmed the actual Flavor photo, book title and expanded exact citation with CSP enforcement enabled. This supersedes the earlier failed image-display status. The photo is associated with the EPUB document, not guaranteed to illustrate the specific recipe that led to it; the viewer states that limitation.

Private deployment evidence and rollback configuration: `/Users/rick/cookbook-mcp-data/setup/cutover-20260912/image-viewer-deploy/`. The rollback config restores the prior EPUB service image, not the deprecated original app. No public image URLs, bucket access, credentials or paid services were added. Tool-description gaps for catalog/section artifacts and original-file download support remain separate follow-ups.


## Compact photo card — September 12, 2026

Refined the image viewer into a compact photo card: 240px cropped preview (200px below 360px width), click/keyboard activation to show the complete photograph, click or Escape to restore the preview, a clean book title and “Photo from the same chapter.” Source opens a plain-language association caveat; technical document/publication/source/image identifiers stay behind a separate disclosure. Dynamic height reporting now uses actual body height and suppresses redundant updates so collapse does not leave empty space. Existing OAuth, image validation, source metadata and parent-message checks remain intact.

Deployed template `ui://cookbook/image-v3.html` in image `registry.fly.io/cookbook-agent@sha256:345edb75a00aa98929c7108c6de52b0a9f55fc4200fc8c6901801937fc1340f6`. Preserved the existing Machine configuration and publication. Four JavaScript interaction/security tests and the authenticated MCP transport test pass. In ChatGPT dark mode, visually verified the compact card, full-photo expansion, Escape collapse and source disclosure. Light/mobile-specific visual verification was not completed; an attempted local preview was blocked by the browser URL policy and removed. No workaround was used.

This is a targeted refinement using native CSS, the existing neutral palette and system font, with design variance 3, motion 1 and density 3. It preserves source provenance and the user's approved image interaction. Private deployment/rollback evidence lives in `setup/cutover-20260912/image-viewer-v3/`.

## Source captions and recipe context — September 12, 2026

The image card now leads with a publisher caption (figure caption, then image alt
text) or the nearby structurally recognized recipe title, with the book name
beneath. Nearby recipe titles are explicitly labeled as ebook context, not verified
visual descriptions. Missing captions no longer produce a generic chapter claim.
The extractor stores recipe context separately in an additive `image_context`
index table; older immutable publications remain readable without that table.

The same approved two-EPUB selection was rebuilt as publication
`97e55399bdd74f4782d30554b44b9dea`, manifest
`590083571d4eb3822431dbf2e90c548fda63ff5343f31ede2261581f51ed4383`.
It adds context for 95 images. Existing section rows, image records, and image
bytes are unchanged. Local publication, full remote checksum readback, authenticated
activation, and 13 hosted MCP calls passed, including the specific image context.
No OCR was run.

Template `ui://cookbook/image-v4.html` is deployed in image
`registry.fly.io/cookbook-agent@sha256:199023c36c90823b2627d7b6b0d74b9588e1516ba694aa1acb38557299d64ba8`.
The layer changes only the library response, server template version, and viewer;
existing Machine configuration was preserved and verified. Fourteen focused Python
tests and five synthetic JavaScript tests passed. Private build, deployment,
rollback, and authenticated publication evidence is in
`setup/cutover-20260912/image-viewer-v4/` outside Git. The older broader-module lint
findings (import order, closure style, UTC alias) were left unchanged; the new test
file passes lint.

ChatGPT app metadata was refreshed to v4. A fresh authenticated image request
against the new publication was visually verified in the existing test chat:
recipe title, book citation, and explicit nearby-recipe label all display.

## Compact expand control — September 12, 2026

Replaced the full-width photo action bar with a 30px corner overlay icon. The
whole photo remains the click/keyboard target; the accessible label and tooltip
switch between expand and collapse, and Escape restores the compact preview.
The overlay occupies no extra card height. Caption and source context are retained.

Deployed `ui://cookbook/image-v5.html` in runtime image
`registry.fly.io/cookbook-agent@sha256:e2a0c1d46f8b5f6f9900b1077cece3a2d4ac56e1a152e1180730a4ddd529ee4b`.
Five existing JavaScript checks and the authenticated MCP test pass. Machine
configuration and health were verified. ChatGPT metadata was refreshed to v5,
and the actual conversation card was visually checked: the bar is absent and the
corner icon is visible. No publication change or OCR was needed. Private rollback
and deployment evidence is in `setup/cutover-20260912/image-viewer-v5/`.

## Compact caption layout — September 12, 2026

The caption now uses two compact lines: source caption/recipe title above, book
name and a short provenance label below. Source sits at the right and expands
into the full-width details area. Reduced padding and spacing remove two default
rows while allowing long titles to wrap. The existing photo and keyboard controls
are preserved.

Deployed `ui://cookbook/image-v6.html` in runtime image
`registry.fly.io/cookbook-agent@sha256:1af5ca2a41c01c42b6988ce69c671e602727c78a7200ffde9bd0ff7789e80234`.
Five JavaScript checks and the authenticated MCP transport test pass. Verified
Machine configuration and health, refreshed ChatGPT metadata, and visually checked
the actual compact card and Source disclosure opening/closing. Publication data
was unchanged. Private deployment and rollback evidence is in
`setup/cutover-20260912/image-viewer-v6/`.

## ChatGPT renewal diagnosis — October 3, 2026

The original connection requested only `library:read`. On September 21, the user
approved and enabled Auth0 offline access for the API and rotating refresh tokens
for the ChatGPT client, with a 30-day idle lifetime and 90-day maximum lifetime.
Reconnecting showed success, but refresh-token issuance was not verified then.

On October 3, the current ChatGPT connection again required authentication.
Auth0's displayed recent history contained authorization-code exchanges and full
sign-ins, with no refresh exchanges. The user's Authorized Applications entry
showed only `library:read`, and Devices showed no linked devices/refresh tokens.
The issuer discovery document advertises `offline_access` and the refresh-token
grant. These observations point to the connection not requesting offline access;
enabling issuance at Auth0 alone did not establish renewable access.

Created and connected [Cookbook Library (renewable)](https://chatgpt.com/plugins/plugin_asdk_app_6ac13c66cad0819185e8c3769581109b)
using the existing issuer, client, and private MCP endpoint. In Advanced OAuth
settings, select User-Defined OAuth Client and `client_secret_post`; keep
`library:read` selected as a default scope and set base scopes to `library:read`
and `offline_access` (one per line). Base scopes ensure renewal is requested even
when tool-specific scope selection is used. OIDC remains disabled.

The Auth0 consent screen explicitly requested offline access. The first setup
attempt failed its token exchange as Unauthorized; that unconnected app is labeled
`Cookbook Library (incomplete setup)`. A replacement using the verified existing
client credential connected successfully. No credential was rotated or saved to
disk. ChatGPT shows the connected account and ten read tools, and Auth0 Devices
now shows one refresh token for ChatGPT Cookbook Library / Mac Chrome, compared
with none before. The 30-day idle and 90-day maximum lifetimes and rotation were
also confirmed in the client settings.

Refresh-token issuance and initial connection are verified. Automatic renewal
after access-token expiry has not yet been observed; verify a successful refresh
exchange before claiming that long-term behavior is tested. On web and mobile,
select the new renewable app. At the user's request, the three superseded entries
(`Cookbook Library`, `Cookbook Library (previous)`, and
`Cookbook Library (incomplete setup)`) were uninstalled. Only the renewable app
remains installed; its connected account remains active. Private screenshots are in
`/Users/rick/cookbook-mcp-data/setup/auth-renewal-20261003/` outside Git.

Do not add `offline_access` to the server's required access-token scopes: resource
authorization still requires `library:read`, and refresh issuance is a separate
authorization-server concern. The Mac publisher client is unchanged.

The reported iOS error is “Failed to connect to Cookbook Library. Please try again
later.” OpenAI's current [developer MCP help page](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
states that these apps are web-only, and recommends recreating the app when
refresh tokens are not being issued. However, the user confirms that this
connection works in the iOS app after authentication on the web. Treat that
observed behavior as evidence: mobile use itself is not blocked, and the failure
may concern starting or renewing authentication. After completing renewable
authorization on the web, verify continued use from iOS; do not infer that the
generic mobile error proves a platform limitation.

## Grok Bot connection — October 18, 2026

Connected the personal Grok Bot desktop app to
`https://cookbook-agent.fly.dev/mcp` as `cookbook-library`. Its chat installation
card shows **Connected · 1 Account**. Installed connectors are account-wide in
Grok Bot; use `@cookbook-library` to select it explicitly.

Created the separate Auth0 application **Grok Bot Cookbook Library**, public
client ID `tpc_tX1bQogNTi1yAVYM5Qa92z`, Native type with strict third-party
controls. The observed authorization request uses S256 PKCE. Registered only
the callback actually requested by the desktop app:
`https://www.cursor.com/agents/mcp/oauth/callback`.

Granted only the existing Cookbook Library API's user-delegated `library:read`
permission. Management API, machine-to-machine, and anonymous permissions remain
ungranted. Authorization Code and Refresh Token grants are enabled, with refresh
rotation, a 15-day idle lifetime and 30-day maximum lifetime. Grok requests
`library:read offline_access` and no client secret. Auth0 Devices shows one
refresh token for Grok Bot Cookbook Library / Mac Chrome. Automatic renewal
after access-token expiry has not yet been observed.

**Reconnect caveat:** this Grok Bot version normalizes the OAuth resource to
`https://cookbook-agent.fly.dev/`, while the existing Auth0 API identifier is
exactly `https://cookbook-agent.fly.dev`. Auth0 rejects the normalized value with
`access_denied: Service not found: https://cookbook-agent.fly.dev/`. For this
initial connection, corrected only the `resource` parameter in the app-generated
authorization URL to remove the trailing slash, retaining its client ID,
callback, state and PKCE challenge. Google sign-in, consent, token exchange and
the desktop loopback completion then succeeded. A future full reauthorization
may require the same correction; no persistent connector override was verified.
The server, canonical audience, tenant defaults, ChatGPT client and publisher
client were not changed.

Live Grok acceptance: publication information reported 59 books; catalog search
returned books; a Chop Chop lookup found Ozoz Sokoh's book, and an in-book search
returned Classic Nigerian Jollof Rice with a source-bound citation. This verifies
authenticated discovery and search, not a complete recipe read, image/card UI,
or refresh exchange. No ingestion, OCR, book publication or deployment was run.

## Transcription reports — service deployed

Deployed on 2026-10-21; see [transcription-reports.md](transcription-reports.md).
The service accepts agent reports when three secrets name a reports-only bucket:

- `REPORTS_S3_BUCKET`, `REPORTS_AWS_ACCESS_KEY_ID`, `REPORTS_AWS_SECRET_ACCESS_KEY`;
- optionally `REPORTS_S3_ENDPOINT_URL`, which defaults to `S3_ENDPOINT_URL`.

With none of them set, `report_transcription_issue` returns `reporting_unavailable`.
The service refuses to start when they are set only partly, or when they name the
library bucket or the library access key. The library runtime key stays read-only.

The reports key should be scoped to the reports bucket alone. R2's object tokens are
read-only or read & write. I am not aware of a write-only scope, so it will be
read & write on that one bucket. The server only creates objects, conditionally, and
never reads or deletes them. The Mac reads reports with a separate key for that
bucket. The owner approved bucket/key setup and the service deployment. The private
`cookbook-reports` bucket now has a bucket-scoped read/write runtime key and a
separate read-only Mac key. All three required settings and
`REPORTS_S3_ENDPOINT_URL` are present on the running Machine. The endpoint is
explicit because the reports bucket uses the default jurisdiction while the
library bucket uses the US jurisdiction. The keyword engine child does not inherit
`REPORTS_*` settings. The library runtime credential remains read-only, and the
publisher credential was not sent to Fly.

Uploading the PDF originals, about 1 GB, is a separate publication step governed
by [Host the scanned books and reports bucket](https://github.com/rickono/cookbook-mcp/issues/54).
It was not part of this service rollout. Once the scanned publication is ready and
its upload is approved, acceptance still needs a render and region zoom of the
largest scanned PDF on the existing 1 GB Machine, followed by a real hosted report
and Mac reader round trip. The current EPUB-only publication correctly rejects
transcription reports, so no synthetic report was placed in the live reports bucket.


## October 21 service rollout

The deployed image is
`registry.fly.io/cookbook-agent@sha256:cf12a1327c58f01cad3686ae46e614e9c0b6d4eea93c58c9010754681209638b`,
built from `96612b49d1fd81666552945f809c8ae2aebc94e0` on
`deploy/spec46-preserve-live-20261021`. The initial preflight refused an obsolete
volume pin before making remote changes. Fresh inspection identified the live
recipe-structure image; its 27 packaged source files matched the recipe-structure
branch exactly. That branch was merged before rebuilding, preserving whole-book
retrieval and its bounded recovery behavior alongside scanned transcription support.

Only the image changed on Machine `2863795a042368`. Its SJC placement, shared
1 CPU / 1 GB guest, encrypted 20 GB volume `vol_r68yxje08mo6q3n4`, mounts,
services, environment, metadata and restart policy match the saved before-state.
The prior image and full configuration are retained for rollback. The active
publication and model snapshot `32f3d7787d0cd991b26106c6e6eba6f1` are unchanged.

All 395 Python checks passed through the OCR sandbox with its original resource
ceilings; temporary test files used the private output mount. All 11 viewer checks
passed. After adding reports-credential isolation, all 11 model/search checks
passed again. The native x86 image build and a separate source-free, network-disabled
service startup check passed, including UID 10001, manifest cache, renderer presence,
complete synthetic reports settings, health HTTP 200 and anonymous HTTP 401.
Native build execution is required on this Mac: the unchanged prior live Typesense
binary also segfaulted under its x86 emulator.

Clean post-update verification passed. Fly's routing check passes, health is OK,
and anonymous readiness/MCP return 401. Real authenticated connected-tool checks
confirm publication information, search and a source section read. Read-only
hosted checks confirm 59 source roots, 7,266 recipes, title retrieval in all 55
recipe books without query cutoffs, all 627,907 keyword search units, current and
retained citations, source continuations, supporting work and candidate filtering.
The running service can list the reports bucket using its separate endpoint and
key; its keyword engine inherits no reports credentials.

Private receipts, build logs, the rollback configuration and the runbook are under
`~/cookbook-mcp-data/setup/deploy-spec46-20261021/`. Refresh ChatGPT/Grok app metadata
to discover the report tool and updated schemas. No scanned publication, successful
hosted report write, or largest-PDF zoom is claimed by this rollout record.

## October 21 three-book publication

With the owner's publication authorization, the active library is now
`0539a03a0bdc441282a0d3391139cdcb`, manifest SHA-256
`2c05e89ad5d159ae8942ddda6a982d13ad6ed81f1120c5878c1c31778c0f9b75`.
It adds Calibre 6, 79 and 81 to the existing 59 native EPUB books. The scanned
books contain 233, 247 and 392 physical pages and 226, 201 and 249 assembled
sections. Full coverage passes, with no blank or failed pages. The 73 unresolved
items (15, 11 and 47 respectively) remain marked, and scanned text remains
unapproved agent transcription. No new OCR, PDF ingestion or inference ran.

The service image is
`registry.fly.io/cookbook-agent@sha256:447cd6c32230d73269c7a598f520e7a4ffd83770c55b9c0a200b5f8cd5def6db`,
built from `2f85a3bfb16435f3644b2adb01f9a34cdf7c646b`. Only the image changed
on the existing Machine; guest resources, volume and other configuration match
the captured before-state. The native snapshot, 7,266 recipe records and 627,907
keyword documents are unchanged. The combined publication reuses the original
immutable keyword collection only after exact document, metadata, schema and
count checks. Correction refreshes retain the native model through the same path.

The publication quality gate and full native-model structural validation passed
inside the original OCR sandbox limits. The Python suite passed 400 checks;
93 focused checks passed after adding validator-specific receipts, and all 11
viewer checks passed. Native service startup passed before deployment. Genuine
full-validation receipts were staged under the exact Linux validator signature;
file hashes and index integrity are still checked by the runtime. The original
default receipt was retained so the prior service image remains usable for rollback.

All 11,617 unique R2 objects passed fresh streamed SHA-256 readback before the
conditional active-pointer update. The server reconstructed the new native
SQLite bytes from its checksum-verified parent plus two changed blocks, then
verified the complete new checksum. Its stored files and runtime validation passed.
Authenticated MCP checks confirmed all 62 catalog books, searches and complete
multi-page recipe reads for each scanned book, unapproved provenance, check
regions, and page/region images. The largest PDF in this publication is about
70 MiB and remains below the 512 MiB original cache; zoom renders remain capped
at 2,400 pixels. Native keyword search and source reading also passed.

Exact publication/manifest readiness and active MCP responses were confirmed
before recording successful history. The prior publication remains retained.
Publisher credentials never left the Mac. Private books, page images, transfer
and validation evidence remain under
`~/cookbook-mcp-data/publications/scanned-three-live-20261021/`; service image and
rollback receipts are under `~/cookbook-mcp-data/setup/deploy-scanned-three-20261021/`.
The remaining 15 scanned books are tracked in issue 53. Visual QA found one
section-assembly discrepancy; a genuine report was filed through the hosted MCP
and retrieved with the Mac reports-only read key. It remains pending independent
review, with no correction applied. Issue 54 retains the remaining-corpus rendering
and refresh/triage acceptance work; this publication does not claim a render of
the unpublished 136 MB PDF or completed blind triage.

## October 26 expanded scanned publication

The owner-authorized 71-book selection is active as publication
`d6e1fc69113c4571bf68e842fd031edf`, manifest SHA-256
`b701de975745cbf2cefc587ca95bcca2b785eece81c4f24019d1184b4609f31a`.
Authenticated acknowledgement and post-activation checks completed on October 27
UTC (October 26 owner local time). The six owner-held books remain excluded.
All 15 private production assemblies completed; the nine accepted new books and
the refusal-safe replacement for Calibre 81 use exact reviewed candidates.
Calibre 6 and 79 and all 59 native EPUB editions are preserved. The native edition
with EPUB and AZW3 retains both original formats and counts once.

The 12 PDFs account for 5,143 physical pages: 4,998 transcribed, one blank and
144 explicitly failed. Failed pages remain empty and unavailable content is
identified in neighboring served sections. The 4,329 unresolved items remain
explicit; limited source sampling does not establish whole-book accuracy or
content approval. No model calls or OCR were made during publication.

The exact source/native-parent audit, publication gate and full native-model
validation passed under the unchanged resource guard. The native snapshot,
7,266 recipes and all 627,907 keyword documents are retained. All 11,680 unique
objects (9,969,025,004 bytes) passed fresh full checksum readback. The three
runtime files (3,481,621,311 bytes) passed complete checksums and the genuine
Linux validator. The service image and Machine configuration are unchanged
from the three-book publication; publisher credentials stayed on the Mac.

Authenticated staged and active checks confirmed the exact 71-book catalog,
held-book exclusion, searches and section reads for all 12 PDFs, unapproved
provenance, check regions, native keyword search and native source reading.
All 24 hosted full-page and region images were visually inspected before
activation. Calibre 34 is the largest selected PDF by bytes (81,314,309);
Calibre 61 has the most pages (1,272; 80,326,576 bytes). Both render and zoom.
The 136 MB PDF is owner-held and is not claimed as published or rendered.
The 512 MiB original cache and 2,400-pixel render ceiling are unchanged.

Exact authenticated publication/manifest acknowledgement and the active MCP
checks passed before recording successful history. An independent readback
confirmed the active pointer and successful-history entry match, with the
previous mixed publication retained for rollback. The temporary processing
monitor is disabled and all owned publication jobs have exited.

The Mac's guarded refresh entry point read the existing genuine hosted report
and passed an unchanged-ledger, zero-triage readiness check with native retention.
The report remains pending: blind triage and a changed-ledger rebuild/activation
have not been accepted. Issue 54 remains open for that outstanding work.
Private receipts, source reviews and hosted images remain outside Git under
`~/cookbook-mcp-data/publications/scanned-all-20261022/` and the private production
operations directory. Final model costs were $31.1006 list and $52.3729
CLI-reported; these are not an invoice.

## October 27 real report review

The owner authorized one prepared crop to be sent through the existing Mac
Haiku 5.5 CLI, limited to three stateless calls with no retries and an immediate
stop on refusal or limit. This was a narrow exception to the model-execution
rule, not a general authorization for future host model jobs. The source-bound
crop was produced by the registered helper under the unchanged official sandbox
and shared scheduler lock. Credentials and all report/source content stayed
private.

Exactly three calls completed with no errors, refusals or retries. None matched
either the current or proposed report claim, so the immutable decision is an
owner-queue item. No correction was added to the ledger. The actual refresh
entry point then ran twice inside the official sandbox with the saved decision.
Both runs skipped further review, retained the empty ledger and reported
`unchanged`, with no crop, model, rebuild, upload or activation. Independent
readback confirmed that the live pointer and successful history were unchanged;
the 71-book selection, six holds and native inventory are preserved.

Before this review, commit `0b0e6ea` fixed report sampling after terminal reader
responses. Refusals now stop remaining samples and cannot be overridden by an
earlier majority; limits stop the run, and mixed refusal/limit metadata cannot
cause a refused report to be retried. All 71 targeted report, refresh and reader
checks passed inside the official sandbox, with Ruff and formatting checks passing.

The real review added $0.0014 list / $0.0024 CLI-reported cost, not an invoice.
Private decision, readings, owner queue and guarded refresh receipts are under
`~/cookbook-mcp-data/production/transcription/ops54-20261027/`. The report's section
boundary remains an owner-queue item; no new publication is warranted by this
decision. At that checkpoint, the changed-ledger hosted check was still unverified
and the temporary monitor was disabled. The separate review below completes that
check; this first decision and its consumed one-crop exception remain unchanged.

## October 28 supported correction refresh

The owner separately authorized one precise quantity report and at most three
fresh stateless Haiku 5.5 calls through the existing Mac CLI, with no retries and
an immediate stop on refusal or limit. The existing guarded crop was reused.
All three readings supported the proposed correction; no further model calls are
authorized by this exception. This review added $0.0014 list / $0.0021 CLI-reported,
not an invoice.

The actual refresh path rebuilt the active publication's recorded snapshot,
71-book selection and 12 frozen scanned candidates with the new ledger row.
Exactly one correction applied, with none stale or ambiguous. The separate
owner-queue item remains unchanged. Native retention and full validation passed
under the official resource guard: 59 editions, 7,266 recipe records, 627,907
keyword documents, the model snapshot and keyword fingerprint are preserved.
The source books and admitted candidate bytes did not change. A second guarded
refresh returned `unchanged` without review, rebuilding or publishing.

All 11,681 unique immutable objects passed full checksum readback. The runtime
files were staged and hashed on Fly using the measured old/new model byte delta
and the genuine manifest- and Linux-validator-bound receipt. Fresh publisher
authentication, exact readiness acknowledgement, catalog, scanned search and
reading, correction/reviewer provenance, native keyword search and reading, and
active-publication checks passed. The prior publication and successful history
remain available for rollback. Publisher credentials stayed on the Mac; no token
was saved.

Rendering acceptance included 21 byte-identical renders from the prior visually
reviewed publication, three newly inspected smaller region zooms, and a visibly
inspected full page and zoom for the correction. An earlier edge1600 region zoom
(render ceiling2400) timed out and coincided with failed health checks. One
controlled restart recovered the same Machine and image. Edge800 zoom requests
(render1600) then passed. The cause of the larger-request stall is not established,
and the smaller successes do not establish a fix; [issue 67](https://github.com/rickono/cookbook-mcp/issues/67)
tracks that limitation separately. No resource ceilings were increased.

Publication `31f4716be96146c984875e890b9d5b0c`, manifest
`24ed35bf15211e8ce17172ac274f95fde83edd776d508c2ec796934167de07fc`, completes
the supported-correction rollout check in issue 54. Scanned content remains
unapproved with 4,329 explicit unresolved items; this is no whole-book accuracy
claim. Private receipts are under
`~/cookbook-mcp-data/publications/scanned-correction-20261028/`.

## Bounded page rendering — October 28, 2026

The serving renderer admits one page request at a time. A concurrent request
returns `render_unavailable` immediately instead of waiting behind the renderer.
The verified original is pinned with a temporary hard link, allowing unrelated
image-cache access during rendering; text reads and health checks remain available.
The source cache stays at 512 MiB, requested output edges at 256–1600 pixels and
region rendering at a maximum of 2400 pixels.

On Linux, a fresh decoder process receives hard limits of 128 MiB address space,
10 CPU seconds, 16 MiB per output file and no core dumps. A 15-second wall deadline
kills its process group, including remaining descendants on both success and
failure. These are per-process serving limits, not a whole-workload cgroup or a
replacement for the required OCR VM and sandbox. Ingestion and offline OCR retain
their existing guarded entry points and ceilings. Native non-Linux serving renders
are refused; synthetic rendering replacements remain available to tests.

Nonzero exits, decoder warnings, invalid output and deadline failures return a
redacted `render_unavailable` tool error, never a partially decoded or blank image.
This is a deliberate supported bound: some published pages with expensive embedded
images cannot currently be rendered, even at a smaller output edge. Their source
text remains readable. The largest selected PDF by file size still passes page and
zoom rendering; the sampled page from the longest PDF and the incident page are
refused within the decoder budget. Supporting those pages requires separate work
within the existing capacity or a separately reviewed capacity change.

An isolated replay of the incident page at render edge 2400 used about 210 MiB
peak decoder RSS and succeeded under a 256 MiB cgroup; a 192 MiB cgroup recorded an
OOM kill. The bounded renderer refused that page in about one second, including
rejecting Poppler's decode warnings. This establishes a memory-exhaustion hazard
and its bounded behavior, but does not establish the historical production stall's
cause: no process/stack evidence was captured during that incident.

Synthetic enforcement checks cover inherited hard limits, excessive allocation,
file growth, decoder warnings, timeouts, descendant cleanup and concurrent health
and text reads. The full guarded suite passed: 459 tests. Private inputs, images
and probe evidence remain outside Git under `poc/zoom-stall-67`.

Deployed image `sha256:c4487fffb3495def3f788e27398b7304697513f93007dba4e2ec5f577ed08af4`
is healthy on the existing Machine. Its configuration is unchanged except for the
image. Authenticated hosted acceptance passed: the incident zoom returned a
bounded error, the largest-source page and zoom were byte-identical to their
previously reviewed images, and concurrent section reads, catalog search and
native keyword search/read succeeded. All 90 concurrent health probes passed.
The active publication and its counts are unchanged. No token was saved, model
called, publication activated or resource ceiling increased.

## Spec68 runtime deployment (2026-10-29)

Deployed immutable image
`sha256:23aab3aa8987757182166dc3554d1b6cc37192255f78ddf99e40affe16917695`
from source `e97bbab94e81dd18a0522245cc6b6fbc1f956c22` on
`t3/deploy-spec68-runtime`. This combines the merged spec68 implementation with
`fix/67-bounded-zoom`; every predeployment packaged source file matched that live
branch. It retains the manifest cache, whole-book Typesense/native retrieval,
scanned/report support and bounded rendering. The integration preserves terminal
reader refusal accounting and updates the shared-index activation regression to
expect pending activation after a committed remote pointer update.

The full suite passed through the mandatory OCR sandbox with unchanged ceilings:
546 tests, no OOM or PID-limit events. All 11 viewer tests and Ruff F checks passed.
The broader configured Ruff rules report 97 findings; no broad cleanup is claimed.
The existing native amd64 remote build and source-free smoke passed, including
Typesense startup, manifest-cache presence, UID, health and anonymous auth refusal.
All 38 packaged source files match the combined checkout.

Only the image changed on existing Machine `2863795a042368`. Its exact remaining
configuration, sole encrypted volume attachment and secret names/status are
unchanged. Cached publication validation completed during cold startup and Fly's
routing health passed. Public health and anonymous readiness/MCP refusal passed.
Signed synthetic in-process MCP transport acceptance on the deployed Machine
passed catalog search, native/legacy search and reads with citations. The real
active publication, control pointer/version, manifest, model identity, keyword
collection and its 627,907 documents, and transcription counts are unchanged.
Current withdrawal state is readable with existing runtime credentials and has no
recorded withdrawals. Nonempty withdrawal behavior is covered synthetically; no
production content approval, withdrawal, publication or source processing ran.
This acceptance does not claim a fresh real OAuth session or a new source-image
inspection. The existing bounded-render behavior was retained and tested in the
sandbox without rendering production pages.

Exact rollback configuration, pullable prior image, build/source hashes, guarded
test records, native smoke, before/after acceptance and verification scripts are
private under `~/cookbook-mcp-data/setup/deploy-spec68-20261029/`. Rollback uses
`python3 deploy.py rollback` there to restore the captured exact configuration on
the same Machine. No new Machine, volume, secret or publication was created.
