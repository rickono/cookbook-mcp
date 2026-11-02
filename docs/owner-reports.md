# Owner transcription observations

Implements [durable owner reports](https://github.com/rickono/cookbook-mcp/issues/105)
under [the reader specification](https://github.com/rickono/cookbook-mcp/issues/98).
Session and deployment prerequisites remain in [hosted-reader.md](hosted-reader.md).

The scanned section reading page offers a labelled, collapsed report form without
loading an original. A description of 1–1,000 characters is required; proposed text
(up to 1,000 characters) and a normalized region are optional. The region describes
the referenced source pages; no crop, image request or source text is required.
Submission records an `owner-observation.v1`, with an explicit owner reporter.
It does not change text, ledger, eligibility, publication or uncertainty and starts
no OCR, triage or review. The legacy `transcription-report.v1` agent interface and
its exact quote/differing proposal requirements remain unchanged. Its offline
reader cannot enumerate these observations from its separate bucket.

`POST /reader/reports` accepts JSON with `csrf`, `reference`, `submission_id`,
`description`, optional `proposal` and optional `region` ([left, top, right, bottom]).
It requires the current authorized reader session, exact HTTPS origin and exact
Origin/CSRF checks. Requests are bounded to 16 KiB. Responses retain private
no-store, no-referrer and the reader security headers. No description appears in
URLs, logs, returned markup or browser persistence. Without JavaScript the form
posts rather than putting fields in a URL, but JSON intake requires JavaScript.

The encrypted authenticated reference is issued only after shared Library source
validation. It contains the owner, edition/book/source hash, physical pages,
section/chunk location, exact publication and extraction version; it contains no
book text. It is not authorization. An authenticated owner may submit this same
binding after retirement or withdrawal without rereading or disclosing withdrawn
text. A fabricated identifier envelope cannot replace the authenticated reference.
Retain the reader encryption key across replicas/restarts to retain outstanding
bindings; key replacement invalidates old bindings and requires a deliberate
migration policy. There is no automatic reference expiry tied to publication
retention. Reporting still requires a live authorized session.

The tab generates one random 128-bit submission identifier before the first
attempt and retains it and the frozen payload only in memory. The owner and
identifier determine an atomic create key. Reference and payload determine a
separate fingerprint. Only confirmed durable creation or a matching durable prior
record returns `received` and the same receipt identifier. Changed reuse is 409
and never overwrites. A receipt means received and unverified.

Reporting disabled is 503 `reporting_unavailable`; storage/write/timeout ambiguity
is 503 `receipt_unconfirmed`; concurrent admission exhaustion is 503 `report_busy`;
rate limits are 429 `rate_limited`; invalid input is 400. Retry the same identifier
and original payload explicitly. A durable prior receipt is checked before rate
admission, so accepted reports remain recoverable at the limit. Admission uses
shared conditional writes, defaults to 60 distinct identifiers per owner per UTC
hour, and reserves attempted identifiers even if their final write fails. This
conservative limit never evicts a receipt. The intake write wait is bounded to
eight seconds inside the existing ten-second request bound; a timed-out storage
worker may still finish, so timeout never proves the report was rejected.

The UI announces unconfirmed timeouts, limits, unavailable reporting and conflicts
separately. Recoverable failure retains the draft in the live tab. Expiry clears
it, returns to sign-in with only the opaque reading destination and never resends.
The generic session-expiry notification also clears a draft awaiting explicit retry.

## Reports-only storage configuration

Set all three optional values to enable owner reporting:

- `OWNER_REPORTS_S3_BUCKET`
- `OWNER_REPORTS_AWS_ACCESS_KEY_ID`
- `OWNER_REPORTS_AWS_SECRET_ACCESS_KEY`

Optional `OWNER_REPORTS_S3_ENDPOINT_URL` defaults to `S3_ENDPOINT_URL` and requires
HTTPS. Partial settings fail startup. The bucket and credential must each differ
from the library, session and legacy agent-report bucket/credential. Disabled
reporting leaves the form available with a truthful unavailable response.

Provision a private encrypted reports-only bucket with strongly consistent reads
and conditional create/update. Grant this credential GetObject/PutObject only on
`owner-observations/receipts/*` and `owner-observations/limits/*`. It needs no list,
delete, library, session, publication, correction or approval authority. Operational
policy must prevent deletion/overwrite of accepted receipt objects; application
writes to receipts are create-only. Rate objects require CAS updates. Do not attach
an expiry lifecycle to receipts. Hourly limit objects may be cleaned after the
hour ends; a generous clock-skew buffer is appropriate. Back up observations
independently of publication retention, keeping owner descriptions private.
No deployment, bucket provisioning or identity changes are performed here.

## Verification and remaining proof

`uv run pytest -q tests/test_owner_reports.py` exercises the assembled public HTTP
boundary using synthetic publications, identity and stores. It includes a separate
synthetic 503 original response followed by description-only submission, removes
the retained manifest to establish retirement, and simulates a durable receipt
write followed by a lost response. It proves retry, restart, conflict, rate limit,
expiry, CSRF, malformed references and storage configuration separation. A delayed
receipt write and concurrent identical request establish durability before
acknowledgement and convergence on one receipt. Existing
reader, MCP, legacy report and dashboard selections provide regression coverage.
No real rendering, ingestion, OCR or inference is used.

`node --test tests/owner_reports.test.mjs` exercises report form events using a
synthetic DOM/fetch boundary: ambiguous retry, unavailable/limited states, frozen
payloads and active/passive expiry clearing. These are browser-script behavior
checks, not an observed Safari/Chromium/device or accessibility journey. Real
hosted durability, least-privilege grants, login/renewal, Mac-off operation,
keyboard/VoiceOver, device reflow and performance remain parent acceptance proof.

Verified locally: 102 Python regression checks plus the subsequently added
concurrent HTTP check (five report tests total); 18 Node script checks. Focused
Ruff lint/format and `git diff --check` pass. No device or hosted evidence is claimed.
