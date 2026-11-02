# Source-bound hosted reading

Implements [Read complete source-bound content from the catalog and dashboard](https://github.com/rickono/cookbook-mcp/issues/100)
under [the reader spec](https://github.com/rickono/cookbook-mcp/issues/98).
Configuration and session/security prerequisites remain in [hosted-reader.md](hosted-reader.md).
This is implementation and synthetic verification, not hosted/browser/device proof.

## Reading contract

`reader_content.reading_link(citation)` builds `/reader/read?at=…` from publication,
book, source and optional section or native target/snapshot identifiers. The URL-safe
opaque envelope contains identifiers and bounded continuation state only: no titles,
source text, resource paths, search terms, credentials or monitoring payloads.
It is a reference, not authorization. Never use it to accept an arbitrary return URL.
`decode_location` rejects unknown fields, mixed retrieval paths and unbound native
cursors. All content delivery requires the existing reader session and exact HTTPS
origin, with private no-store, no-referrer and the existing restrictive CSP.

- `GET /reader/read?at=…`: focused server-rendered reading or book contents. Source
  and trust details and contents are labelled collapsed controls. `back=…` is another
  validated identifier envelope for explicit reference return to the same chunk.
- `GET /reader/content?at=…`: the same authorized, bounded delivery as JSON for
  explicit text continuation. `state` distinguishes `contents`, `partial_text`,
  `complete_text` (end reached), and `withheld`. `next_text`, `next_related`, and
  `next_contents` are independent opaque destinations. Null alone means exhaustion
  of that particular delivery, never semantic completeness of a recipe.
- Legacy/native indexed sections use `Library.get_book`, `read_section` (4,000
  characters) and `section_navigation` (20 authored targets). Adjacency comes only
  from retained contents. Scanned citations keep physical-page bindings, unresolved
  markers, review reasons, ordered applied corrections and check-region geometry.
- Native editions with a whole-book artifact use `get_book_structure` and
  `read_book_content`, retaining their default 16,000-byte/100-node bounds. Cursors
  remain bound by BookModel to publication, snapshot, target, source parts and reading
  occurrence. Repeated document occurrences remain separate contents targets.
  Native related records use the API's independent 16-record pagination without a
  text cursor; a cursor view obtains that metadata via a second bounded read with
  one node. It does not replace or advance the text cursor. Source references are
  exposed separately as `references`; unresolved/external targets are labelled and
  cannot load arbitrary resources. An unknown target occurrence is not guessed.
- The native browser projection retains ordered text, block and table-cell
  boundaries; spanning-cell metadata is disclosed beside the text. It does not
  reproduce EPUB CSS. Raw bounded native nodes and source-part citations remain in
  JSON for later original/source comparison. Interpretation/coverage remains distinct
  from approval. Unapproved native content is explicitly labelled.

The generic continuation script appends through `textContent`, advances only after
success, preserves earlier chunks on recoverable failure, focuses the new chunk and
updates navigation return destinations. Authored references from later bounded native
chunks append as text-safe controls in source order, with stable source-derived
identifiers suppressing overlap/retry duplicates. Each keeps its originating
chunk envelope and returns to that chunk's text; unresolved targets remain labelled
and non-clickable. Initial authored reference controls keep their original return
destination as later text loads. No automatic retries or whole-book preload
occur. Without script, explicit chunk links remain usable. Final-chunk wording does
not claim that earlier chunks are all present in the current document. Withdrawn text
is empty under shared Library rules; a continuation encountering withdrawal clears
previous text in that live view. Session expiry clears the view and preserves only
an opaque login destination. Login transaction storage binds that destination through
OAuth; no mutation is replayed after sign-in.

Retained publications are attempted exactly. Missing/retired publication is 410,
unknown/mismatched source location is 404, malformed destination is 400, and a
technical/session-storage failure is a redacted retryable 503. HTML failures retain
an explicit retry link to the exact destination. No fallback publication or edition
is selected. Rich update choices, originals, personal state, owner reports and
kitchen controls belong to #102–#106; #101 can reuse the citation-to-link contract.

## Dashboard entry

The separate local dashboard accepts optional `reader_origin`, an exact HTTPS
origin. Current successful index/catalog observations carry only publication,
book and source identifiers into their metadata facts. Inventory and book details
show **Open in library reader** only for those current catalog facts; unprocessed,
stale or identifier-incomplete entries have no link. Membership does not promise
available or approved text. No reader content request is made by the dashboard.
Host/origin restrictions and loopback binding are unchanged. See [dashboard.md](dashboard.md).

## Prerequisite provenance

The prepared base `fa890f1d1d8a3569048089e28bd01faa0943ebcc` contained #99 and
scanned support, but lacked the deployed native retrieval and dashboard. Under
explicit parent instruction, this branch merges combined deployed runtime
`02f618aa1278e9f51f9468ca432c1a2dc636e9f3` in merge `afbe5d6`.
That brings existing BookModel/build/search and bounded serving-render infrastructure,
its source documentation and regressions. Hosted factory/entry-point conflicts were
resolved by keeping both native search-engine lifecycle and #99 reader/session,
trusted-proxy and storage separation configuration. No inference or ingestion ran.
OCR admission policy, launcher and guard code remain unchanged.

The dashboard prerequisite was uncommitted #86 implementation in the original
`integration/spec-68` working tree at `0384b358d2f51e5ef2ad54c64e72f4291366adf0`,
as documented in [the #86 resolution](https://github.com/rickono/cookbook-mcp/issues/86#issuecomment-6548056055).
Copied only its `src/cookbook/dashboard/` package, `usage.py`, dashboard tests and
user documentation. Added the launch entry points and optional injected telemetry
wrapper required by those existing tests; no reader telemetry was added and no
producer was enabled. Original working-tree files were left untouched. No prototype,
private configuration, source book or operational evidence was copied.

## Verification and remaining proof

Safe HTTP checks use hand-authored synthetic publication/index/BookModel records,
synthetic JWTs and identity-provider responses, and external-store failures. No
capture, EPUB/PDF ingestion, OCR, model inference or original rendering occurs in
these fixtures. They cover both paths, repeated occurrences, UTF-8 continuations,
foreign cursor/source refusal, independent native/scanned relationships, reference
return, escaping, withdrawal, unavailable publication, retry, login return, privacy,
dashboard links and existing MCP/session behavior. Node tests simulate DOM actions
for continuation/retry/expiry/withdrawal; they are not an observed browser journey.

Actual Safari/Chromium and phone/tablet rendering, keyboard/VoiceOver, reflow/zoom,
hosted login/renewal, Mac-off operation, original delivery and performance budgets
remain release proof under #98. Linux rendering enforcement tests require Linux;
no rendering/OCR boundary or resource ceiling was relaxed for this work.

Verification on this branch: the combined safe Python selection in
`tests/test_reader_content.py`, `test_reader_http.py`, `test_dashboard.py`,
`test_library_auth.py`, `test_hosted.py`, `test_mcp.py`, `test_manifest_cache.py`
and `test_rendering.py` passed **89 tests**; six Linux-only rendering checks were
skipped on macOS. The reader/image/recipe Node selections passed **14 tests**.
Focused Ruff lint and formatting pass for authored/edited modules and new tests;
`git diff --check` passes. Repository-wide Ruff also reports 77 inherited findings
in untouched and imported baseline files (including prototype naming, loop
closures and older test imports); these were not mass-reformatted in this slice.

## Publication updates and saved-location contract (#103 / #104)

`GET /reader/updates?at=…` uses the same session, origin, timeout and private
response boundary as reading. It returns `state=available|unavailable`,
`current_publication_id`, opaque `at` (null when unavailable), and `pinned_state`.
It returns no book text and never selects a replacement edition. The script checks
on focus/pageshow and each minute; only an explicit **Open current text** link
navigates. Existing text/continuations stay publication-bound. Withdrawal learned
by a check clears loaded text and continuation; original authorization is untouched.
The destination publication is displayed and the explicit link targets the focusable
text article. A newer publication arriving after the notice yields another pinned
view with another notice, not a race-dependent substitution.

For #104, `reader_updates.source_location(library, decoded_location)` validates a
reference server-side and returns an identifier-only durable location. Store that
value, not the text/citation projection. `resolve_current(library, location)` returns
the same resolution object as HTTP. It uses one observed current publication and
rechecks available text through Library. Transient exceptions propagate to the
existing redacted retryable 503 boundary; unavailable references must be retained
by the personal-state caller. Neither function writes personal state.

A section requires the same book/source identity, section identifier and a matching
SHA-256 `source_key` of a unique retained source locator. EPUB locators need a
document and anchor; page locators need a physical page. Bare page lists and
unknown locators are insufficient. Duplicate locators, changed IDs/locators, or
missing evidence return unavailable. This intentionally permits false negatives
rather than inferred mappings. Native targets require the same model snapshot and
exact target (including reading-occurrence IDs); a changed snapshot is unavailable.
Cursors, chunk offsets and pagination never migrate: updates restart the identified
section/target. No title, wording, page-overlap or cross-edition matching occurs.

Reading JSON adds `source_location` and `update`. The page's **Link to this location**
and the live address bar retain source evidence; text continuations retain it too.
Copied older envelopes without evidence still attempt their exact publication;
while retained the server can verify their source. Once retired, missing evidence
is unavailable. A durable source key can recover after retirement only if the
current unique locator still agrees. Keys are references, never authorization or
storage paths. These fields survive the existing validated opaque sign-in return.

Synthetic HTTP tests switch and retire publications, withdraw scanned text, refuse
changed locators/editions/snapshots and retain distinct native occurrences. Native
fixtures are hand-written SQLite records validated by the production publication
boundary; no parsing, ingestion, inference, OCR or rendering is run. Node DOM tests
exercise passive notices, focus-preserving repeated checks, withdrawal and expiry.
Actual browser/device/accessibility, hosted login/renewal and Mac-off evidence
remain acceptance work under #98; no such observations are claimed here.

After merging integration/spec-98 through `3d81084` (originals and owner reports),
the safe Python selection in `test_reader_updates`, `test_reader_content`,
`test_reader_http`, `test_library_auth`, `test_hosted`, `test_mcp`, `test_dashboard`,
`test_owner_reports` and `test_reader_original` passed **89 tests**. Node selections
`reader_updates`, `reader_content`, `owner_reports` and `reader_original` passed
**13 tests**. Focused Ruff lint/format and `git diff --check` pass. Passive update
checks preserve session inactivity expiry and dispatch the shared expiry event to
clear report drafts. `current_publication_id` is null when no valid current
publication exists; an exact retired link remains 410 in that case. Storage outages
still use the existing redacted 503 response. No ingestion/OCR/model/rendering work,
deployment, live identity change or issue-tracker mutation was performed.
