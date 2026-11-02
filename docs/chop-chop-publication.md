# Chop Chop publication — October 6, 2026

The user authorized adding Calibre ID 87, *Chop Chop: Cooking the Food of Nigeria*
by Ozoz Sokoh, to the existing 58-book EPUB catalog. Calibre holds both AZW3 and
EPUB. The builder now prefers EPUB for indexing while retaining all files in
the selected record's backup. AZW3-only records and ambiguous non-EPUB selections
are refused before extraction. PDF/DjVu admission and OCR isolation are unchanged.

Calibre was closed normally before a fresh, checksum-verified snapshot of the
59 selected record directories and catalog metadata. The snapshot preserves both
Chop Chop formats. Source pre/post inventories and source/copy hashes match.
This is a selected-record backup, not a complete mixed-format library backup.
Private source files, derivatives and evidence remain outside Git under
`/Users/rick/cookbook-mcp-data/publications/chop-chop-20261006/`.

Comparison with Calibre's AZW3 input extraction found identical body text after
whitespace normalization, including numeric tokens and fractions. All referenced
images are byte-for-byte preserved in the user's EPUB. Only an unused 172×240
cover thumbnail is absent; the full cover is preserved. This checks this specific
conversion's text and image preservation, not visual layout equivalence.

Publication `ba5e4b567b67400b8e8f183a628c0a51`, manifest SHA-256
`9b570555b178adf80f9c7eb36199039906b85b4ae203f7bb7f2e19b74677ad3a`,
contains 59 books, 18,139 sections and 11,446 image records. Chop Chop contributes
436 sections, 145 images and 124 resolved TOC entries. All previous books,
sources, sections, images, image context and FTS rows are preserved exactly.
SQLite integrity and the publication quality gate pass. No OCR or PDF/DjVu
ingestion was invoked.

All 11,591 objects, totaling 6,013,564,752 bytes, passed complete streamed remote
SHA-256 readback before the active pointer changed. The first attempt stopped on
a network read timeout without activating. The successful retry used a 180-second
network read timeout, four bounded transfer workers and up to three fresh
readback attempts per object. Every object was fully reverified; no checks were
skipped. Resource ceilings, hosting configuration and service code were unchanged.

The new publication passed 298 local MCP calls across all 59 books. Hosted
administrative verification confirms the exact active publication/manifest,
verified runtime index, SQLite integrity and exact selected Calibre IDs.
Seven authenticated calls through the already connected **Cookbook Library
(renewable)** app confirm the active publication, exact 59-book catalog,
Chop Chop discovery, jollof search and source-cited reading. The returned text
matches the local index exactly. The separate publisher Google sign-in wait was
stopped because the existing authenticated connection supplied this verification.
The exact successful pointer is recorded and read back in R2 publication history.

The format-selection and publication changes passed 52 targeted non-OCR tests.
Ruff F checks and formatting pass for the changed Python files. Source books are
also protected by an AZW3 Git ignore rule.

Private evidence includes `validation.json`, `conversion-comparison.json`,
`local-mcp-check.json`, `readback-audit.jsonl`,
`hosted-administrative-check.json`, `hosted-connector-check.json`, `status.json`,
and `publisher-state/activation-confirmed.json`.
The prior publication remains available for rollback. No retention cleanup ran.
