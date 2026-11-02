# Private reader search

Implements [Search the library and open matches in context](https://github.com/rickono/cookbook-mcp/issues/101)
under [the reader spec](https://github.com/rickono/cookbook-mcp/issues/98).
Session and deployment requirements remain in [hosted-reader.md](hosted-reader.md).
No library, dashboard, MCP, publication, rendering, reporting or OCR authority is added.

`GET /reader/search` starts whole-library keyword search. From reading,
`/reader/search?at=…` accepts the existing identifier envelope and initially selects
that book. Query changes and scope changes stay in the live form. Catalog scope
options load one bounded metadata page at a time, with explicit continuation.
Author/tag/format filters are disabled with an explanation: native Content retrieval
cannot apply those filters consistently with Section retrieval. Format remains
visible on every hit. Content-type selection explicitly excludes Section matches
and warns that interpreted classification is partial. All-material search includes
native source units as well as interpreted entities; essays and techniques need not
have their own classification to match authored text.

`POST /reader/search/results` accepts bounded JSON containing `query`, optional
`book_id`, `kind`, `publication_id`, `group=both|content|section`, `content_page`
and `section_offset`, plus the existing Reader session CSRF token. Exact Origin,
session authorization, HTTPS and private no-store headers apply. Unsupported fields
are rejected instead of silently ignored. Query-bearing GET requests are rejected.
No query is written to session storage, browser persistence, history state, URLs,
telemetry or application logs. Existing edge/client/body logging prohibitions apply
here too. The existing native keyword engine disables access/search/analytics logs.

The adapter calls `Library.find_book_content` and `Library.search` independently,
preserving each engine's order, bounds and continuation values. It resolves the
publication once before dispatch, and pins both groups and later pages to that
publication. Native keyword typo tolerance and section all-query-words matching
retain their existing differences; there is no new ranking or semantic matching.
Deduplication uses only exact reading destinations within each group, including
publication, source, section or native target/snapshot. Similar wording never
collapses distinct targets, and the two groups are never merged.

Each group returns `state=ok|unavailable|excluded|failed`, `results`, independent
`next`, coverage disclosure and optional cutoff/coverage details. Empty/short pages
retain any continuation returned by Library, including withheld section pages.
There are no invented totals. A missing native artifact means unavailable coverage,
not zero matching authored material. Errors are redacted per group; successful
results remain usable. Each group has a seven-second response deadline under the
Reader's existing ten-second request deadline. Client fetches have an 8.5-second
bound. These limits do not cancel an already running worker thread or replace its
existing serving/resource limits. A retired pinned publication returns 410 and
requires an explicit fresh search; it never silently selects current text.

Every match uses `reader_content.reading_link`. A normal click fetches the existing
reading HTML and initializes its content continuation in the same live document;
the search DOM remains detached in memory. **Return to search results** restores
query, scope, type, both result groups, independent continuations, focused match
and scroll position. Search-this-book from this reading view also retains the
query and selects the book, requiring an explicit Search to apply the scope.
Modifier-click retains the ordinary identifier-only reading link behavior.
Reload, leaving the page and expired authorization discard transient search state;
there is no saved search or cross-tab query history. The continuation script is
scoped for repeated initialization. The reading mount also initializes first-party `/reader/*.js` enhancements
declared by the trusted reading response; it keeps the existing session monitor.
Reading enhancements must support initialization for each mounted document.

All untrusted query/source/excerpt strings use text nodes. Labelled forms,
headings, status announcements, visible focus and at least 44px controls support
keyboard/screen-reader use. This is implementation intent, not an accessibility
certification or observed device rendering.

Verification uses authenticated public HTTP against hand-authored synthetic
indexes/BookModel artifacts, and Node DOM simulations. The keyword engine is an
injected external-boundary stand-in: native hit resolution, binding, paging,
cutoff and failure isolation are exercised through real Library code, but this
selection does not establish actual Typesense typo/ranking behavior. Existing
Section matching runs against the real SQLite index. No ingestion, OCR, model
inference, original rendering or hosted identity operation runs.

Remaining acceptance proof under #98: actual Typesense/mixed-publication search,
hosted login/renewal and Mac-off operation, Safari/Chromium and phone/tablet
journeys, keyboard/VoiceOver, zoom/reflow, measured hosted performance, plus
combined reading/original/report enhancements after sibling integration. Tickets
remain open for acceptance. Keep private books and raw evidence outside Git.

Verification after merging integration `3d81084094f78b6f11862a304e3ce858b033d3b9`
(including #102 originals and #105 owner reports): 103 safe Python tests passed
across reader search/content/session/originals/reports, library authorization,
hosted service, MCP, dashboard and manifest cache. Fifteen Node DOM tests passed
across search, content continuation, originals and reports. Focused Ruff checks
and formatting and `git diff --check` pass. These are synthetic checks, without
OCR or live browser/hosted/device evidence. Search discards transient state on
the shared `reader-expired` event and broadcasts it on departure, so mounted
reading enhancements can also clear their drafts.
