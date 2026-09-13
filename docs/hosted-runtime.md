# Hosted trial runtime

Image selection update, September 13: the existing service now exposes
`list_images` and `inspect_image` before the final `get_image` display. Live
ChatGPT checks confirm candidate inspection without image cards and a single
selected-photo viewer. Deployment details and acceptance evidence are in
[image selection](image-selection.md).

Current status, September 13, 2026: all 58 authorized EPUB records are uploaded to private R2 and active on the existing Fly Machine as publication `d9e2b701b6864ccaa4aabfd6bc04d32a`. Full remote checksum readback, hosted active-manifest/index validation, the exact 58-book inventory, and health pass. Google publisher sign-in, exact authenticated readiness acknowledgement, 293 hosted MCP calls across all 58 books, and successful-publication history verification now pass. The full build preserves the newer image captions/recipe context and resolves all EPUB TOC links; 57 books have searchable text and one is image-only. See [the full publication record](full-epub-publication.md). The full catalog has now passed authenticated transport checks. Earlier two-book ChatGPT visual acceptance and subsequent viewer deployments remain the recorded in-ChatGPT visual checks.

## Serving and updates

The container runs `cookbook supervise` as unprivileged UID 10001. Its worker, `cookbook serve-hosted`, serves Streamable HTTP on port 8000. The configured resource audience remains `https://cookbook-agent.fly.dev`; the MCP route is `/mcp`. Auth0 issuer, audience, signature, required claims, fixed subject and `library:read` scope are validated for protected requests. The publisher credential must never be placed on Fly.

`GET /healthz` returns only `{"status":"ok"}` without authentication. `GET /readyz` requires an authorized user token and returns the active publication ID and manifest digest, or HTTP 503 when no verified publication is available. Its OAuth challenge points to the resource metadata location for the configured audience. Pydantic URL construction preserves the audience's empty path, so discovery does not silently append a slash to the Auth0 API identifier. MCP Host/Origin validation explicitly permits the configured resource origin; DNS-rebinding protection stays enabled and unrelated hosts are rejected. No bucket or asset is publicly routed.

At startup, a cached publication's manifest digest, runtime file hashes, SQLite integrity, and index publication identity are checked without R2 access. Invalid active state is quarantined within the dedicated runtime directory and never reported ready. The updater immediately tries R2, then waits 60 seconds between completed checks. Failed updates preserve the last verified active pointer; successful updates stage and verify a separate version before atomic activation. Empty runtime storage is reconstructed from R2. Interrupted staging does not replace active state. A staging free-space preflight checks declared runtime byte requirements; this is not a full disk quota or a guarantee against concurrent disk exhaustion.

Older cached versions remain available for citation follow-ups. No real cache-version deletion or cloud garbage collection is enabled. Runtime disk use can therefore grow over repeated publications; a reviewed cache-version pruning policy remains required before prolonged production operation. Existing artifact limits, including the 512 MiB source cache, remain trial limits; larger scanned sources require separate sizing/delivery work.

## Restart behavior

The independent supervisor checks the worker's local `/healthz` every 30 seconds with a five-second request timeout. Failed liveness checks during the initial five minutes do not trigger a restart. Afterwards, three consecutive failures trigger worker process-group termination and replacement. Successful probes reset the failure count. Crashes are detected separately and restarted, including during startup grace. A one-second pause limits rapid crash loops. Shutdown forwards termination and escalates to kill after 15 seconds, including rendering descendants.

R2 and Auth0 are not contacted by the liveness probe, so dependency failures alone do not trigger restarts. Fly's draft Machine policy is `always`, covering a failed supervisor. The Fly routing health check has a one-minute grace because the Fly validator caps it there; this does not change the supervisor's five-minute grace.

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
