# Scanned PDF recall plan

Research proposal, October 11, 2026. This records a recommended direction, not an
agreed domain-model change or publication policy. No OCR, ingestion, model
inference, book upload, correction acceptance, or runtime change was performed.

## Recommendation

Convert scans into a **structured, page-linked transcription** that feeds the
same whole-book reader and search model as text-bearing EPUBs. Keep the PDF as
the authoritative book edition. An EPUB or Markdown export can provide a useful
reading copy, but the export is not the canonical transcription: we need page
regions, reading order, candidate history, corrections, and unresolved content.

The target is a versioned JSON representation stored in SQLite: ordered content
blocks with source spans, plus supported recipe, passage, and reference-entry
records. Derived FTS rows index complete logical units, including recipes that
continue across physical pages. Every result resolves back to the original
pages and, where available, their regions. Preserve the book's prose, captions,
tables, and notes as well as recipes.

This extends the existing [whole-book model proposal](whole-book-model.md).
Its current schema is explicitly EPUB-only; PDF page/region locators and
transcription/correction lineage need a designed extension, not invented EPUB
document paths.

## What currently loses recall

- [PDF extraction](../src/cookbook/extract.py) uses one section per physical page,
  titled `Page N`. EPUB extraction uses headings and authored navigation for
  smaller logical sections and recognizes some bounded recipes.
- [Search](../src/cookbook/library.py) requires every query token to occur in one
  FTS row. A recipe title on one page and a requested ingredient on the next
  therefore cannot match together. Conversely, one page containing several
  unrelated recipes can match terms that belong to different recipes.
- Existing PDF text is selected whenever it has at least 40 word characters,
  unless full OCR is explicitly selected. Length does not establish that a
  hidden OCR layer is correct or that image captions are covered.
- [OCR parsing](../src/cookbook/ocr.py) retains word text, confidence, width, and
  height, but discards word positions and hierarchy identifiers from its TSV
  word records. These are needed for region association and layout recovery.
- The [published EPUB corpus](full-epub-publication.md) has functional search
  checks and latency measurements. Those checks do not measure retrieval recall
  against an independently labeled set. Image-only EPUBs share the scan problem.

A pure in-memory SQLite FTS5 check using synthetic text confirmed the page-boundary
failure: `lemon AND paprika` missed both separate page rows, but matched an
assembled recipe row containing the same unchanged text. This demonstrates the
mechanism; it is not a measured improvement on real books.

The private September 13 corpus report supplies the recognition evidence:
`/Users/rick/cookbook-mcp-data/poc/pdf-corpus-20260913/report.md`.
The best single tested OCR configuration passed 19 of 31 frozen short-span
checks, versus 17 for default whole-page Tesseract and 15 for native extraction.
All five explicit fraction checks failed across the tested OCR variants. These
were purposively selected difficult pages, not whole-library accuracy estimates.
Native extraction preserved a fraction that OCR lost on another page. Increased
regional rendering density did not repair the tested fraction failures.
See [trial methods](pdf-corpus-trials.md); private source content stays outside Git.

## Representation and processing

1. **Keep source evidence.** Hash the original edition; inventory physical pages.
   Printed labels and spread halves are separate from physical page ordinals.
   Render the complete PDF composition, including its image/mask layers.
2. **Keep transcription candidates and geometry.** Preserve native text and OCR
   candidates with page/region positions, line/block identities, language,
   engine/model/configuration identities, and image/text hashes. Record the full
   mapping from rotated, deskewed, or cropped coordinates to original-page
   coordinates. OCR confidence is triage information, not an acceptance rule.
3. **Recover ordered content.** Represent headings, paragraphs, ingredient
   lists, methods, captions, sidebars, and table rows/cells. Explicitly handle
   columns, spreads, continuation pages, and quantity-to-ingredient associations.
   Keep ambiguous regions and omitted/unreadable source text unresolved. Keep
   running headers and page numbers as source content while excluding them from
   recipe search projections where their role is established.
