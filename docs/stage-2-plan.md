# Local proof-of-concept approval plan

Stage 1 discovery and design choices are recorded in [discovery.md](discovery.md), [publication-design.md](publication-design.md), and [tool-contract.md](tool-contract.md). This document makes the next stage concrete for approval. The user approved this local scope and all five fixtures on September 11, 2026. Implementation and results are recorded in [stage-2-report.md](stage-2-report.md).

## Approved design foundation

- Python, the official MCP SDK, Streamable HTTP, and SQLite/FTS5 in a normal Docker container.
- Mac-only publishing and English OCR using consistent snapshots; source Calibre library remains read-only.
- User imports scans as PDFs into Calibre; required OCR errors prevent activation.
- Complete-library original backup; user-reviewed food/wine selection controls tools, including newly added books. Group identical-file search results while retaining record identities.
- Shared immutable objects, complete versioned manifests, full remote byte/hash verification before activation, and current plus two prior successful publications.
- Exact source identities, documented EPUB locators, physical PDF/DjVu page ordinals, and separately verified printed labels.
- Auth0 with Google login and a fixed user-identity allowlist. Eventual hosting: Fly `iad`, R2 `us`, tentative 1 GB RAM/10 GB runtime volume, $25/month planning ceiling.

## Proposed representative source set

Read only from the already verified snapshot at `/Users/rick/cookbook-mcp-data/snapshots/20260911T120144.142161Z/library`. Test outputs belong outside Git under `/Users/rick/cookbook-mcp-data/`. This exact set is approved for local POC use.

| Calibre ID | Book | Purpose |
| --- | --- | --- |
| 5 | Momofuku | EPUB 2.0 navigation, recipe/section structure, 175 image entries |
| 40 | Ottolenghi Flavor: A Cookbook | EPUB 3.0 navigation and a large, approximately 366 MB archive |
| 6 | Tu Casa Mi Casa Mexican Recipes for the Home Cook | PDF with sampled low-text interior pages; inspect scan/OCR behavior |
| 9 | The Professional Chef | 956-page PDF, native/OCR text inspection and embedded page labels |
| 45 | The World Atlas of Wine, eighth edition | DjVu text/page extraction; synthetic alias records can test duplicate grouping |

Five complete original format files total approximately 714 MB. Synthetic fixtures will add deliberate edge cases and a clearly labeled 120-book scale workload. Synthetic PDFs can include known ground-truth recipe quantities, fractions, rotations, spreads, mixed native/scanned pages, and intentional OCR failures. Synthetic scale results must be distinguished from performance on 120 real cookbooks. No real book or extracted passage enters Git.

## Proposed local scope

1. Set up a project environment and pin dependencies. Add exclusions for private data, generated outputs, credentials, and local configuration before generating test outputs. Keep pure synthetic fixtures and test code in the repository; store all book-derived content outside it.
2. Implement versioned source/citation mappings and extraction for the approved fixtures. Inspect package reading order/TOCs and extract bounded text plus image references. Preserve PDF/DjVu page identity. Use OCR only on derived files and cache by exact processing inputs.
3. Build a local publication/index and prototype the proposed tools. Keep the API shapes provisional until content delivery is tested. Record numerical limits and defaults as experimental settings rather than final product requirements.
4. Test shared objects, full readback verification, atomic pointer switching, partial/corrupt/missing uploads, interrupted OCR, stale publishers, retention with shared references, and complete restoration into an empty destination.
5. Exercise the S3 adapter against a local test service using synthetic data. Do not expose real library content through an unauthenticated emulator. Tests on real fixtures can use a local storage backend; eventual R2 conditional/multipart/jurisdiction behavior must be tested against R2 only after Stage 3 approval.
6. Implement resource-server authorization checks with test-only signing keys and token fixtures: signature/algorithm, issuer, audience/resource, expiration/not-before, scopes, and allowed subject. Test that missing/invalid credentials cannot enumerate tools/catalog or retrieve assets. Test-token fixtures are not a new authorization server and do not prove an Auth0/ChatGPT OAuth flow.
7. Bind any local MCP/Inspector service only to loopback. Use authenticated local tool calls, test image/text/resource response types, and run the official MCP Inspector or current equivalent. Do not create a public tunnel or remote endpoint. Avoid logging source text, tokens, credentials, or signed URLs.
8. Measure the 1 GB memory limit in Docker, disk/index/cache use, the large EPUB/PDF cases, and the synthetic 120-book workload. Record OCR time, staging and restore headroom, and failures honestly. Increase neither Fly sizing nor the approved budget without presenting measurements.
9. Deliver the test report, concrete API proposal, limitations, and an updated deployment resource/command/cost plan for Stage 3 approval.

## Sizing baseline and limits of current evidence

The source snapshot contains 56 records, 3.82 GB of files, approximately 24.7 MB of EPUB text, 8,011 EPUB image entries, and 5,813 PDF pages. A Python PDF sampling process peaked around 117 MB RSS on macOS. These observations support testing an embedded index and the tentative 1 GB Machine; they do not validate Linux server memory, page rendering, concurrent calls, OCR duration, or 100+ real books.

The 10 GB volume must fit active, staging, rollback runtime files, a bounded cache, and temporary rendering space. It cannot contain a growing full original library. OCR runs on the Mac. Full remote verification downloads one complete publication each time, an explicitly approved bandwidth cost.

Current Fly compute plus tentative volume is approximately $7.20/month. At 150 GB of originals, three physically full original copies would add about $6.60/month in R2; the approved shared-object layout can reduce repeated-original storage. Derived artifacts, staging peaks, traffic, excess requests/snapshots/build storage, taxes, and any account charges still need measurement or verification. The $25 ceiling remains a planning constraint.

## Deferred until evidence or infrastructure approval

- Actual Auth0 tenant, Google OAuth client, user subject, exact ChatGPT client identification/redirect values, and refresh/revocation settings.
- Fly account login, organization/billing status, current region capacity, exact app hostname, R2 activation/account/bucket name, and separate scoped credentials.
- Final response bounds, multi-format preference, recipe-detection confidence, artifact delivery, supported image/page resolution, and any scan preprocessing. The POC can test alternatives; final behavior needs review before commitment.
- Cleanup timing for local snapshots, failed cloud stages, and unreferenced shared objects; policy protections against deletion using a stolen publisher credential. No automatic deletion outside disposable synthetic test state before an approved cleanup plan.
- Uptime service, public versus private health details, polling/timeouts, Fly watchdog/restart and snapshot configuration, billing alerts and operational thresholds.
- Extra backup material outside the Calibre library, such as Calibre application preferences or plugins: no such filesystem paths or backup scope are assumed. Project/extraction configuration needed to restore this service must be documented and included appropriately without bundling secrets.

## Evidence required later in ChatGPT

Local image or embedded-resource success does not prove ChatGPT behavior. After the user approves the Stage 3 infrastructure plan, deploy only the approved test subset, complete real Auth0/Google linking in ChatGPT, and demonstrate authenticated image/page/section/original-artifact behavior and empty-volume recovery. Resolve any mismatch before calling the API final or requesting approval for the full library upload.

Stage 2 approval authorizes local implementation and tests only. It does not authorize paid resources, Auth0/Google resource creation, a public endpoint, book uploads, or Calibre changes.
