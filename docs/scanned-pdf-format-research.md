# Scanned PDF representation research

Research checked against official documentation on October 11, 2026. This is a
technical supplement to the [recall plan](scanned-pdf-recall-plan.md), not an
engine benchmark or an extraction-policy change. No OCR, PDF/DjVu ingestion,
model inference, book upload, or OCR tests were run for this research.

## Recommended representation

Use a source-backed, ordered transcription with page/region evidence, then build
recipe and passage search units over it. Treat Markdown and EPUB as optional
reading exports. Changing the container cannot recover missing words, correct a
quantity, or join a recipe split over pages; those require transcription and
assembly work. This recommendation is an architectural inference, consistent
with the existing [whole-book model](whole-book-model.md), whose current schema
is deliberately EPUB-only.

The proposed PDF adapter should retain:

- Immutable book-edition bytes/hash and physical page ordinals; printed page
  labels are a separate, possibly unresolved interpretation.
- Page dimensions, original rotation, derived-image hashes, render settings,
  crop boxes, and the transforms between OCR coordinates and original-page
  coordinates. Boxes from deskewed or rotated images cannot be cited directly
  without that mapping.
- OCR blocks, paragraphs, lines and words with text, geometry, engine/model
  identity, confidence and candidate alternatives. Keep raw engine output as
  private evidence; confidence is a review signal, not proof of correctness.
- Explicit proposed reading order and table cell associations. Retain headings,
  captions, sidebars and furniture as distinguishable content rather than
  silently discarding every repeated region.
- Recipe, recipe-part and passage selections spanning any required pages or
  regions, with corrections and unresolved content tied to their source spans.
  Preserve complete ingredient/method text independently of parsed fields.
- Separate authored text and search normalization. Fraction equivalences,
  whitespace and dehyphenation can improve matching without overwriting the raw
  transcription. Ingredient names, amounts, units, ranges and formulation
  associations need source-supported interpretation.

These are proposal requirements, not claims that an existing converter delivers
them correctly. A plausible implementation stores geometry-rich transcription
once, adds semantic selections over it, and builds the same derived search
interface used for EPUB content. The original scan remains the source truth.

## What the current engines can supply

### Tesseract: retain its structured evidence first

