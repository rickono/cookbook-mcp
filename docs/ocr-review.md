# OCR execution safety update

OCR/model runs and OCR tests now require the [resource-isolated launcher](ocr-resource-isolation.md). Historical native commands below describe earlier runs; they do not authorize native OCR execution. Existing review decisions and publication policy are unchanged.

# Approved scan correction and review — September 11, 2026

Latest result: the user deferred all PDF/DjVu books to an OCR follow-up. The current first hosted trial selects only EPUB IDs 5 and 40, Momofuku and Ottolenghi Flavor. It is `/Users/rick/cookbook-mcp-data/poc/build-trial-20260912-epub-only`, publication `b7619e4f7b4348aa8d7be7b92b175ee3`. Its 353 manifest files, SQLite integrity, 338 sections, 343 images and unchanged retained-book records are verified. There are zero OCR assessments and zero pending decisions, and the quality gate passes without any review-policy exception. No real-page review decisions were applied. The previous four-book trial and its 59 pending pages, like Casa's earlier evidence, are preserved for the follow-up. This supersedes the trial selections below; those sections preserve historical evaluations.

The completed vision work was a purposive sample, not a complete review: see private `build-ocr-trial-20260912-fullscan/vision-review/sample-summary.md` and `sample-findings.json` under the same `poc` directory. Recommendations have not been applied. In addition to the flagged queue, Wine physical page 2 has obscured source text despite passing automatic checks; Wine page 423 is also obscured. Those known source limitations require explicit handling before acceptance, rather than assuming that clearing the queue establishes correctness.

## Complete five-book trial rebuild — September 12, 2026

Rebuilt the approved snapshot books 5, 40, 6, 9 and 45 into private directory `/Users/rick/cookbook-mcp-data/poc/build-ocr-trial-20260912`, publication `af17ca0348974073ab6b2bd5c584047e`. No publish, cloud upload, Calibre mutation or review approval occurred. The build exited with the expected review-required status 3.

Verified every manifest entry: 361 files, 796,199,578 bytes; SQLite integrity is `ok`, only the five approved books are exposed in the index, and a local FTS query resolves 578 sections. The build contains 1,951 sections and 343 EPUB images. EPUB text matches the prior build by source document/section; their IDs use the previously implemented version-2 extraction policy. Tu Casa Mi Casa's 233 physical-page identifiers match the prior build.

| Book | Pages sent through OCR | Pending human review |
| --- | ---: | ---: |
| Momofuku | 0 | 0 |
| Ottolenghi Flavor | 0 | 0 |
| Tu Casa Mi Casa | 99 | 94 |
| The Professional Chef | 78 | 45 |
| The World Atlas of Wine | 23 | 14 |
| Total | 200 | 153 |

All 200 OCR assessments and their preview-image hashes were checked. The core publication quality gate refuses the build while these 153 decisions remain unresolved. Flags overlap: 54 pages have no recognized text on nonblank images, 46 sparse text, 32 uncertain quantities, 52 low mean confidence, 58 many uncertain words, 43 ambiguous orientation, and one reaches the skew search limit. Flags do not imply that all 153 pages contain errors.

The private `review-overview.html` is a read-only visual gallery; `review-guide.md` groups links by book and physical page. Existing per-page reports compare original/derived images and extracted text. The gallery uses local file URLs and makes no external requests. No review decisions are submitted by either artifact.

### Additional confirmed embedded-text issue — policy decision pending

Tu Casa Mi Casa physical page 20 (printed page 22, Nixtamal and Masa) contains corrupt embedded PDF text, including its printed quarter-teaspoon fraction. The current extractor only invokes OCR when native text has fewer than 40 alphanumeric characters, so this page's 2,202-character embedded text is used without an OCR assessment. An earlier forced-OCR evaluation also misread the fraction as `4 teaspoon` and garbled ingredients; that cached assessment is **not** part of the new build's 153-page review queue. This distinction was verified against the new index and corrected in the review artifacts.

