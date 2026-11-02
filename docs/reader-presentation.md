# Kitchen and responsive reading

Implements [Read comfortably in kitchen mode across phone and tablet](https://github.com/rickono/cookbook-mcp/issues/106)
under [the hosted reader spec](https://github.com/rickono/cookbook-mcp/issues/98).
Prepared from `integration/spec-98` at `aaf2ccef9c9e0108dc9514dbcfa4a1f8bec584f4`.
Existing [session](hosted-reader.md), [content](reader-content.md) and
[original](reader-originals.md) contracts remain authoritative.

The reading and original views load focused presentation assets. Default text is
18 CSS px with 1.6 line spacing and a 65ch maximum main width. The explicit,
keyboard-operable Kitchen mode toggle uses 22 CSS px text, 1.6 spacing, a 58ch
maximum width and 52px controls. Normal controls remain at least 44px. Kitchen
mode reduces the app-title size while retaining source attribution, uncertainty,
contents, return links, continuations and original actions. With JavaScript
disabled, normal reading and explicit navigation remain available; the kitchen
toggle stays hidden. There is no wake lock, scaling, completion or history UI.

Only the `reader-kitchen` boolean is stored locally. Denied browser storage leaves
the live toggle functional. No content, locations, search terms or drafts are
stored by these assets. Existing session expiry/withdrawal behavior is retained.
Reading status and appearance announcements use separate status regions.

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
They verify kitchen/skip controls, source-return envelopes, escaped table excerpts
across long-cell continuations, bounded source identity and existing security and
failure behavior. Node tests use a simulated DOM for toggle/storage denial,
focus, continuation retry, expiry, withdrawal and table regions. These are **not
observed browser, touch-device, layout, contrast or VoiceOver evidence**. No
ingestion, OCR, inference, live identity changes or deployment is performed.

Still required for acceptance: record actual Safari and Chromium versions on
desktop plus iPhone/iPad Safari or equivalent device environments. Observe the
complete reading/reference-return/original/kitchen journey at 390px phone portrait,
tablet portrait/landscape and 1280px desktop; verify 320 CSS px reflow,
200%/400% browser zoom, orientation changes during long reading and interrupted
continuation, horizontal table keyboard scrolling, focus return, status
announcements, VoiceOver reading order/labels, contrast and measured 44px/52px
touch targets. Observe a successfully decoded supported original in the assembled
application. The parent release also still needs hosted login/actual renewal,
Mac-off operation, Linux serving enforcement and specified performance/failure
budgets; this slice claims none of that proof. Keep raw/private evidence outside
Git and GitHub.
