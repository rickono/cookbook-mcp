# Publication design proposal

Stage 1 design document. Region (`iad`), storage jurisdiction (`us`), $25/month planning ceiling, current plus two prior successful publications, read-only source library, English OCR, and Google login through Auth0 are approved. The user also approved the Python/official MCP SDK/SQLite FTS5 stack, shared immutable storage layout, and full streamed remote SHA-256 verification described below. Stage 2 local implementation was authorized and is described in [stage-2-report.md](stage-2-report.md). No deployment or upload is authorized.

## Approved processing stack

Use Python with the official MCP SDK, Streamable HTTP, and SQLite/FTS5. Package the server in a normal Docker container. Keep extraction, immutable publication inventory, storage operations, serving, and provider-specific deployment configuration separate. Reuse the existing skill's catalog/search and extraction behavior where correct; replace filename-order EPUB concatenation with package-spine reading and preserve source locators. Do not wrap the complete Mac-dependent shell skill as a remote server.

Python fits the existing inline Python extraction and locally available PDF/OCR tooling. A TypeScript server with Python extraction is a possible alternative but adds a runtime boundary. Pin supported stable versions during the local POC after checking official release metadata, not from memory. SQLite tokenization/search behavior must be evaluated against representative Calibre queries.

## Approved physical storage: shared immutable objects

Store each unique original or derived file once under a key derived from its SHA-256 hash. Each publication has its own immutable manifest listing every logical file path, object key, byte size, hash, schema/extraction versions, book identity, and source/citation mapping. Control pointers are separate mutable objects.

This changes the tentative workflow from a self-contained physical copy under every version prefix to a complete logical publication whose manifest references shared R2 objects. Every retained publication is still independently restorable from R2 with no Mac data or external book files. Different Calibre records can reference identical bytes without merging their catalog identities. Restoring reconstructs the original logical file tree.

Why propose this: with incoming scans and 100+ books, successive publications are likely to reuse many originals. Shared objects avoid re-uploading or retaining multiple copies of unchanged files. The tradeoff is more careful cleanup: an object cannot be removed while any retained publication, in-progress publish, or supported rollback needs it. Cleanup must be serialized with publishing, operate on an explicit complete reference inventory, and fail closed on missing/unreadable manifests. Test retention with shared objects, crashed publishes, rollback, and concurrent maintenance.

The simpler alternative is physically self-contained version prefixes, using server-side copying of unchanged objects where supported. That simplifies manual browsing/deletion and increases stored bytes and copy operations. Both remain compatible with ordinary S3 storage; neither needs proprietary storage logic in the content core.

The user selected shared immutable objects. Conditional create-only writes protect against accidental overwrites in normal publishing. Hash-based names do not by themselves protect against a stolen write credential or an administrator deleting objects; storage-policy protection is a separate Stage 3 decision and must not be overstated.

## Approved verification: full streamed readback initially

Measure hashes of original snapshot bytes and all derived files locally. Upload new files with supported transfer-integrity checks. Before activation, stream every required publication object back from R2 and independently recompute its SHA-256, comparing both length and hash to the manifest. Verify the manifest itself and its exact schema/inventory before committing the pointer. Reused content is also verified; an object-name hash, user metadata, or multipart ETag is not sufficient proof of its current bytes.

This is simple to audit and directly satisfies the checksum-verified independent-backup requirement. The user explicitly accepted that it downloads approximately one complete publication per publish: at 150 GB of originals, at least 150 GB plus derived assets. Reads can stream through small buffers without retaining another full disk copy. R2 does not charge egress, but elapsed time and the user's connection/data allowance can matter. Measure this in the POC before offering any incremental-verification optimization. Such an optimization would need a separate integrity design and approval.