The exact source, section, publication and text hash are recorded in private `embedded-text-finding.json`; `embedded-text-finding.html` compares the original image with the actual indexed text. `validation.json` reports this additional issue and `ready_for_trial: false`. The original page image is tied to the same source hash and physical page. The finding requires resolution before publishing this book; the current automated OCR gate alone does not cover it.

Proposed next decision: treat Tu Casa Mi Casa's existing PDF text as untrusted and re-OCR all its pages under the review policy, then review the flagged results. Alternatively, defer this book from the first hosted trial while retaining the other four fixtures. This changes which source text is trusted and the amount of OCR/review work, so it has not been applied without the user's choice. No other PDFs have been silently reclassified.

Validation runner: `/Users/rick/cookbook-mcp-data/setup/verify-ocr-trial.py`; build progress log: `/Users/rick/cookbook-mcp-data/poc/build-ocr-trial-20260912.log`. These private artifacts contain book-derived data and are outside Git.

The user approved automatic rotation/skew correction on derived OCR images and mandatory review of suspicious OCR before publication. Both are implemented locally. Original files and their physical page order remain unchanged. There is no new cloud upload or deployment.

## Behavior

Each low-text PDF/DjVu page is rendered into a bounded derived image. Four quarter-turn orientations are compared using Tesseract confidence, recognized word count, and word-box geometry. Geometry matters: testing demonstrated that Tesseract can recognize sideways text while leaving the page sideways. The chosen orientation is deskewed with a projection-profile search, then OCR runs again at the final image size.

The publisher flags low overall confidence, many uncertain words, uncertain numeric/fraction tokens, sparse text, ambiguous orientation, a skew estimate at the search limit, and nonblank pages with no recognized text. An effectively white blank page is not blocked merely because it has no text. An illustration that produces no text needs a human non-text decision; it is not silently classified as blank.

Confidence flags are triage, not an accuracy guarantee. High-confidence mistakes, faint content, handwriting, warped photographed pages, and native-text pages containing an additional scanned region remain limitations. Original page images remain available for checking quantities. The page rendering tool returns the original orientation; correction applies to the OCR copy.

Reversible initial thresholds are recorded in `ocr.SETTINGS`: 85 weighted mean confidence, word-confidence threshold 60, more than 15% uncertain words, numeric/fraction confidence below 85, fewer than four words, orientation-score margin below 8, and a deskew search of ±5° in 0.25° steps. OCR images remain bounded to 2500 pixels on the long edge; orientation probes use 1600. These are empirical starting points, not calibrated error probabilities or a claim of comprehensive scan-quality detection. Each subprocess retains the 90-second failure/timeout limit; a page involves multiple subprocesses.

## Review and publication gate

New builds use manifest schema 2 and include `quality/ocr-review.json` in their verified inventory. Every OCR section has an assessment bound to its source hash, physical page, result hash, and effective text hash. Cache identities include the algorithm/settings, renderer version, Tesseract version, English trained-data hash, Pillow version and NumPy version. Older cache results do not silently inherit the new policy.

The core `publish()` function checks quality before writing even the staged remote/local manifest. Clearing a summary pending list does not bypass per-section checks. Missing assessments, stale/mismatched decisions, changed text, or unresolved flags prevent publication and preserve the active pointer. The shell wrapper also stops when building returns review-required status 3.

A person may accept the displayed text, supply a corrected transcription, or mark an illustration/blank page as non-text. Decisions require the exact review ID and displayed result SHA-256. They are timestamped and bind to that exact result. Changed OCR processing requires a new result/review; old approvals are not transferred. The tool does not automatically accept flagged real-book output.

