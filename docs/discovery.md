# Cookbook MCP discovery — Stage 1 record

## Confirmed decisions

- Existing skill: `/Users/rick/.agents/skills/calibre-explore` (also linked from `.claude/skills`). Both SKILL.md and the complete shell implementation have been read.
- Source library: `/Users/rick/Calibre Library`, strictly read-only to this project.
- Project: `/Users/rick/Documents/ChatGPT/cookbook-mcp`.
- User approved `/Users/rick/cookbook-mcp-data/snapshots` and explicitly requested Calibre shutdown on September 11. Calibre and its viewer were quit normally; no remaining Calibre processes or open library files were detected before copying.
- Verified discovery snapshot: `/Users/rick/cookbook-mcp-data/snapshots/20260911T120144.142161Z/library`. Adjacent `snapshot-manifest.json` records all 173 files, source metadata, sizes, and SHA-256 hashes (3,817,690,346 bytes total). Source pre/post stat inventories matched, all source/copy hashes matched, and final process/open-file checks passed. Snapshot copying did not modify source files. Normal application shutdown preceded the snapshot.
- User has Fly.io and Cloudflare accounts and ChatGPT Pro. Billing readiness, organizations, R2 activation, buckets, and existing identity-provider accounts remain unverified.
- Use a Fly-provided hostname; exact app name remains unresolved.
- User approved Fly region Ashburn, Virginia (`iad`) and R2 United States (`us`) jurisdiction. Availability and account-specific configuration still require verification before provisioning.
- User approved a $25/month planning ceiling for this service, excluding ChatGPT Pro. This is not spending authorization or a provider-enforced billing cap; a proposal estimated above it requires reconsideration and approval.
- User approved Python with the official MCP SDK and SQLite/FTS5, shared immutable R2 objects referenced by complete per-publication manifests, and full streamed readback of every required object with independent SHA-256 verification before activation. The user accepted the resulting verification download volume, including at future library sizes.
- Near-term capacity target: 100+ books, per the user's September 11 update; the current 56-book snapshot is only the baseline. The original 50–150 GB three-year growth range still applies. No exact upper book count, future format mix, or new runtime sizing has been selected.
- User approved Auth0 with Google login. A dedicated Google OAuth client is required; this is a design selection, not authorization to create accounts, a tenant, or a client. Exact authenticated identity and MCP client-registration configuration remain unresolved.
- User approved backing up the complete library while exposing only food/wine books through an explicit selection. The single manual publish command asks the user to include/exclude newly discovered books, then remembers choices outside Calibre. Every original is backed up regardless of exposure. No automatic topic classifier or filename-based exclusion is approved.
- User approved initial DjVu search and page-reading support. Preserve original DjVu files; local derived text/rendering and OCR must keep source files unchanged.
- User approved grouping byte-identical files in search, preserving all record/source identities and originals. Different editions or similar titles are not merged. The user noted that deleting duplicates in Calibre may be the better source-level solution; this is not an instruction to delete them. The read-only-source rule remains in force. IDs 45, 46, and 58 are the verified identical-file group.
- User approved keeping the current publication plus two previous successful publications; older publications are eligible for removal only after a verified replacement is active. Historical recoverability and hosted citation resolution are limited by retained source versions. Exact cleanup mechanics and backup deletion protection remain to be specified before deployment.
- User approved selective local OCR with cached results, preserving original sources. Incoming manually scanned books are expected soon, and OCR is a required ingestion capability for them.
- User will import scanned PDFs into Calibre before publishing. Initial OCR language is English. Required OCR errors/timeouts stop publication and leave the hosted publication active; blank or illustration pages are not failures merely because they lack text. Loose-image ingestion and additional OCR languages are outside the initial approved workflow.
- User approved documented source-based EPUB locators rather than requiring EPUB CFI initially. The locator includes exact source-file identity, internal chapter path, anchor or deterministic text position, and publication context. PDF/DjVu citations identify exact source files and physical pages; verified printed labels are separate.
- Stage 2 local implementation with the five named fixtures was subsequently approved. No infrastructure, tenant, public endpoint, or cloud upload is authorized. See [the Stage 2 report](stage-2-report.md).

## Local evidence

Filesystem-only inventory on September 10, 2026; live inventory, not a consistent snapshot. No database contents or book contents have been read.

| Item | Count | Bytes |
| --- | ---: | ---: |
| EPUB | 42 | 2,676,940,302 |
| PDF | 11 | 738,869,912 |
| DjVu | 3 | 308,434,377 |
| JPEG | 53 | 22,319,393 |
| OPF | 56 | 111,082 |
| All files | — | 3,817,690,347 |

