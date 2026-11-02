# Bookmarks and remembered locations

Implements [Bookmark and resume reading across devices](https://github.com/rickono/cookbook-mcp/issues/104)
under the [hosted reader specification](https://github.com/rickono/cookbook-mcp/issues/98).
These are synthetic HTTP/DOM checks, not hosted or device observations.

Reading offers an optional plain-text bookmark name, save acknowledgement, and an
explicit Remember this location action. Bookmarks has refresh, open, rename and
remove controls. Names are limited to 120 characters, Unicode normalized, stripped
of control/format characters and whitespace normalized. UI uses textContent/value;
no personal values are placed in links, logs, localStorage, sessionStorage, caches
or history state. Only identifier envelopes appear in reading URLs.

A visible newly mounted stable section/target automatically remembers its start.
It initializes once per mounted reading document, including search's dynamically
mounted reading responses. Background mounts, focus, session checks, scroll,
continuations and back/forward restoration do not update progress. Remember is an
explicit way to accept the displayed section again. Contents views and withheld
views do not automatically replace progress. This stores one source location per
owner/book/source edition, without percentages, completion flags or history UI.

Catalog Open book uses `GET /reader/book?at=…` and offers Resume this edition when
one exists, alongside explicit contents. Explicit `/reader/read?at=…` links,
search matches, authored references and bookmarks always bypass resume. There is
no automatic redirect to a different remembered target. Bookmarks and resume use
`reader_updates.source_location` on creation and `resolve_current` when offered:
unique section locator evidence or exact native snapshot/reading occurrence is
required. Unavailable references remain stored and labelled; nothing guesses a
replacement edition or stores book text. Copied reading links remain exact.

## HTTP and persistence

`GET /reader/personal` lists bookmarks and remembered locations with current
resolution (`available|unavailable`, opaque `at` or null). `POST /reader/personal`
accepts JSON with `csrf`, a random 32-hex `operation_id`, and one action:

- `save`: identifier envelope `at`, optional-name value `name` (empty is allowed).
- `rename`: `bookmark_id`, `name`.
- `remove`: `bookmark_id`.
- `resume`: stable section/target `at`.

The existing exact HTTPS origin, current owner authorization, no-store response,
CSRF/Origin and expiry boundaries apply. Bodies are bounded to 16 KiB. Unknown
fields are refused. A shared `reader-expired` event clears personal drafts and
pending attempts; sign-in never replays a mutation. Controls require JavaScript.

One conditional owner-record write commits metadata, monotonic revision and the
operation fingerprint/result together. Competing replicas retry CAS collisions
within a bounded eight attempts; the last accepted server write wins. Client
clocks are irrelevant. A matching operation retry returns its durable result
without reapplying it over newer navigation or restoring removed bookmarks.
Changed reuse returns 409. Success means a confirmed durable write or confirmed
prior accepted operation. Timeout/storage ambiguity returns 503
`persistence_unconfirmed`; the UI freezes the original payload/id for explicit
retry and never claims failure means rejection. No automatic mutation retry occurs
in the browser. Disabled configuration returns `personal_unavailable`.

Admission caps each owner at 1,000 bookmarks and 10,000 accepted operations; it
returns `metadata_limit` (429), without evicting references or idempotency evidence.
Capacity expansion/migration is operational work, not silent retention expiry.

## Separate storage authority

Set all three values to enable storage:

- `PERSONAL_S3_BUCKET`
- `PERSONAL_AWS_ACCESS_KEY_ID`
- `PERSONAL_AWS_SECRET_ACCESS_KEY`

Optional `PERSONAL_S3_ENDPOINT_URL` defaults to `S3_ENDPOINT_URL` (HTTPS required by
the shared S3 factory). Partial settings fail startup. Bucket and access key must
each differ from library, session, agent-report and owner-report authority. Reader
configuration must also be present. No deployment or identity changes are made.

Grant GetObject/PutObject only on `reader-personal/owners/*`, with strong read
consistency and conditional create/update. No list/delete/publication/correction,
approval, session or report authority is needed. Owner object keys are SHA-256
identifiers; identifiers supplied by browsers never become storage paths. Use a
private encrypted bucket and confidential independent backups. Keep records and
backups independently of publication retention; no expiry lifecycle on metadata.
The library runtime credential remains read-only. LocalStore is synthetic-test
infrastructure, not a hosted fallback. Accepted-operation entries contain only a
fingerprint/result; records contain no access tokens, CSRF values or book text.

## Proof still required

`tests/test_reader_personal.py` uses two authenticated sessions through the
assembled HTTP app and shared durable synthetic storage. It covers restart,
rename/removal, idempotency, competing writes, pending durability, lost responses,
expiry/CSRF/privacy, current-source recovery and retained unavailable references.
`tests/reader_personal.test.mjs` exercises mounted initialization, background-tab
resistance, frozen ambiguous retries and expiry through a synthetic DOM/fetch seam.
No ingestion, parsing, OCR, rendering or inference runs in these checks.

Real hosted restart/replica durability, least-privilege grants and backup recovery,
login/renewal, Mac-off operation, Safari/Chromium, phone/tablet reflow, keyboard,
VoiceOver and performance evidence remain acceptance work under #98.
