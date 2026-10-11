# Whole-book retrieval through the MCP

The integration for [Publish whole-book structure and Typesense retrieval through the MCP](https://github.com/rickono/cookbook-mcp/issues/24)
adds native EPUB source capture and an owned Typesense keyword index to the
existing immutable publication lifecycle. The original books remain authoritative.
The [whole-book model](whole-book-model.md) defines the records; agreed terminology
is in [CONTEXT.md](../CONTEXT.md).

## Publication and coverage

`cookbook structure --build EXISTING_BUILD --output NEW_BUILD --interpretation EXISTING_MODEL`
creates a new publication from an already verified EPUB build. It verifies every
original input, captures source resources, ordered DOM nodes, reading occurrences,
authored navigation, links and spans, and retains the existing sections, images
and original backups. PDF/DjVu, OCR and inference are outside this command; their
existing resource admission check still applies.

Interpretations are imported only when the original source hashes match exactly.
Their states are preserved. The first catalog has native structural capture for
all 59 currently published EPUBs, including Chop Chop, and 2,632 candidate recipe
records from the 20-book trial. Parts, uses, quantities, reference entries and
other typed records are supported but currently have only limited worked
examples. Structural coverage does not establish semantic completeness, readable
image text, suitability, or accurate recipe boundaries. Parser diagnostics and
interpretation coverage accompany reading responses.

The manifest contains `runtime/whole-books.sqlite` and `runtime/whole-books.json`.
Both must exist and validate together. The model snapshot identifies the source
publication and implementation; it is distinct from the publication ID. Publishing
still requires immutable upload, complete checksum readback, a conditional active
pointer update, and exact hosted acknowledgement. No book data belongs in Git.

## MCP tools

| Tool | Contract |
| --- | --- |
| `find_book_content` | Literal keyword retrieval with typo tolerance and 5:1 title/body weighting. Filter by admitted book IDs, finite record kinds, or candidate inclusion. Default allowance 25; maximum 50. Page continuations require a pinned publication. |
| `get_book_structure` | Coverage, separate reading occurrences, root nodes and authored navigation, with bounded offsets. |
| `read_book_content` | Ordered original nodes for an entity, span, navigation target, reading occurrence or node; bounded UTF-8 bytes and node count with exact continuations. First-page typed records and resolved original links can be followed by ID. |
| `get_supporting_work` | Interpreted uses/choices, quantities, selected parts/formulations, unresolved scopes, cycles and explicit truncation. Only required whole-preparation uses expand recursively. |

Search returns publication/model/book/source/target citations. Follow the target
with `read_book_content` until `next_cursor` is null before assessing a recipe.
For library-wide recipe discovery, also search `kinds=['source']`: 39 books do not
yet have recipe records. Empty recipe results never establish absence of a suitable
recipe. Source snippets and ranking cannot supply dietary or subjective judgments.

The existing `search_library`, `read_section`, image tools and recipe-card renderer
remain compatible. New recipe-card citations accept a model snapshot and target
in place of a legacy section. Books retain legacy section/image IDs.

## Runtime ownership and rollback

The image pins official Typesense 30.2 Linux/amd64 bytes by checksum and runs a
source-free Linux engine startup/health/shutdown check during the build. The hosted
worker owns a loopback-only engine on ports 8120/8121, a private random API key and
a fixed keyword-only schema. It enables no vectors, embedding fields, models,
search analytics or query/access logging. Source data stays on the existing private
runtime volume and object store.

Each publication gets a collection bound to its model checksum and exact record
count. Failed imports are rejected. Activation prepares the collection before
committing the local active pointer; failed preparation preserves the previous
publication. Engine death fails health/readiness so the existing supervisor can
restart the whole owned process group. Restarting reuses a complete matching index. Lookups for a prepared publication
do not wait behind another publication's index import.
Retained publications continue to resolve exact citations.
Owned-engine startup allows up to 180 seconds for a persisted index reload. The
supervisor allows up to 600 seconds before the first healthy probe, covering
engine load and runtime byte checks. After the first healthy probe, three failed
30-second probes trigger recovery without waiting for startup grace again.

Recovery hashes every runtime artifact on every attempt. A successful full-model
validation receipt is bound to the manifest hash, validator/type/helper code and
SQLite/Pydantic versions. It reuses structural checking only for identical bytes
and rules; missing, broken or stale receipts require the full pass. A failed
receipt write cannot quarantine valid sources. The full pass has one bounded
128 MiB SQLite cache and reclaimable read-only mappings; ordinary readers retain
their smaller request caches. Mapped address space does not increase the VM RAM
limit.

Full integrity checking can thrash on a serving Machine smaller than the source
database and its indexes. For this first publication, preflight the exact release
validator and library versions in a bounded, non-serving temporary Linux Machine.
It restores and hashes the exact manifest's runtime artifacts, performs the complete structural pass,
and exports that image's receipt. Install the receipt on the serving volume only
after checking its manifest/validator/report identity and rehashing the volume's
actual artifacts. Normal recovery still rehashes those artifacts independently.
Remove the verifier and its temporary source copy after it completes. A changed
validator or library version requires a new full preflight; receipts cannot be
fabricated from counts or from a different validator's result. Engine lifecycle
changes do not invalidate a model receipt when its validation identity matches.

Roll out the image on the existing Machine without replacing its volume/config,
then publish the structured artifact. Save the previous image, Machine config and
active pointer first. Roll back with the previous image and a conditional pointer
change; retain all publication artifacts and source records. Indexes are derived,
so source restoration does not depend on them.

## Verification

Synthetic EPUB checks cover duplicate spine occurrences, inline text, oversized
UTF-8 continuations, scoped IDs/cursors, corrupted artifacts, failed index
preparation and recipe citations. Supporting-work checks cover cycles, depth/size
budgets and preservation of partial scope. The selected non-OCR suite passed 65 Python
checks; the recipe viewer passed 11 JavaScript checks. The remotely built Linux
image passed its owned-engine health check.

The real 59-book publication validated 2,555,681 source nodes, 656,586 spans and
491,546 derived search units. Local official-SDK checks exercised all 14 tools'
discovery, real keyword lookup, complete recipe source continuation, source-only
books including Chop Chop, candidate exclusion, cross-book rejection, auth and
legacy search/read compatibility. The frozen trial pool had zero missing anchors
among 19 occurrences at allowance 25 through the new adapter using the same
literal query terms. This is a migration check on a small catalog-browsed pool,
not a held-out recall, precision or owner-fit result.

Initial local validation plus indexing took 130 seconds; observed peak engine RSS
was 341 MiB and its disk index was about 317 MiB. Hosted immutable checksum readback
verified 11,593 objects (8.99 GB). A full Linux preflight passed in 119 seconds on a
bounded temporary 4 GiB Machine, which removed itself. The unchanged 1 GiB serving
Machine independently verified its runtime bytes before installing the receipt.
Authenticated hosted MCP acknowledgement, all 59 source roots, real keyword/typo
lookup, supporting work and current/retained legacy reads passed. Linux engine
peak RSS was 304 MiB. The first cold check reproduced a too-short 60-second engine
startup deadline; the corrected timeout and post-startup watchdog behavior both
have regression checks. Final cold recovery is recorded in the implementation
ticket before completing rollout.

The semantic schema remains draft-v1. Validation checks canonical order/text,
evidence ownership, typed references, selected preparation ownership and relation
ownership. Complete semantic parent/endpoint policies, table-grid interpretation,
correction lineage and owner acceptance remain follow-up work; records are not
promoted to reviewed by this deployment.