Root `metadata.db`: 483,328 bytes. Root `full-text-search.db`: 70,406,144 bytes. Counts are formats/files, not verified catalog records. No file symlinks were found by the inventory.

Calibre GUI and worker processes were running during initial inspection. Calibre 8.13 is installed. Docker client and server both respond at 29.5.2. Fly CLI v0.4.58 is installed. Python, SQLite CLI, Node, and uv are present. `pdftotext` is absent from the current PATH; `pdftoppm` is available through the bundled runtime. About 441 GiB free space was reported on the source/project filesystem. No project code, dependencies, or tests existed at discovery start; Git had no commits.

## Existing behavior and migration risks

The skill is one shell script with inline Python, not a reusable package, and has no bundled tests. Preserve useful semantics: catalog filters; book ID/title lookup; full-text snippets; collapsed book-level matches; TOC navigation; bounded follow-up reading grounded in source text.

- Search delegates to Calibre's custom-tokenizer FTS index. A portable FTS5 implementation needs a separately built index and search-behavior comparison, including accents, phrases, stemming, and syntax.
- Book resolution infers numeric IDs from folder names and prefers EPUB over PDF. Remote identity and format selection must instead be explicit and grounded in snapshot metadata.
- EPUB extraction sorts HTML filenames, strips markup with regexes, and loses source positions. Correct spine order and document anchors must be retained for reproducible citations.
- TOC extraction keeps labels but loses links and nesting. EPUB package/nav/NCX parsing must preserve destinations.
- PDF extraction emits whole-book text without structured page IDs. Preserve physical page ordinals and distinguish printed labels.
- Images, recipes, manifests, publication versions, and authenticated artifact delivery are new capabilities.
- DjVu exists but is unsupported by the existing script; the user approved adding search and page reading.
- Snapshot hashes prove the three DjVu files for *The World Atlas of Wine*, eighth edition (book IDs 45, 46, 58), are byte-identical. Each is 102,811,459 bytes. None has an EPUB/PDF companion or a separate catalog entry with that title in an EPUB/PDF format. Approved policy: group identical bytes in search and preserve all source records/files.
- Initial structure checks below establish format availability, UUIDs, duplicate files, metadata integrity, and font-encryption declarations. Full archive validation, page-level visual quality, OCR accuracy, and search equivalence still need the Stage 2 POC.

## Architecture selected for the local POC

Mac: pause all library writers; create and verify an independent local snapshot; inspect only that snapshot; extract document structure and build portable indexes offline. Then publish originals, required Calibre metadata, derived assets, and a hash inventory as an immutable publication. The user selected shared immutable content-addressed objects with complete per-publication manifests, and full streamed remote SHA-256 readback verification before changing the active pointer.

R2: complete durable private publication, separate bucket-scoped publisher and runtime credentials. Runtime credentials are object-read-only. Standard R2 tokens support bucket scopes; do not claim prefix isolation without separately implementing and verifying it. Recommend a dedicated bucket to make the boundary simple.

Fly: one normal Docker container with read-only MCP operations over Streamable HTTP. Restore indexes from R2, stage and hash-verify replacements, then atomically switch the active version. Fetch source artifacts through bounded caches rather than keeping the entire library on the volume. Keep old versions available according to a user-selected retention policy and pin calls to publication IDs.

The tentative 1 GB RAM / 10 GB volume remains unvalidated but plausible for the current collection. EPUB text measured approximately 24.7 MB, versus 2.86 GB uncompressed EPUB contents (mostly assets); keeping originals and images in R2 and bounding the local cache remains appropriate. A local Python process sampling five pages from each PDF peaked around 117 MB RSS, but this does not measure rendering, concurrent requests, the server, or Linux container behavior. Measure peak process memory during PDF rendering and searches; measure index/text size, active + staged + rollback state, cache ceiling, and temporary-space headroom. The existing 70.4 MB Calibre index is only an encouraging starting observation, not a sizing guarantee. A 150 GB future library cannot be sized by original bytes alone: image-heavy and text-heavy growth have different index costs.

The Stage 2 evaluation plan must cover a 100+ book catalog, not just the current snapshot. Use separately identified synthetic scale fixtures or additional user-approved books; do not treat repeated copies of identical text as proof of diverse-corpus search performance. Measure index growth and query latency, total/peak publish disk use, restore duration, atomic version-switch headroom, and bounded-cache behavior. Exercise a large PDF and an image-heavy EPUB independently of catalog size. Report measured fixtures and extrapolations separately. The user's growth update does not authorize changing the tentative Machine or volume size without evidence and approval.