The [R2 compatibility matrix](https://developers.cloudflare.com/r2/api/s3/api/) distinguishes full-object checksums from composite checksums and does not advertise full-object SHA-256 for multipart objects. Do not compare a composite SHA-256 or ETag directly to the manifest's SHA-256 of the whole file. It documents conditional PutObject requests; exact multipart/conditional semantics must be tested against R2 after infrastructure approval, with portable fallbacks for other S3 stores.

## Publish lifecycle

1. Hold a publisher lock and ensure Calibre writers are paused. Create a consistent snapshot outside Git, preserving all original library files. Review newly discovered book exposure choices and persist the selection outside Calibre.
2. Extract selected book content in source order. Apply required English OCR to local derived copies; cache results by source hash and exact processing configuration. A required extraction/OCR failure prevents activation. Keep every original, including excluded books, in the backup inventory.
3. Build the read-only runtime index, source/section/page/image maps, and versioned manifest. Validate completeness and all local file hashes.
4. Upload the staged publication. Under the shared-object proposal, create missing objects without overwriting existing keys; verify reused objects too. Resume safely after interruption.
5. Perform full streamed remote readback verification. Never commit the active pointer on an incomplete inventory or mismatch.
6. Update the R2 active-publication pointer with a conditional write tied to the expected previous pointer. A stale/concurrent publisher must not silently overwrite a newer choice.
7. The read-only service detects the new complete version, verifies/stages its required runtime files, and switches atomically. Requests and continuations retain their own publication context. Content assets are hash-verified before use and fetched through bounded caches.
8. The Mac command reports full publish success only after an authenticated check confirms the desired publication is active on Fly. This follows the user's requirement that successful publish means the hosted copy is current. If activation cannot be confirmed, report a distinct pending/failed-activation result, preserve the previous version and all needed staged state, and allow resume/retry without rebuilding or re-uploading valid objects. Do not call a verified R2 upload a completed hosted publish.
9. After confirmed activation, advance the successful-publication retention inventory. Retain current plus two previous successful publications. Never prune during an unconfirmed activation. Cleanup details and grace periods remain to be finalized before any deletion automation.

No MCP tool performs these writes: the publisher is a separate administrative Mac command using separate credentials. The runtime has read-only R2 credentials and reports activation through authenticated diagnostics. The R2 pointer supports empty-volume recovery; it must refer only to a complete verified publication. Service activation failure must preserve the previous local valid state and remain visible to the publisher.

## Runtime and scan constraints

The Fly volume holds only reconstructable indexes, staged/rollback runtime state, and bounded source/render caches. Do not mirror all originals to the 10 GB volume. Heavy OCR runs on the Mac, not the tentative 1 GB Fly Machine. Per-page rendering must be bounded and tested with the unusually large source page dimensions observed in this library. Keep original scans and their page order intact; OCR is a separate derived representation with exact source mappings.

Measure local snapshot/scratch requirements as well as hosted storage. At 150 GB, a snapshot plus OCR temporary files and cached derivatives can consume substantial Mac space. Current free disk is not a three-year capacity guarantee. The command should estimate needed space and stop with a clear report before exhausting a filesystem; exact headroom limits are POC outputs.

## Cost envelope

Illustrative base compute/volume plus R2 originals only, using the verified September 11 prices, assuming a full 30-day month and unused R2 free allowance. Three physically complete original copies are a conservative comparison, not the selected storage layout. Derived assets, traffic, excess request counts, excess Fly snapshots/build storage, temporary staging, taxes, and account-specific charges are excluded.

| Original library size | Fly compute + tentative volume | R2: three full original copies | Combined baseline |
| --- | ---: | ---: | ---: |
| 3.82 GB | about $7.20 | about $0.03 | about $7.23 |
| 25 GB | about $7.20 | about $0.98 | about $8.18 |
| 50 GB | about $7.20 | $2.10 | about $9.30 |
| 150 GB | about $7.20 | $6.60 | about $13.80 |

Shared immutable objects would charge for unique retained bytes rather than multiplying every unchanged original by three. Exact cost depends on the change rate and derived artifacts, which remain unmeasured. Peak storage during staging can exceed the three-publication steady state. Preserve the $25 planning ceiling as a review constraint, not a claim that bills are technically capped.

Sources: [Fly prices](https://fly.io/pricing/), [R2 prices](https://developers.cloudflare.com/r2/pricing/), [R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/), [R2 bucket locks](https://developers.cloudflare.com/r2/buckets/bucket-locks/). On September 12, 2026 the user approved indefinite locks on `objects/` and `publications/`; both were enabled in R2. `control/` remains mutable, completed-object lifecycle deletion and application garbage collection remain disabled, and physical historical data can exceed the current-plus-two normal rollback set until a separately approved administrative cleanup. See stage-3-plan.md for verification.