Original and corrected preview images plus raw OCR words/confidence stay in the private local cache. The script-free review report embeds its images and escapes source text, with a small index linking to one report per page. Each page provides concrete accept/non-text commands. Corrections are stored privately; only their hashes and decision metadata enter citations, so a search result cannot accidentally include an entire corrected page. The approved text and review audit are included in the publication's index/quality inventory. Temporary preview images remain local review evidence rather than durable publication artifacts.

## Commands

Run from the repository root. Paths below named `BUILD`, `CACHE`, and `NEW_BUILD` are explicit arguments, not literal defaults. `NEW_BUILD` must be a new directory outside Git.

```sh
PYTHONPATH=src uv run python -m cookbook.cli review-report \
  --build BUILD --ocr-cache CACHE --output /absolute/private/review.html

PYTHONPATH=src uv run python -m cookbook.cli review-ocr \
  --ocr-cache CACHE --id REVIEW_ID --result-sha256 RESULT_SHA256 \
  --decision accept
```

Use `--decision nontext` for an illustration/blank page, or `--decision correct --text-file /absolute/private/corrected.txt` for a reviewed transcription. Copy the exact ID/hash from the displayed report. No accept-all shortcut is implemented.

After all flagged pages in a build have decisions:

```sh
PYTHONPATH=src uv run python -m cookbook.cli finalize-local \
  --build BUILD --ocr-cache CACHE --output NEW_BUILD

PYTHONPATH=src uv run python -m cookbook.cli publish-local \
  --build NEW_BUILD --store /absolute/private/store \
  --runtime /absolute/private/runtime
```

Finalization creates a new publication ID and new index, applies reviewed text to both sections and FTS, and records the decisions. It does not mutate the prior build or publication. It reuses verified original/image inputs. The existing local `build-3` publication remains readable, but schema-1 builds are refused for new publication under this policy and need re-extraction. The full snapshot command still processes only the five approved fixtures.

## Verification and real-book evaluation

Final result: **34 automated tests pass**. Formatting and undefined/unused-name checks pass. The official MCP Inspector and 32 authenticated calls against the retained original publication also pass with the updated server. The Docker image builds successfully.

Automated tests now cover 90°, 180° and 270° scans, +3° skew, combined 90°/-2° rotation/skew, original-file immutability, preserved physical ordinals, known `1/2 teaspoon salt` / `200 grams beans` text, cache reuse, OCR failures/timeouts, sparse/empty/quantity flags, stale decision rejection, HTML escaping and image integrity, corrected FTS text, and core publication refusal before any object/pointer write. A synthetic end-to-end test reviews one flagged page, finalizes a new version, publishes it successfully, and resolves the corrected text through an exact page citation. Another test rejects legacy publication bypass.

The exact previously failing synthetic rotated PDF now corrects by 270° counterclockwise and preserves both known quantities. Its corrected image was visually checked and is upright and legible.

A targeted real evaluation reused the approved snapshot sources and examined nine deliberately difficult/representative pages across the two PDFs and DjVu. Seven require review. This is not an estimate of the whole library's rejection rate:

| Book | Physical page | Outcome |
| --- | ---: | --- |
| Tu Casa Mi Casa | 11 | Review: no text on a nonblank page |
| Tu Casa Mi Casa | 12 | Review: sparse text |
| Tu Casa Mi Casa | 20 | Review: overall confidence and a quantity |
| The Professional Chef | 13 | Review: sparse text |
| The Professional Chef | 14 | Review: no text on a nonblank page |
| The Professional Chef | 20 | Review: a quantity |
| World Atlas of Wine | 11 | Review: no text on a nonblank page |
| World Atlas of Wine | 20 | No automatic review flag |
| World Atlas of Wine | 55 | No automatic review flag |

All tested source-file hashes were checked before/after processing and matched. The evaluation took about 60 seconds. It did not finalize or publish a new real-book index, and no flagged real-book page has been approved automatically. Review evidence is under `/Users/rick/cookbook-mcp-data/poc/scan-policy-v2/`; open `review.html`. This queue is a sample, not a complete rebuilt publication. A full trial rebuild must evaluate all applicable pages before its next publication.