Proposed MCP capabilities and parameter shapes are documented in [tool-contract.md](tool-contract.md). They cover catalog/full-text search, scoped search, book metadata/TOC, bounded reading, PDF/DjVu pages, images, original artifacts, and publication/citation details. Delivery behavior and exact limits remain gated on the POC; this document is not implementation approval.

Artifact POC must test authenticated inline images, selected-page renders, bounded EPUB sections, and original artifact delivery in ChatGPT. Do not rely on protected URLs being fetched automatically or use bearer presigned URLs as a privacy shortcut. Local protocol success does not establish ChatGPT rendering success; a separately approved endpoint will be needed for that acceptance test.

Public OAuth discovery must contain no library data. Protect catalog, content, assets, and MCP requests. Health exposure and publication-ID visibility need an explicit choice. A process restart policy handles exits; a separate watchdog is needed for hangs. No infrastructure-specific API belongs in the content core.

## Authentication shortlist

Auth0 is the user-selected identity provider: hosted login, native MCP support, manual CIMD registration, and an explicit resource-parameter compatibility setting. Setup would include a tenant, API identifier/scopes, client registration, login method, refresh-token settings, and a fixed issuer/subject allowlist. Current Free pricing includes Auth for MCP and up to 25,000 monthly active users. No tenant has been created or identified.

Stytch Connected Apps is an alternative with documented PKCE/discovery/DCR support and a free allowance of 10,000 monthly active users and AI agents. Its documented integration requires an application-hosted login/consent surface, increasing implementation scope here. Resource-specific token audience behavior still requires verification before selecting it as the implementation path.

Whichever provider is selected, enforce signature/algorithm, issuer, resource/audience, expiry/not-before, scopes, and exact allowed subject on protected requests. Use actual discovery metadata and the exact ChatGPT-provided redirect URI, not a guessed callback. Provider compatibility and login must be demonstrated end to end.

Sources checked September 10, 2026:

