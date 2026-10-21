# Scanned transcription prototype contract

This opt-in local prototype is separate from the EPUB whole-book draft and the
production publisher. It retains recognized evidence; recognition is not source
truth, and a candidate or agent review does not imply approval.

The pure stdlib interface in `cookbook.transcription` is:

```python
validate_snapshot(snapshot) -> None  # ValueError for malformed evidence
snapshot_digest(snapshot) -> str     # canonical JSON SHA-256 after validation
adapt_docling(edition, pages, document, predictions) -> dict
```

`adapt_docling` consumes saved JSON, not models. `pages` is a list of evidence
pages, `document` is Docling document JSON, and `predictions` maps page IDs to
Docling saved page prediction JSON. No function opens files or performs OCR.
Book-derived callers must run through `scripts/ocr_sandbox.py` with its admission
guard before input reads. Synthetic pure validation tests can run locally.

## Exact JSON shape

Version is `scanned-transcription.v1`. A snapshot has exactly `version`,
`edition`, `pages`, `blocks`, `tables`, and `diagnostics`.

- `edition`: `{id, source_sha256, format}`; format is `pdf` or `djvu`.
- Each page: `{id, physical_page, source_page_sha256, render_sha256,
  render_size, source_size, render_to_source, recognition, lines}`. Sizes are
  `[width, height]` with positive finite dimensions. `physical_page` is one-based.
  Page source hash identifies the page evidence manifest, not a claim that a PDF
  page has standalone original bytes. `render_to_source` is the invertible affine
  `[a,b,c,d,e,f]`: `(x,y) -> (a*x+c*y+e,b*x+d*y+f)`; both coordinate spaces use
  top-left origin. `recognition` is `{method, artifact_sha256}`. Each line is
  `{id, text, polygon, confidence}`. Polygons have four `[x,y]` points in render
  pixels; text is never normalized or overwritten. Confidence is null or in
  `[0,1]`. Canonical lines occur exactly once globally in page order.
- Each block: `{id, page_id, kind, line_ids, children, marker}`. `kind` is the
  Docling label or `unclassified`; marker is null or the separately retained
  authored list marker. Blocks reference canonical lines, never copy their text.
  Children reference block IDs on the same page; cycles are rejected. Hierarchy
  may repeat references to parent evidence. Leaf/top-level geometry does not
  establish recipe ownership. Every line has at least one block reference;
  unsupported/unassigned text receives an explicit unclassified block.
- Each table: `{id, block_id, page_id, rows, columns, cells}`. Each cell:
  `{id, row_start, row_end, column_start, column_end, line_ids,
  column_header, row_header}`. Offsets are zero-based half-open ranges.
  Nonempty grids cannot overlap. Header flags retain model predictions, not
  approved formulation semantics. Ambiguous geometric line matches stay
  unassigned to cells with a diagnostic; canonical lines remain available.
  A full canonical line cannot be assigned to more than one table cell.
- Each diagnostic: `{code, page_id, block_id, line_ids, detail}`. Optional
  references are null, and detail is a nonempty explanation. Unsupported,
  ambiguous, missing and suspicious structure is recorded here.

IDs are nonempty strings unique within their record namespace, and line IDs are
globally unique. Every referenced ID must resolve within its page. Hashes are
lowercase 64-digit SHA-256. Coordinates must be finite, inside their render and
map inside source bounds; degenerate polygons and transforms are rejected.
Source physical pages and page IDs cannot repeat. Input/output JSON is copied;
mutating a returned snapshot does not mutate the caller's evidence.
The pure validator checks declared lineage and references, not the bytes of
original books or manifests. A guarded file-owning caller must independently
verify all declared hashes against its immutable source inventory. Saved Docling
JSON and its input hashes must accompany the derived snapshot; model-specific
metadata is flagged rather than interpreted by this adapter.

## Independent semantic and review proposals

Consumers store their own records alongside a digest-bound snapshot, without
modifying raw evidence. A semantic candidate selection uses `id`, `kind`
(`recipe`, `passage`, `reference_entry`, `unclassified`), ordered `line_ids`,
`state` (`candidate` or `unresolved`), and `reasons`. Recipe parts and continuation
or supporting-work relationships are separate proposals over selections.

A review proposal identifies its snapshot digest, source line IDs, inspected
render hashes, field/target, proposed value and state. Unresolved values are
explicitly null with reasons. Corrections can replace displayed readings only
in a derived view; they do not overwrite canonical recognized text. Review
agents define and validate these proposal records in their own modules.

## Saved Docling adapter

The adapter checks frozen prediction cell indices, original text and coordinate
roundtrips against canonical lines. Top-level predicted cells must assign each
line exactly once; invalid indices, changed text, duplicate or missing cells
fail closed. It traverses nested picture/group children and list markers in the
saved document, preserving line geometry rather than relying on Markdown.
Tables retain model row/column offsets and flags; they are not automatically
interpreted as formulations. Unsupported saved JSON nodes remain diagnostics.
