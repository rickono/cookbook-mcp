# Full EPUB publication — September 12–13, 2026

The user authorized publishing all 58 current Calibre EPUB records after the two-book ChatGPT trial passed. PDF/DjVu ingestion and OCR remain deferred. This authorizes the EPUB snapshot, extraction, private R2 upload, and hosted activation; no new infrastructure or changed resource ceilings are needed.

## Scope and evidence

Calibre was quit normally before copying. The fresh snapshot contains 176 files: the 58 selected record directories and catalog/preferences metadata. All source/copy SHA-256 hashes match, and the source pre/post stat inventories match. The catalog passes SQLite integrity checking. The EPUB originals total 4,183,913,078 bytes.

The snapshot and publication are EPUB-only backups. Their copied catalog also references unselected PDF/DjVu records; this is not a complete mixed-format Calibre library backup. Source books and private evidence remain outside Git under `/Users/rick/cookbook-mcp-data/publications/epub-full-20260913/`.

Calibre ID 76, *Alain Passard The Art Of Cooking With Vegetables*, is image-only: its HTML contains images and no body text. It is included in the catalog and original/image backup, but full-text recipe search requires future OCR. The other 57 EPUBs contain extracted text. No OCR, PDF ingestion, or model inference was run for this publication.

## Fixes exposed by the full corpus

- *The Dead Rabbit Drinks Manual* repeats a document in its spine. Extraction now indexes that document once, preserving its first spine position and existing source-bound IDs, rather than failing on duplicate section IDs.
- Nested TOC anchors with no intervening text previously lost all but their first target. Extraction now records every anchor in each section. This fixes ten links across three books.
- Repeated references to an image within a section now produce one image ID in that section.

Synthetic regressions exercise duplicate-spine indexing and nested empty anchors. EPUB extraction tests and publication/auth/storage/MCP tests pass without invoking OCR. The publisher supports an optional bounded transfer worker count (one by default, maximum four) with progress callbacks. It verifies all local inputs, performs full remote SHA-256 readback, and updates the active pointer conditionally only after every transfer succeeds. Tests cover corrupted readback preserving the previous pointer and a successful verified retry with one and four workers.

## Validation and activation

The first complete build passed 293 local MCP calls covering catalog pagination, all 58 books, source-bound reading, section artifacts, images, and text search for the 57 text-bearing books. Its 17,703 sections and 11,301 images occupied a 128,204,800-byte index.

A Linux/amd64 benchmark of the full corpus under one CPU and a 1 GiB memory limit passed without OOM: cgroup peak 377,122,816 bytes, runtime restoration 2.69 seconds, search p50 359 ms and p95 535 ms. This was the complete pre-anchor-fix build; final build validation and authenticated cloud activation are recorded below. The Fly volume had 6,468,704 KiB available before the update; no resizing was performed.


## Active full publication — September 13

Publication `d9e2b701b6864ccaa4aabfd6bc04d32a`, manifest SHA-256 `f857bbc34b1edf6b813d204176b60139ef517c6dd2b819c8c236b6e925854557`, is uploaded and active. All 11,442 objects, totaling 5,780,839,749 bytes, passed complete streamed remote SHA-256 readback. The final index has 58 books, 17,703 sections, 11,301 image records, 221 image-context records, and zero unresolved TOC links. All 95 image-context records from the newer two-book trial are preserved exactly. The final build passed 293 local MCP calls including caption/context checks. The 51-test EPUB/publication/auth/storage/MCP selection passed; two additional partial-download retry cases passed, including failure after all three attempts preserving the old active pointer. Ruff F checks and formatting pass.

The initial full-library attempt correctly stopped on an active-pointer conflict: another task published the two-book image-context update during transfer. The full build was rebuilt to preserve that update; only the index and quality report changed. Existing original/image objects were reused. A subsequent full readback encountered a network timeout. The successful retry used a 60-second network read timeout and at most three fresh full-object readback attempts for connection-closed/read-timeout errors. A retry starts its hash from byte zero. Checksum failures are not suppressed. CPU/memory ceilings and OCR isolation were unchanged.

The publisher used an object listing to avoid repeated existence HEAD calls for already stored objects. This only optimizes existence checks: every local input is hashed, missing objects use create-only PUT, and every required remote object receives complete checksum readback before activation.

Administrative verification on Fly confirmed the exact active pointer, matching manifest/index hashes, SQLite integrity, and all selected Calibre IDs. `/healthz` returns OK. The existing Machine, latest image-v6 runtime, and volume were retained. The predecessor `97e55399bdd74f4782d30554b44b9dea` remains preserved for rollback; the full publication is now first in authenticated successful-publication history.

**Complete:** the user completed a reopened Google sign-in after the first login window expired. The publisher verified the signed token and exact hosted publication/manifest digest, then passed 293 authenticated MCP calls across all 58 books. Checks cover catalog pagination, source-bound reading, section artifacts, images/captions/recipe context, and text search for all 57 text-bearing books. It recorded and read back the exact successful pointer in R2; the process exited successfully. No books were reuploaded during this acknowledgement-only resume.

Private evidence is in `/Users/rick/cookbook-mcp-data/publications/epub-full-20260913/`, particularly `build-4/`, `validation.json`, `local-mcp-check.json`, `publish-3.log`, `hosted-administrative-check.json`, `activation-base.json`, and `publisher-state/pending-activation.json`.

The completed acknowledgement-only resume command was:

```sh
PYTHONPATH=src uv run python -u /Users/rick/cookbook-mcp-data/publications/epub-full-20260913/publish_and_check.py --resume
```

Tokens remained in process memory and were not saved. Final evidence is in `resume.log`, `hosted-mcp-check.json`, `publisher-state/activation-confirmed.json`, and `status.json`. The full catalog is uploaded, active, and verified; the image-only Alain Passard EPUB still awaits the separate OCR follow-up.