4. **Attach meanings and review corrections.** Recipes and passages select the
   transcription's source spans instead of owning another copy of the text.
   Preserve raw fractions and units; interpreted quantities can be exact
   rationals alongside the source wording. Source-grounded correction proposals
   remain proposals until accepted under the existing policy. Agent review and
   human approval remain distinct.
5. **Build search projections.** Index complete supported recipes, passages,
   reference entries, and useful fallback source blocks. Retain exact evidence
   locations and deduplicate hits from overlapping projections. Use bounded
   source spans within very long units so finding a chapter does not require
   returning the entire chapter. Do not join adjacent pages indiscriminately:
   that would introduce matches across unrelated recipes.

Begin with the existing local Tesseract path, retaining its geometry and adding
the page adapter and logical search units. Compare a layout-capable alternative
only as a controlled candidate. Official documentation supports hOCR/ALTO or
TSV as intermediate OCR evidence, and richer document JSON for layout-aware
tools; it does not prove cookbook transcription quality. See
[official-source format research](scanned-pdf-format-research.md).

A searchable PDF alone supplies a text layer, not verified recipe boundaries or
correct table associations. An OCRmyPDF sidecar alone is incomplete for mixed
documents because it can omit existing or skipped text. Plain Markdown alone
does not reliably carry cell geometry and revision provenance. All can be
derived artifacts rather than the only retained representation.

## A small experiment that can establish the next step

Freeze approximately 30–50 source-grounded queries over a few complete recipes
and passages before tuning. Include single-page and continued recipes, multiple
recipes per page, ingredient columns, batch tables, fractions, captions, and
prose. Use some old diagnostic pages for development and different complete
recipes for held-out evaluation; freeze references and missing/unreadable spans
before candidate generation. A small trial validates direction, not all-book
readiness.

Where available, compare a scan and EPUB containing the same edition/content.
Otherwise compare against an independently checked transcription of the exact
scan. Different books, editions, or inventories cannot supply a direct format
parity claim. Queries asking for subjective suitability or synonyms should be
reported separately from literal title/ingredient retrieval, because the
current lexical search also limits EPUBs on those requests.

Compare four conditions with the same query semantics and result limit:

1. Independently checked reference text with checked logical units.
2. Current page-based extraction.
3. Candidate transcription using page-based units.
4. The same candidate transcription using assembled logical units.

This separates transcription losses from boundary/association losses. For any
paired EPUB, also measure its actual current search baseline rather than
assuming it is perfect.

Measure two outcomes independently:

- **Finding:** recall@10 over labeled recipe/passage targets, first relevant
  result rank, missing headings/ingredients/regions, and unrelated-recipe
  matches. Count a target once even if several overlapping search rows return it.
- **Reading:** full ingredient-list and instruction completeness; exact
  quantities/fractions/units; table-cell association and reading order; source
  citation resolution; unresolved content and review effort. Report corrected
  results separately from uncorrected candidates.

Agree a parity margin after the baseline is measured. A candidate may find a
recipe while still mistranscribing its amounts. For accepted trial recipes,
require no unresolved ingredient amounts or missing instructions and check
citations against the original pages. Even a clean small sample does not justify
automatic acceptance of an entire book.

Mugaritz's image-only recipe pages and Babbo's known fraction failures provide
useful contrasting development cases from the existing private trials. Add
held-out pages and a table/continuation case. These are suggested trial choices;
no new scan processing was run for this note.

## Execution boundary

Every future PDF/DjVu ingestion, render experiment, OCR or model run uses
[`scripts/ocr_sandbox.py`](../scripts/ocr_sandbox.py), after reading
[resource isolation](ocr-resource-isolation.md). Preserve the 4 GiB/two-CPU Linux
VM ceiling, 2 GiB job memory, zero swap, 64 PIDs, and five-minute job deadline.
Use sequential resumable small jobs and private input/output directories.
Alternative models must prove they fit those limits before real-book trials;
limits are not increased to accommodate them. No remote book-data transfer is
part of this proposal.

Production integration must retain fail-closed admission and digest-bound review
gates, version new extraction identities, and preserve the original edition and
previous publications. First deliver a private comparison and reviewable
transcription, then decide whether its evidence supports broader ingestion.