## Recipe refinement and citation compatibility

The approved EPUB re-evaluation identifies 75 bounded recipes in *Ottolenghi Flavor*. The rule requires a TOC-linked title block in the observed publisher style, ingredient blocks, and later method blocks within the same bounded section. Similar class names without all these conditions remain ordinary sections. *Momofuku* retains section-based reading under this conservative parser; no recipes are fabricated. All 141 real EPUB TOC entries still resolve. Generic section titles now use source TOC labels where available.

New EPUB section IDs use `extract-v2` and `epub-spine-v2`; previous publication mappings remain intact. Citations and publication diagnostics read their actual stored versions, including the legacy active publication. The 75 newly detected recipes are extraction evaluation results and will appear in the runtime only after a reviewed new publication is activated.

Implementation background: Tesseract documents [rotation/skew effects](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html) and [TSV confidence output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html). The correction/scoring and review policies above are this project's tested implementation, not promises made by Tesseract.

## Approved full-page OCR for Tu Casa Mi Casa

The user selected OCR for every page of Tu Casa Mi Casa after the embedded-text finding. Implemented `build --force-ocr-books 6` for this five-book snapshot; other selected PDF/DjVu books keep the existing low-text trigger. The fixture wrapper now includes this option so its next rebuild retains the choice. IDs must belong to the explicitly selected books and use PDF or DjVu format. Byte-identical selected aliases share the source's forced-OCR policy.

For a forced source, embedded text is not extracted or used as a fallback. Every physical page receives the existing English OCR assessment, including blank pages. Empty OCR results remain empty and still carry an assessment; nonblank pages with no recognized text retain the review flag. Existing valid OCR results can be reused from the digest-bound cache because the OCR algorithm and inputs have not changed. No review is automatically approved.

The verified quality inventory records `forced_ocr_sources`, and page locators record `text_selection: forced-ocr`. The publication gate requires an OCR assessment and OCR provenance on every page of each forced source. Finalization carries this policy into the new publication. Original source bytes and physical page identifiers are preserved. This ensures the known physical-page-20 issue enters the OCR review workflow, but does not claim that OCR automatically corrects the page.

Completed the new local build at `/Users/rick/cookbook-mcp-data/poc/build-ocr-trial-20260912-fullscan`, publication `e5c851ddf52d4fa984c4ddfe39484ee2`. All 233 Tu Casa Mi Casa pages have OCR assessments and forced-OCR text selection; none use embedded text. Their physical-page identifiers match the prior trial. The other four books' section records are unchanged. Tu Casa Mi Casa has 210 pending pages; The Professional Chef has 45, World Atlas of Wine has 14, and the EPUBs have none: **269 pages await review**. Full-page OCR produced 218 nonempty and 15 empty page results for Tu Casa Mi Casa. The known physical page 20 is now flagged for uncertain quantities; its text still requires correction. The coverage gap is closed, not the content review.

Verified all 361 manifest files (796,414,148 bytes), SQLite integrity, 1,951 indexed sections, all 334 OCR assessments across the trial, exact forced-source coverage, original source hashes, stable page IDs and unchanged section records for the other four books. The publication quality gate refuses the pending build. The private visual overview and per-page reports are regenerated in the new build directory. No OCR decisions, publication or upload occurred. All 60 tests pass (including new tests with intentionally wrong invisible PDF text, empty-page fallback rejection, unchanged source/page IDs, OCR failure, full-page coverage enforcement, and policy preservation through finalization). Ruff F and formatting checks pass. This approval covers local OCR and rebuilding, not publishing or accepting flagged text.
# OCR execution safety update

OCR/model runs and OCR tests now require the [resource-isolated launcher](ocr-resource-isolation.md). Historical native commands below describe earlier runs; they do not authorize native OCR execution. Existing review decisions and publication policy are unchanged.
