# Stage 2 local proof of concept — September 11, 2026

**Subsequent approved update:** rotation/deskew correction and required review of suspicious OCR are implemented. See [OCR review results and workflow](ocr-review.md). The measurements and initial limitations below describe the original POC publication; they are retained as historical evidence.

The approved five-book POC is implemented and locally tested. It demonstrates authenticated MCP content delivery, extraction/search/citations, checksum-verified immutable publication, failure isolation, and empty-destination recovery. It is not a deployed service, a complete-library backup, or proof of ChatGPT compatibility. No cloud resources, public endpoints, Auth0 tenant, Google client, or book uploads were created.

## Measured fixture results

Publication: `824f0f2aa44b4de8a717fb726649a491`. The original verified snapshot remains unchanged: all 173 files / 3,817,690,346 bytes were rehashed after the POC with zero differences.

| Approved book | Format | Sections / physical pages | Characters | Extracted images | Pages with OCR text | OCR-empty pages |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Momofuku | EPUB | 180 sections | 487,427 | 172 | — | — |
| Ottolenghi Flavor | EPUB | 158 sections | 465,243 | 171 | — | — |
| Tu Casa Mi Casa | PDF | 233 pages | 262,090 | page rendering | 86 | 13 |
| The Professional Chef | PDF | 956 pages | 1,550,690 | page rendering | 23 | 55 |
| The World Atlas of Wine, 8th edition | DjVu | 424 pages | 1,935,278 | page rendering | 11 | 12 |

All 141 EPUB TOC entries resolve to a source section. EPUB images are normalized JPEG renditions, at most 1600 pixels on the long edge; complete originals preserve the original embedded bytes. Image counts concern referenced images actually extracted, not every package manifest image entry. Caption attribution uses source alt text; section image associations are currently document-level.

The completed local build took 397 seconds with OCR results cached from the initial discovery run, and peaked at 400 MB process RSS on macOS. This is not a cold-OCR timing claim. OCR subprocess time is not included in the parent RSS figure. A missing fontTools dependency identified in the first PDF attempt was installed and pinned before the accepted build.

The 360-file publication has:

- 718,326,403 bytes of approved original/backup files and catalog/preferences metadata.
- 57,205,403 bytes of derived EPUB image renditions.
- 20,365,312 bytes of runtime SQLite index.
- 795,897,118 bytes total logical inventory.

Every required object was streamed back and SHA-256 verified before local activation. A separate full restore into an empty directory reconstructed all 360 files and independently matched every size/hash, in 1.51 seconds on this Mac. This measures local disk throughput, not R2 transfer speed. The fixture backup intentionally omits other books' originals even though its administrative catalog references them; it must not be represented as a complete Calibre-library restore.

## Authentication and MCP evidence

The official MCP Python SDK 2.2.0 client completed 32 authenticated tool calls across all five books. The official MCP Inspector CLI 2.6.0 connected over loopback Streamable HTTP and listed the seven tools successfully. Tests exercised structured text, image blocks for EPUB/PDF/DjVu, and embedded text resources for derived section artifacts. Original-file artifact requests explicitly report that binary delivery remains unavailable in this POC; no public or presigned fallback URL is returned.

Synthetic RSA-signed JWT fixtures test signature/RS256 restrictions, issuer, audience/resource, expiry, future not-before/issued-at, required claims, subject allowlist and scope checks. Anonymous requests cannot enumerate tools or access content; wrong/expired credentials fail. Metadata discovery contains resource configuration only. `/healthz` returns only a generic process status; `/readyz` and publication details require authentication. No static API-key or basic-auth mode exists.

This proves resource-server enforcement and local protocol behavior. It does not prove Auth0/Google authorization-code/PKCE, registration, refresh/revocation or ChatGPT display behavior. Those remain separately approved hosted acceptance tests.

## Tests and resource measurements

Final automated result: **24 passed**. Ruff unused/undefined-name checks and formatting checks pass. The only test warning is an upstream Starlette/AnyIO deprecation. No private book, image, database or key files appear among Git-visible project files.

The automated suite covers EPUB spine order, stable IDs, nested TOC and missing anchors, explicit semantic recipe boundaries, image extraction, mixed native/scanned PDF pages, English OCR and cache reuse, DjVu OCR/rendering, physical ordinals, oversized spreads, source immutability, engine failure/timeout, catalog/FTS filters, duplicate grouping, continuations, authorization and asset-ID traversal attempts.

Publication integration tests cover corrupt/missing objects, stale conditional writes, unconfirmed activation, corrupt runtime restore, full empty restore, current-plus-two retention with a pending stage, shared-object references, incomplete-reference fail-closed behavior, and cache corruption. The S3 adapter was exercised against a real loopback Moto HTTP process using synthetic content only. Real data was never sent to the emulator.

Both Docker runs used one CPU, a 1 GiB memory limit, no swap allowance beyond that limit, no network, a read-only container filesystem/object store, an unprivileged process, and a fresh runtime directory. Results are from ARM64 Docker Desktop, not Fly x86/shared-CPU performance.

