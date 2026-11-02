# Responsive reading

Implements [Read comfortably in kitchen mode across phone and tablet](https://github.com/rickono/cookbook-mcp/issues/106)
under [the hosted reader spec](https://github.com/rickono/cookbook-mcp/issues/98).
Prepared from `integration/spec-98` at `aaf2ccef9c9e0108dc9514dbcfa4a1f8bec584f4`.
Existing [session](hosted-reader.md), [content](reader-content.md) and
[original](reader-originals.md) contracts remain authoritative.

The owner removed kitchen mode during local preview feedback on 2026-11-02.
This supersedes the original #106 toggle requirement. There is one reading
presentation, with no mode toggle or locally persisted appearance setting.
Reading and original views retain focusable source returns, labelled horizontal
table regions, wrapping navigation, and accessible controls. The default remains
18 CSS px with 1.6 line spacing and at least 44px controls pending UI polish.
Existing session expiry and withdrawal behavior remain authoritative.

Native JSON adds `text_blocks`: ordered `{kind: text|table, text: string}` excerpts
whose concatenation is the existing `text`. The adapter classifies the bounded
delivered nodes against immutable source table intervals, including continuations
starting inside a cell and namespace-qualified EPUBs with anonymous XPath names.
This is a read-only metadata query against the existing BookModel; it retrieves
no extra source text. Shared MCP/retrieval response contracts are unchanged.
Escaped server markup and `textContent` continuation inserts use labelled,
keyboard-focusable horizontal regions for table excerpts. They preserve existing
cell boundaries and spanning-cell notes without inventing a semantic grid or
reconstructing EPUB layout. Scanned plain text remains wrapped; no table structure
is guessed from punctuation. The same projection serves original comparison.

Text wraps independently of table overflow. Fluid widths, wrapping navigation,
breakable identifiers and no fixed-height or sticky reading chrome support narrow
views and browser zoom. No resize/orientation handler reloads content or resets
scroll. Continuations retain existing chunks on failure and focus the newly
loaded chunk only after success. Explicit original and authored-reference returns
focus the source text anchor. Original selection and recovery carry the validated
optional `back` identifier envelope, preserving the authored-reference return
through a text/original round trip. Neither return value accepts an arbitrary URL.

## Verification and outstanding acceptance

Safe checks use the assembled authenticated HTTP application with hand-authored
synthetic publication/BookModel records and injected identity/rendering outcomes.
They verify skip controls, source-return envelopes, escaped table excerpts
across long-cell continuations, bounded source identity and existing security and
failure behavior. Node tests use a simulated DOM for
focus, continuation retry, expiry, withdrawal and table regions. These are **not
observed browser, touch-device, layout, contrast or VoiceOver evidence**. No
ingestion, OCR, inference, live identity changes or deployment is performed.

After merging integration commit `cb86444853f6ae83637f53014aeaa2b367137fe1`,
the safe Python selection passed **115 tests**, with **six Linux-only serving
rendering tests skipped** on macOS. Selection: `test_reader_presentation`,
`test_reader_content`, `test_reader_original`, `test_reader_http`,
`test_library_auth`, `test_hosted`, `test_mcp`, `test_dashboard`,
`test_manifest_cache`, `test_rendering`, `test_reader_search`,
`test_reader_updates` and `test_owner_reports`. The six reader/search/update/report
Node files passed **21 simulated DOM tests**. Focused Ruff lint/format and
`git diff --check` passed. Merge resolution retained sibling search/report/update
implementations and changed only the update script's reading-status selector to
avoid the separate appearance announcement region.

Still required for acceptance: record actual Safari and Chromium versions on
desktop plus iPhone/iPad Safari or equivalent device environments. Observe the
complete reading/reference-return/original journey at 390px phone portrait,
tablet portrait/landscape and 1280px desktop; verify 320 CSS px reflow,
200%/400% browser zoom, orientation changes during long reading and interrupted
continuation, horizontal table keyboard scrolling, focus return, status
announcements, VoiceOver reading order/labels, contrast and measured 44px
touch targets. Observe a successfully decoded supported original in the assembled
application. The parent release also still needs hosted login/actual renewal,
Mac-off operation, Linux serving enforcement and specified performance/failure
budgets; this slice claims none of that proof. Keep raw/private evidence outside
Git and GitHub.