- [OpenAI OAuth contract](https://developers.openai.com/apps-sdk/build/auth)
- [ChatGPT developer mode](https://developers.openai.com/api/docs/guides/developer-mode)
- [Auth0 pricing](https://auth0.com/pricing)
- [Auth0 CIMD](https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd)
- [Auth0 tenant settings](https://auth0.com/docs/get-started/tenant-settings)
- [Stytch pricing](https://stytch.com/pricing)
- [Stytch MCP authorization](https://stytch.com/docs/connected-apps/guides/mcp-auth-overview)

## Cost evidence, not a deployment quote

R2 Standard is $0.015/GB-month, with 10 GB-month included, 1 million Class A and 10 million Class B requests included monthly, and no R2 egress charge. Free allowances may be shared with other account usage. Extracted assets and retained publications increase total stored bytes. Use Standard rather than Infrequent Access as the proposal because the latter adds retrieval fees and minimum durations.

Illustrative originals-only monthly storage, assuming the free storage allowance is unused elsewhere and full copies remain all month:

| Library size | One complete copy | Two complete copies |
| --- | ---: | ---: |
| 3.82 GB observed | $0.00 | $0.00 |
| 25 GB | about $0.23 | $0.60 |
| 50 GB | $0.60 | $1.35 |
| 150 GB | $2.10 | $4.35 |

These are not full publication or total service estimates. Fly volume capacity is $0.15/GB-month: 10 GB is $1.50/month. Compute varies by region; select a US region before giving a region-specific quote. Shared IPv4 is available; dedicated IPv4 costs $2/month and is not currently proposed. Fly egress, image/build storage, extra Machines, volume snapshots, taxes, and other account usage must be accounted for in the approval plan. Fly enables daily volume snapshots with five-day retention by default; decide whether to retain them for replaceable runtime state.

- [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [R2 credential scopes](https://developers.cloudflare.com/r2/api/tokens/)
- [Fly pricing](https://fly.io/docs/about/pricing/)
- [Fly regions](https://fly.io/docs/reference/regions/)
- [Fly restart policies](https://fly.io/docs/machines/guides-examples/machine-restart-policy/)

## Remaining decision batches

1. Snapshot creation and initial structure inspection are complete. Whole-library backup, food/wine-only tool exposure, DjVu support, selective local English OCR, scanned-PDF import into Calibre, fail-on-required-OCR-error publishing, source-based EPUB locators, review of new books during publishing, and grouping byte-identical search results are approved.
2. Auth0 with Google login is approved. Resolve allowed identity and MCP client-registration method; verify Google account/client setup readiness. No provider/client creation before infrastructure approval.
3. Proposed tool-contract acceptance and approved representative books/synthetic fixtures for Stage 2. Python/official MCP SDK/SQLite FTS5, source-based locator equivalence, initial OCR policy, shared immutable storage, and full remote readback verification are settled. POC experiments will establish exact response limits and extraction behavior before final API approval.
4. Before deployment: complete backup contents beyond existing library files, local snapshot cleanup, failed-upload cleanup, and protection against publisher-credential deletion. Current plus two prior successful publications, retention-limited historical citation access, and shared-object storage are settled.
5. Before deployment: account/org/billing readiness; bucket and app names; billing guardrail implementation; health/uptime service and exposure; polling/timeout settings. Region `iad`, R2 jurisdiction `us`, and $25 planning ceiling are settled. The command must distinguish verified R2 upload from successful hosted activation, as required by the original request.
6. Present architecture and measured/estimated resources to close Stage 1. Request Stage 2 authorization before building the POC. Stage 3 resource plan and approval precede any endpoint or tenant creation and uploads. Full-library upload requires separate explicit approval after ChatGPT acceptance of the test subset.

Documentation-only choice: record discovery and pending decisions in this Markdown file. No deployment-specific code has been written.

## Follow-up discovery

The official [MCP SDK inventory](https://modelcontextprotocol.io/docs/2026-07-28/sdk) lists Python and TypeScript as Tier 1. The user selected Python with the official SDK and SQLite/FTS5.

[R2 data-location documentation](https://developers.cloudflare.com/r2/reference/data-location/) distinguishes best-effort location hints from jurisdictional restrictions. A US Fly region does not by itself constrain R2 storage geography. Resolve the user's storage-location preference in the infrastructure decision batch.

The user subsequently approved the proposed snapshot location and requested shutting down Calibre. Snapshot inspection below is complete. Auth0 selection, complete-library backup with food/wine-only tool exposure, and DjVu search/page support were then approved. No deployment-specific code, infrastructure, tenant, public endpoint, or upload has been created.

## Verified snapshot findings — September 11

The snapshot database was opened using SQLite `mode=ro&immutable=1`; `PRAGMA integrity_check` returned `ok`. There are 56 book records and exactly one format per record: 42 EPUB, 11 PDF, 3 DjVu. All referenced format files exist. Every book has a unique, nonempty UUID, providing a useful candidate identity component (library UUID + book UUID, separate from publication/content hashes). No custom columns, annotation records, or last-read-position records exist in the catalog snapshot.

The stored byte sizes for 36 EPUB records differ slightly from actual file sizes. The snapshot itself passed source/copy checksum verification; metadata size differences must not be misreported as copy corruption. Publisher manifests should use measured bytes and hashes. The cause of stale catalog sizes has not been established, and the source catalog has not been repaired.

EPUB structural inspection:

- 23 EPUB 2.0 and 19 EPUB 3.0 packages parsed successfully.
- 3,896 spine references, 3,916 HTML documents, 8,011 manifest image entries.
- 39 of 42 spine orders differ from sorting their document paths. Filename concatenation is unsuitable as the future citation reading order.
- Approximately 61.4 MB of HTML markup and 24.7 MB of decoded text including whitespace and non-spine content. Text counts are discovery estimates, not the final extraction algorithm.
- 8,336 heading elements and 75,765 ID/named-anchor elements. Eighteen books contain elements whose class/type mentions recipes; these are candidate structural signals, not verified recipe boundaries.
- One EPUB has an encryption manifest referencing seven font files only (five OTF, two TTF); do not classify the whole book as unreadable based on that manifest alone. Its HTML was readable. No ZIP entry encryption flags were found in that EPUB.

PDF structural inspection:

- 5,813 physical pages across 11 PDFs; none reports PDF encryption.
- Three have embedded page-label dictionaries. Most lack those dictionaries, and printed page numbering cannot be inferred from physical ordinals.
- Five pages per PDF were sampled (first, early interior, quarter, middle, last), all without extraction exceptions. Some interior pages yield 0–10 characters. This suggests possible scan/image pages but is not proof: illustrations and blank pages also yield little text. Visual inspection and full per-page assessment are needed before deciding OCR coverage.
- Page dimensions vary widely, including pages over 2,000 points high and landscape spreads. Rendering must cap output pixel dimensions to control memory while retaining a way to request readable details.
- Sampling process peak RSS was 117,260,288 bytes on macOS; it is not a hosted runtime benchmark.

The catalog contains a programming book, *Elixir in Action*, alongside food/wine books. The user approved backing up everything while filtering tool exposure to food/wine. Keep the programming book in the independent backup; the explicit selection workflow remains to be chosen.

Private inspection reports are outside Git under `/Users/rick/cookbook-mcp-data/`: `discovery-inventory.json`, `epub-text-discovery.json`, and `pdf-discovery.json`. Reports contain metadata/statistics and no extracted passages. No book content is included in project files.

## Approved batch: retention, OCR, and citations

The user accepted these recommendations:

- Retention: current plus two previous successful publications, with older publications eligible for removal only after a verified replacement is active. Historical deletions and citations remain recoverable only while their source version is retained. Three full 150 GB originals-only copies cost approximately $6.60/month at the previously verified R2 Standard rate and unused 10 GB allowance; derived assets and other charges are additional. No cleanup has been performed.
- OCR: selectively process pages lacking usable text on local derived copies, cache by source hash and extraction settings, preserve originals, label OCR-derived text, and use original page images for verification. Do not treat empty text alone as a definitive scan detector. Language selection remains explicit.
- EPUB citations: source-file hash + internal chapter path + anchor or deterministic text position, with publication ID and documented algorithm version. This is a service-resolvable locator, not a standard e-reader deep link. PDF/DjVu: source identity + physical page ordinal, separate verified printed page label.

Incoming scans make OCR a core initial ingestion requirement. OCR runs on the Mac before upload, and page-mapped text/derived artifacts become part of the publication. Cache keys must include original file hash, OCR engine/version, language settings, and processing options so changed settings invalidate stale results. Original page ordinals and images remain the source for citation verification; recognition output must never silently replace or alter original scans in Calibre.

Stage 2 must include approved representative image-only and mixed text/image scans, rotation and spread cases, recipe quantities/fractions, and interrupted OCR recovery. English OCR quality, processing errors, and duration need measurement on scanned PDFs. Add scanning-heavy growth scenarios to the 100+ book evaluation; book count and current EPUB text density are not adequate predictors of scan storage, local scratch space, or initial publishing time. Input is user-imported PDFs and initial OCR language is English; resolution, page geometry, compression, and preprocessing settings remain unmeasured.

Dependency discovery: local Tesseract and OCRmyPDF 16.10.4 are installed. Tesseract language inventory contains `eng`, `osd`, and `snum`; neither `ddjvu` nor `djvutxt` was found on PATH. Catalog language inspection found 44 books tagged `eng` and 12 without a language. The user's explicit English-only decision sets the initial OCR policy; additional languages require a later choice.

Auth0 login-method discovery: [Google login](https://auth0.com/docs/authenticate/identity-providers/social-identity-providers/google) requires the project's own Google OAuth credentials for production. The user selected Google through Auth0 after reviewing this setup requirement. No Google client or Auth0 tenant has been configured. An application email-sending service is not part of the selected login design.

Communication preference: the user reports that tool-based questions are collapsed in the app's work details. Put pending questions and their recommendations directly in final replies, rather than relying on asynchronous question widgets.

## Approved infrastructure-location and budget batch

September 11 pricing verification read the official [Fly pricing page](https://fly.io/pricing/), including its HTML region selector and price multipliers. Ashburn and Secaucus have multiplier 1; Chicago and Dallas 1.25. The user selected Ashburn, Virginia (`iad`), in the cheapest listed US compute tier. At the tentative shared-cpu-1x / 1 GB size, compute is approximately $5.70 per 30 days; the tentative 10 GB volume adds $1.50. This roughly $7.20 baseline excludes R2, Fly egress, any excess snapshot/build storage, tax, and other services. Chicago would be approximately $7.12 compute plus the volume. Capacity at actual provisioning time remains unverified.

The user selected R2's `us` jurisdiction to keep durable originals and derived artifacts in the United States. [Cloudflare documentation](https://developers.cloudflare.com/r2/reference/data-location/) lists `us` and says bucket jurisdiction cannot be changed after creation; relocation would require a new bucket and verified migration. The exact bucket name and account activation remain undecided.

The user approved a $25/month planning ceiling for this service, excluding the existing ChatGPT Pro subscription, with approval required for a design whose estimated recurring cost exceeds it. This is neither approval to spend nor a provider-enforced hard billing cap.

The read-only `fly platform vm-sizes --json` check reported no access token. Fly CLI is installed but not signed in. Account existence is user-confirmed; account organization, billing readiness, and capacity remain unverified. No login, resources, or endpoints were created by this check.

[OCRmyPDF documentation](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html) describes language selection and warns that sidecar text omits pages whose existing text was not OCRed. Any publisher must combine existing extracted text with page-mapped OCR results rather than indexing only a sidecar. Online documentation currently describes version 17; commands must be checked against the installed version before use. No OCR has been run.