| Workload | Index | Runtime disk after calls | Parent peak RSS | Container peak including cache/children | Search p50 / p95 | Empty runtime restore |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Five real fixtures, including PDF/DjVu renders | 20.4 MB | 333.4 MB | 94.6 MB | 483.7 MB | 7.8 / 14.2 ms | 0.09 s |
| 120 synthetic books + one alias, 24,000 sections | 219.2 MB | 219.2 MB | 94.7 MB | 485.2 MB | 326.6 / 1396.3 ms | 5.30 s |

The larger synthetic corpus contains approximately 84.6 MB of deliberately repetitive text. It is a common-term/large-index stress test, not a diverse 120-real-book retrieval evaluation. Search was measured over 100 queries; real page rendering covered physical pages 1 and 20 of both PDFs and the DjVu, and five EPUB images. Visual QA checked the synthetic scan and real photographed PDF/wine-page output. Render bounds preserved source aspect ratio and physical-page identity. No claim of exhaustive page-by-page visual or OCR quality review is made.

These measurements support retaining the proposed 1 GB RAM / 10 GB volume for the hosted trial. Four 219 MB indexes (three retained versions plus staging), the 512 MiB cache, and a provisional 256 MiB render scratch allowance total about 1.7 GB before operational overhead. That arithmetic is headroom planning, not an enforced disk quota. A 150 GB original library's index cannot be extrapolated from original bytes alone. The runtime refuses source files larger than its 512 MiB cache limit; larger future scans require a measured delivery/cache policy before rollout.

## Experimental API defaults

These are POC settings for review, not final product decisions:

- Search: 10 results by default, maximum 20, 200-character query, 500-character snippet. Literal token AND semantics, Unicode accent folding, no stemming/phrase-query language yet.
- Reading: 4,000 characters by default, maximum 12,000. Publication-pinned integer continuation offsets. TOC batches default to 30, maximum 50.
- Page/image response: at most 1600 pixels on the long edge; JPEG image block capped at 3 MB. Page text is bounded to 4,000 characters with truncation indicated.
- OCR: English Tesseract, low-text pages below 40 alphanumeric characters, 2500-pixel derived render, 90-second subprocess limit, cached by source/page/engine/configuration. Empty OCR does not by itself fail a publication; engine failures do.
- Source/render access is serialized around a 512 MiB verified disk cache. No bulk original book is returned through an MCP tool.

## Findings that need another content decision

**Rotated scans:** a 90-degree synthetic scan failed the known-quantity phrase check despite Tesseract exiting successfully. Upright synthetic scans preserved the tested `1/2 teaspoon salt` and `200 grams beans`. Current OCR does not rotate/deskew pages, evaluate confidence, or distinguish an illustration from an unreadable scan. Eighty real pages yielded empty OCR; they have not all been visually classified. Pages with a substantial native text layer can still contain unrecognized scanned text. Recommend testing orientation correction and deskew on derived pages, plus an explicit review queue for suspect output, before accepting manually scanned books in production. The exact preprocessing/review policy remains a user decision.

**Recipe structure:** source TOC/heading navigation works, and explicit semantic recipe markup is recognized in synthetic tests. Neither real EPUB yielded explicit semantic recipe labels under the conservative rule. Recipes can be read through their returned source sections, but generic recipe classification, ingredient/method boundaries and book-specific styles remain incomplete. Some source sections still use generated labels, and image associations are chapter-level. Recommend measured structure adapters for supported EPUB styles with an honest section fallback; avoid claiming every source section is a recipe.

## Remaining implementation/deployment gates

- Implement the full-library consistent-snapshot publisher and remembered include/exclude review. The one-command fixture script operates only on the already approved snapshot and subset.
- Complete Auth0/Google setup and exact user identity; discover/register the actual ChatGPT client and validate the real OAuth/PKCE/resource flow.
- Add approved remote credentials/configuration, HTTPS/host validation, runtime polling and hosted activation acknowledgement. The local activation callback is not a Fly acknowledgement.
- Validate R2 conditional/multipart operations against the real jurisdiction endpoint. The POC intentionally refuses single objects above 5 GB rather than using unverified multipart behavior.
- Configure runtime restoration of older retained publications on demand, and approve retention grace periods/cleanup/deletion protection. Real cleanup is disabled; deletion tests run only on synthetic stores.
- Establish local scratch/free-space checks, scan-quality gates, cache policy for large sources, bounded concurrency tests, production readiness/watchdog behavior and external uptime monitoring. Normal process restart does not cure a hang by itself.
- Demonstrate images, selected pages, section artifacts and practical original-file access in ChatGPT. Only then approve final API behavior and separately authorize the complete library upload.

See [the Stage 3 planning draft](stage-3-plan.md). It is a resource/approval worksheet, not a provisioning authorization.

## Evidence files

Private evidence is under `/Users/rick/cookbook-mcp-data/poc/`: `build-3/stats.json`, `build-metrics.json`, `transport-report.json`, `restore-report.json`, `snapshot-recheck.json`, `docker-metrics.json`, `scale-large/build-metrics.json`, `scale-large/docker-metrics.json`, and `qa/rotation-report.json`. All real source/derived files remain outside Git.

Current implementation references: [official Python SDK ASGI integration](https://py.sdk.modelcontextprotocol.io/run/asgi/), [SDK release package](https://pypi.org/project/mcp/), [OpenAI authenticated MCP requirements](https://developers.openai.com/plugins/build/auth), and [Auth0 token validation](https://auth0.com/docs/secure/tokens/access-tokens/validate-access-tokens).