Tesseract's documented hOCR includes page/block/paragraph/line/word hierarchy,
bounding boxes, line baselines and word confidence. TSV supplies page, block,
paragraph, line and word numbers plus left/top/width/height/confidence/text.
Its command line accepts explicit multilingual combinations; language order
can change recognition. PSM 3 performs automatic page segmentation; PSM 6 assumes
a uniform block. These outputs provide a useful adapter foundation, rather than
only flattening OCR into page text. They do not establish cookbook recipe
boundaries. [Tesseract command-line documentation](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

Tesseract also exports ALTO XML. ALTO's maintained standard supports layout
metadata, language/direction and explicit reading-order structures. Standard
expressiveness does not mean Tesseract populates every feature; inspect the
actual installed renderer before depending on one. ALTO/hOCR are suitable raw
interchange artifacts, while a cookbook adapter still owns semantic assembly.
[Tesseract release notes](https://tesseract-ocr.github.io/tessdoc/ReleaseNotes.html),
[Library of Congress ALTO standard](https://www.loc.gov/standards/alto/).

Official quality guidance identifies skew, binarization, segmentation and
resolution as factors, and explicitly notes weak table recognition without
custom segmentation/layout analysis. Its dictionary behavior can be adjusted,
including domain word lists. Such adjustments are experiment candidates, not
automatic fixes for fractions or ingredient rows.
[Tesseract quality guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).

**First candidate:** keep the existing isolated Tesseract baseline, preserve all
TSV geometry/identifiers and coordinate transforms, then assemble bounded recipes
from a small frozen sample. This tests the representation/search change without
conflating it with an engine replacement. Existing regional trials already
exercise default/best English recognition; do not repeat that comparison without
a new structural or retrieval question.

### OCRmyPDF: useful derivative, insufficient canonical book text

OCRmyPDF adds a searchable text layer and supports preprocessing. Its text
sidecar explicitly excludes existing text on pages that were not OCRed and pages
skipped by page selection, size or timeout options. The docs recommend separate
PDF text extraction for combined native/OCR text. They also warn that processing
can alter image content and should be reviewed. A searchable PDF is a useful
reading derivative; a sidecar alone is not a completeness-preserving book
transcription. [OCRmyPDF cookbook](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html).

**Implication:** avoid a PDF-to-sidecar-to-EPUB shortcut as the canonical pipeline.
If OCRmyPDF is trialed later, retain original pages, distinguish native/OCR
provenance and explicitly account for every page. It is not the first experiment
needed to resolve page-based recipe recall.

### Docling: candidate for layout and ordered document structure

DoclingDocument represents text, tables, pictures, hierarchy, furniture,
provenance and available boxes. Reading order lives in its body tree and child
order. Its provenance model exposes page number, bounding box and character
span. This is close to the structural evidence the PDF adapter needs, although
its hierarchy does not certify cookbook recipe boundaries or quantity accuracy.
[Docling document model](https://docling-project.github.io/docling/concepts/docling_document/),
[Docling provenance reference](https://docling-project.github.io/docling/reference/docling_document/#docling_core.types.doc.document.ProvenanceItem).

Models can be prefetched and selected through `artifacts_path`; remote services
require explicit opt-in. It offers a Tesseract CLI OCR adapter and full-page OCR,
so layout conversion need not imply replacing recognition. Threaded pipeline
batch sizes influence memory; current reference defaults include batches of four.
Pin a tested version and explicitly set smaller batches rather than importing
unreviewed defaults. [Offline/local configuration](https://docling-project.github.io/docling/usage/advanced_options/),
[Pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/),
[Full-page OCR example](https://docling-project.github.io/docling/_generated/examples/full_page_ocr/).

**Later candidate:** a pinned CPU pipeline with local staged weights, Tesseract,
single-page/batch-one processing, optional enrichments disabled, and table
structure enabled only for a frozen table case. Neither docs nor model download
sizes establish peak RAM or five-minute completion in this project's sandbox.
Admission and fit must be measured before any broader corpus trial.

### PaddleOCR PP-StructureV3: candidate for ordered blocks and tables

The official pipeline describes layout/table/formula processing, multi-column
reading-order recovery and Markdown output. Its JSON includes ordered
`parsing_res_list` entries with block boxes, labels, content and order, plus OCR
polygons, detection/recognition scores and recognized text. Language/model
selection and module toggles are explicit; model directories must be supplied
to avoid default downloads. Formula recognition is a separate optional module;
its existence does not demonstrate correct small inline cookbook fractions.
[Official PP-StructureV3 pipeline documentation](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PP-StructureV3.en.md).

**Later candidate:** a pinned CPU layout/OCR configuration with local weights,
one frozen page, and unused orientation/unwarping/seal/formula/chart modules
disabled. Its peak runtime footprint under the current limits is unproven. The
previous Mac environment is disabled and must not be revived for this trial.

## Experiment boundary and evidence needed

All future recognition, rendering and PDF/DjVu parsing must use
`scripts/ocr_sandbox.py` after its doctor passes. Current ceilings remain a
4 GiB/two-CPU Linux VM, a 2 GiB no-swap whole-job cgroup, one concurrent job and
an independent five-minute deadline. Model preparation is a separate controlled
step; trial jobs have no network and books stay local. Failure to fit is an
experiment result, not permission to loosen limits. See
[resource isolation](ocr-resource-isolation.md).

Freeze source-grounded references before recognition. Include whole recipes,
cross-page continuations, multiple columns, sidebars, batch tables, small mixed
fractions and faint/obscured content. The initial trial retains the project's
English-only recognition policy; evaluating additional languages is a separate
scope choice.
Prior [private trials](pdf-corpus-trials.md) provide matched pages and diagnostic
results; their snippet scores do not measure full reading order or completeness.

Compare candidate OCR against independently checked transcription, then compare
search against the same transcription indexed through the EPUB-quality path.
Measure candidate-to-reference recipe retrieval, recipe boundary/assembly
accuracy, full ingredients/instructions completeness, quantity/unit fidelity,
source locator correctness, unresolved content and review effort separately.
Include peak memory, elapsed time and sandbox exits. An improved phrase recall
score cannot excuse a wrong quantity or a missing method paragraph.

Converter documentation establishes available outputs and knobs. It does not
establish recall parity, cookbook transcription accuracy, review acceptance or
resource feasibility. Existing publication/review decisions remain unchanged.
