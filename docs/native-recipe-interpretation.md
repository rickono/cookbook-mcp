# Native recipe interpretation

[Fill recipe structure across the published EPUB library](https://github.com/rickono/cookbook-mcp/issues/26)
extends the immutable whole-book publication with candidate recipe structure.
The owner selected the whole-book model and deferred the image-only book until
protected OCR is available. Original books and source nodes remain authoritative.

## Build

```sh
cookbook interpret --build /private/verified-whole-book-build --output /private/new-build
```

The command verifies every input against its manifest, copies the canonical
source database into a new publication, retains existing recipe IDs and supported
records, adds uncovered candidate occurrences, refreshes semantic search units,
and runs the complete structural validator. It never changes the input build.
Source search units, DOM nodes, reading occurrences, links, navigation and source
resources are retained. Book contents, derived artifacts and credentials stay
outside Git.

`recipe_markup.json` contains publisher selectors bound to exact source hashes.
A profile for different source bytes is refused as interpretation evidence, with
its coverage reason exposed. The profile version and implementation hashes are
recorded in the model snapshot. Missing or rejected markup does not establish
that a book has no recipes; the private `recipe-interpretation.json` keeps the
rejected headings and per-book coverage for review.

The first native pass proposes 7,266 recipes across 55 books, up from 2,632 in
20 books. It exposes 76,761 ingredient occurrences, 42,599 instruction
occurrences, 5,371 parts and 7,018 preparation/source references. Three reference
works remain source-searchable without fabricated recipe records. The remaining
image-only book is explicitly pending protected OCR and review. These are
candidate counts, not an independent recall estimate or reviewed completeness.

## Interpretation limits

Native paragraphs, styled divs, nested lists and ingredient table rows retain
exact source spans. Inline ingredient styles require complete paragraph coverage.
Prose preparations can have no numeric quantity; their authored boxed content is
kept separate from surrounding narrative. Local notes and variations are retained
where the source markup supports them.

Native SVG text and fragmented page paragraphs have candidate layout profiles.
Wrapped SVG ingredient fragments require review. A whole ingredient paragraph
that cannot be split safely stays an ingredient-group part with no invented group
heading; it is not represented as individually parsed ingredient requirements.
Original spacing and locators remain accessible through source reads.

Only simple leading quantities are parsed into candidate rational amounts and
finite authored units. Ranges, equivalences, products, compound amounts and
formulation ownership remain unparsed. An authored link can resolve a preparation
or source target, but its requiredness and whole/partial/variation scope remain
unresolved. Unlinked dependencies are not inferred. Previously supported
examples are preserved; candidate records are not promoted to reviewed content.

## MCP reading

`read_book_content` has two separate continuations:

- Follow `next_cursor` for the complete original source selection.
- Follow `next_related_offset` as `related_offset`, with no source cursor, for
  all typed ingredient, instruction, part and reference IDs. Children are ordered
  by kind, authored ordinal and ID; follow each child ID with the same book and
  publication.

Both retain bounded responses. Candidate inclusion remains explicit in Typesense
retrieval. Recipe ranking does not establish suitability; source search remains
necessary for omitted or uninterpreted content.

## Verification and rollout

The selected non-OCR suite passes 71 checks. Synthetic cases cover nested-list
occurrences, exact source boundaries, continuation paragraphs, prose without
numeric quantities, complete inline coverage, source-hash refusal, preservation
of supported quantities, unresolved preparation scope and complete child paging.
The new module and its tests pass Ruff; broad linting also reports two existing
exception-boundary warnings in CLI/server code.

The actual native build passes complete structural validation. Library-wide
source fingerprints confirm exact preservation of 2,555,681 nodes, source search
units, resources, reading occurrences, navigation and links. All 2,632 retained
recipe IDs and the 2,704 original semantic records keep their supported content
and evidence. Real official-SDK checks discover 14 tools, retrieve a recipe title
in each of the 55 recipe books, follow full source continuations and every child
page for six differently formatted books, and verify candidate filters, source
reads, auth, cross-book rejection and legacy compatibility.

The frozen pool has 5 missing anchors among 19 occurrences at allowance 25 with
literal keywords, and 6 with the original request text. The prior corpus had zero
misses on both. Diagnostic ranking places the five literal misses at ranks 28,
62, 62, 76 and 88. Smaller title weights and stricter matching do not fix the
regression; summed scores or book diversity reduce but do not eliminate it. No
anchor pinning or relaxed evaluation allowance is applied. This small
catalog-browsed pool is not held-out recall or owner-fit validation. The expanded
global index is held for retrieval review because this comparison has regressed.

The matching release image passes complete Linux validation in 130 seconds on
a bounded temporary 4 GiB verifier (peak validator RSS about 2.74 GiB); the
verifier exits successfully and removes itself. The receipt remains private.
This verifies the artifact, not serving capacity for both old and new indexes.

Publish through the existing immutable checksum-readback and acknowledged
activation lifecycle. Retain old versions for exact citations and rollback. The
10 GiB serving volume has about 2.9 GiB available; the new runtime artifacts alone
need 3.42 GB before indexing. Activation must wait for retrieval acceptance and
an approved storage increase, while the existing live publication stays active. OCR, Docker and
model execution remain outside this native pass.
