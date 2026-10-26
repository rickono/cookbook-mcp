# Repair evidence for complete publication of the six held books

Research checkpoint: 2026-10-26, 12:35 UTC. This answers the factual question in
[Establish source-supported repair limits for all six held books](https://github.com/rickono/cookbook-mcp/issues/57),
under [Complete publication of the six held books](https://github.com/rickono/cookbook-mcp/issues/55).
It is a planning asset, not a repair, acceptance decision, or publication input.

## Finding

Saved evidence supports specific corrections and occurrence-review boundaries,
but does not establish a complete, source-supported candidate for any of the six
books. Volume 5 has no known refusal gap and is the strongest candidate for a
complete route from the present material. The other five collectively have 501
terminally unavailable pages. A retained-page repair does not resolve that
coverage barrier or prove that all recipes and their supporting work survive.
Partial publication cannot satisfy this map's agreed destination. [E1, E2, E3]

Two deterministic defects remain present in both the frozen and reviewed text
patch paths: incomplete mixed-fraction replacement, and first-match association
of quantities with repeated wording. These mechanisms are proved by synthetic
controls, rather than inferred only from book symptoms. Their repair would not
settle semantic ownership, detect every wrong majority, or validate a whole
book. [C1, C2, E6]

The present research does not establish a permissible route to complete all
six. Nor does page loss alone determine which authored recipes and supporting
work are missing: that requires an admissible boundary and dependency inventory.
True refused content remains ineligible for recovery by any route. The map must
keep this feasibility question open instead of accepting an incomplete scope.
[E1, E2; map standing constraints]

## Evidence scope and freshness

The source baseline is repository commit
`68961b3f9c160c64a38da12ce40d4e72214f91b6`. The research worktree is isolated on
`research/held-six-repair-evidence`. No source-image review, PDF/DjVu parsing,
rendering, OCR, model call, candidate generation, admission, or expensive test
suite was performed. Only saved receipts, code, candidate identity bytes,
nonrefused preview/record bindings, retained uncertainty metadata, and small
synthetic text controls were examined. Raw evidence remains private.

The October 22 investigation is a useful index, but its assembly checkpoint is
historical. Current primary receipts report eleven completed original
candidates; Professional Chef is still absent from the completed list and its
candidate manifest does not exist. Thai Food is frozen and now has a recorded
semantic-import pass in its deferred-review receipt. This advances the original
report, which had not run that import. [E1, E2, E7]

There is also a freshness disagreement: `latest-supervision.json`, checked at
12:27:47 UTC on October 26, says book 34 is assembling, whereas the directly read
`assembly-state.json` says `needs_attention`, with pending books 34/86/9/61 and an
older embedded update time. This research did not inspect or control processes
and makes no claim that assembly is currently progressing. Neither receipt
provides a frozen Professional Chef candidate. [E1]

Read-only identity checks in this session verified that the five available held
candidate manifests still match the October 22 audit and current assembly
identities; all five payloads of each match their manifest hashes and lengths.
The 374 saved nonrefused preview/input-record bindings still match the private
binding receipt: Vetri 77, Volume 3 64, Volume 5 79, and Café Boulud 154. The ten
Volume 5 source-review record/preview bindings and all twelve corrected nonblank
occurrence addresses also match the authoritative receipt. These are integrity
checks, not new source readings or accuracy checks. Exact book-derived hashes
are deliberately kept in the private receipts. [E2, E3, E4]

The source worktree's `pipeline.py`, `review.py`, `readers.py`, and `production.py`
are byte-identical to those at this research baseline. The live `latest` preview
pointer now concerns a different book; the held-book evidence remains in the
timestamped preview directory recorded by the October 22 binding receipt.
Reusing a mutable `latest` pointer without checking its book would be incorrect.
[E1, E3]

## Per-book supported boundary and missing evidence

### Il Viaggio di Vetri

- Current saved availability is 287 of 312 pages, with 25 terminal exclusions.
  The legacy original still reports zero failed pages and contains quarantined
  derivatives; its import pass and full-page accounting do not make it eligible
  unchanged. The original records contain 100 unresolved items. [E1, E2]
- The primary source-review receipt confirms fraction corruption on physical
  pages 215 and 297, and incorrect association among separate recipe yields on
  215. A repair claim is limited to individually source-bound occurrences; the
  saved page read, quantity majority, or syntactically repaired fraction is not
  globally authoritative. Existing nonrefused replay receipts reproduce the
  frozen text exactly; reviewed replay still changes those pages without
  establishing the correct result. [E5, E6]
- The receipt also proves duplicate additions on 222 and a contents entry
  incorrectly classified as a recipe on 114. Text replay can address some
  additions, but cannot settle the contents classification or recipe ownership.
  Its sampled continuation on 223 is local evidence only. [E5]
- The saved preview changes 77 retained pages; 75 remap structurally and 215/297
  require explicit new occurrence decisions. The legacy structure has 18
  sections touching excluded pages and 28 touching retained immediate neighbors
  (29 distinct retained boundary pages). The 251 sections avoiding an excluded
  page in their listed provenance are a screening set. They are not established
  complete recipes. [E2, E3]
- Missing: a source-bound disposition for each affected quantity/occurrence,
  classification and ownership decisions, review of the entire changed scope,
  and an admissible inventory of missing recipe continuations and supporting
  work. None is replaced by fixing the two pure-code defects. The 25 excluded
  pages still prevent a demonstrated complete route. [E2, E3, E5]

### Modernist Cuisine Volume 3

- Availability is 394 of 399 pages. Physical pages 110, 148, 180, 200, and 234
  are terminally excluded. The legacy zero-failure original and its successful
  import are not a refusal-safe later candidate. It contains 297 unresolved
  items, which are not an error-rate estimate. [E1, E2]
- The primary finding `b32-p328-unflagged-oil-quantity` proves one incorrect
  retained amount supported by a wrong two-of-three crop majority. That recipe
  had no structured unresolved item for the error. The saved nonrefused replay
  is exact, and reviewed replay preserves the wrong result byte-for-byte. The
  existing ballots therefore cannot independently validate that amount. An
  explicit correction can be supported only by its existing guarded source
  evidence. [E5, E6]
- The named blur finding is on physical page 180, a refused page. Its historical
  title/yield observations are ineligible for recovery or retention. It cannot
  serve as an admissible retained-page repair target. Importantly, the saved
  receipts do **not** establish a page-indexed inventory of blurred nonrefused
  amounts: the 274 unresolved records left after excluding refused pages have
  majority or matching reasons, not explicit legibility reasons. Disagreement
  does not itself prove blur. The older report's proposed retained-source
  legibility work is an evidence gap, not a completed finding. [E2, E5, E8]
- The preview changes 64 retained pages, with 52 safe remaps and twelve requiring
  ownership decisions: 101, 112, 130, 203, 204, 306, 338, 354, 361, 371, 385, 397.
  Eight legacy sections touch exclusions; ten touch retained immediate neighbors.
  These counts do not bound the risk of unflagged incorrect amounts. [E2, E3]
- Missing: evidence for nonrefused legibility limits, explicit ownership for the
  rejected remaps, source validation capable of finding wrong majorities beyond
  the known sample, and recipe/supporting-work completeness across the five
  gaps. A clearer source could only address separately authorized nonrefused
  uncertainty; it cannot authorize recovery of true refusals or silent edition
  substitution. [E2, E5, E8; map standing constraints]

### Modernist Cuisine Volume 5

- All 420 saved pages are available; no terminal refusal is recorded. The
  original has 470 sections and 113 unresolved items. This removes the known
  refusal barrier, but does not establish source accuracy or ownership. [E1, E2]
- `book33-source-review.json` is the corrected **nonblank** occurrence authority.
  Its archived blank-inclusive predecessor is superseded. Ten pages were
  source-reviewed for failed remapping: 86, 87, 199, 218, 219, 246, 247, 284, 290,
  291. Together with the earlier page-63 sample, these establish duplicate
  ingredient/title/procedure work and misplaced rows, rather than a general
  deletion rule. [E4]
- The twelve newly unlabeled nonblank addresses in that receipt are: 86:46,
  87:50, 199:28, 218:35/38, 219:30/31, 246:47, 247:35, 284:49, 290:32, 291:43.
  They identify occurrences in the bound preview, not permission to discard
  them. The source-required appended ingredients on 199 and 284 must survive;
  equal amounts or `vote` origins do not make them duplicates. [E4]
- Page 246 needs ownership for four visibly titled components instead of
  inheriting continuation labels. Ingredient and procedure cells on the same
  line may require different dispositions. On 291, removing a repeated
  ingredient-bearing row must preserve any unique source-supported procedure
  step; the malformed fraction still lacks an established exact correction.
  Page 290's dimensional inconsistency is printed in the source and must remain
  a faithful transcription, rather than being silently normalized. [E4]
- The full preview changes 79 pages, of which 69 remap structurally and ten do
  not. Missing: per-occurrence source-supported keep/remove/move/unresolved
  decisions with recipe/part ownership; validation of all changed pages and
  adjoining continuations; preservation or individual disposition of the 113
  unresolved items; and evidence that recipes and their supporting work are
  complete beyond the targeted samples. Volume 4's book-specific removal rules
  do not answer these questions and must not be generalized. [E2, E3, E4]

### Thai Food

- The frozen original now has a recorded import pass. It has 501 retained and
  195 refused pages out of 696, 585 sections, 563 quantity reviews, and 205
  unresolved items. No later reviewed candidate is admitted. Unlike the legacy
  Vetri/Volume 3 originals, the recorded failed pages contribute no page text,
  section-part text, or quantity reviews. [E1, E2, E7]
- The 195 gaps form 85 runs, with 86 retained runs and 143 retained immediate
  boundary pages. Twenty-one sections list a failed page and 260 touch retained
  immediate neighbors. The other 564 sections' listed pages avoid failure;
  this structural fact is insufficient to call any of them complete recipes.
  [E2]
- Missing: authored recipe/part boundaries at every gap, continuation ownership,
  formulation/variation scope, and the availability of referenced preparations
  and techniques. A dependency may be unavailable away from the immediate page
  neighbor. Existing page exclusions and structural import leave these questions
  unanswered. No complete route is shown by the present saved evidence. [E1,
  E2, C3; domain glossary]

### The Professional Chef

- The current receipts retain 735 of 956 pages and exclude 221. The gaps form
  125 runs, with 126 retained runs and 204 retained immediate boundary pages.
  Historical nonrefusal sidecar page 421 does not add another refused page.
  [E1, E2]
- There is still no frozen candidate, no completed assembly entry, and no
  candidate-level recipe, section, or completeness analysis. The older report's
  statement that this awaits assembly remains true; descriptions of an actively
  progressing serialized queue need fresh operational evidence. This research
  neither resumed nor competed with that queue. [E1]
- Missing: a concrete immutable candidate on which to establish structural
  boundaries, followed by admissible recipe/part and supporting-work analysis
  across the gaps. Retained title/page counts cannot substitute for that
  evidence. The presently available material does not demonstrate a complete
  publication route. [E1, E2]

### Café Boulud

- The frozen candidate has a recorded import pass, with 385 retained and 55
  failed pages out of 440, 265 sections, and 70 unresolved items. The 55 pages
  contribute no page text, section-part text, or quantity reviews. A historical
  nonrefusal sidecar on 382 is not an additional failure or general recovery
  permission. [E1, E2, E7]
- Its saved preview changes 154 retained pages and remaps all 154 structurally;
  it is still unadmitted. The 55 gaps form 38 runs, with 66 retained boundary
  pages. Six sections list failed pages and 77 touch retained immediate
  neighbors; the remaining 259 provenance-screened sections are not a proved
  usable-recipe count. [E1, E2, E3]
- Missing: source-backed review of every changed-page disposition and inherited
  classification, recipe/part boundaries across the gaps, unavailable
  continuations, and referenced supporting work. Safe labels preserve cached
  ownership; they do not establish that the cached classification was correct.
  No complete six-book route follows from this technically remappable preview.
  [E1, E3, C2]

## What the deterministic probes establish

At the immutable source baseline, `qty()` and `QTY_RE` recognize the leading
ordinary digit in a superscript/subscript mixed fraction but omit its remaining
glyphs from the replaceable span. `put_qty()` substitutes only that leading
span, leaving the old suffix behind. The synthetic case `1¹/₂ x` patched toward
`1½ x` becomes `1½¹/₂ x` in both public patch paths. This demonstrates the span
defect without book text, inference, or image operations. [C1, E6]

`vote()` discards a title without numeric content, grouping numeric lines by
wording key. `_patch()` then consumes the first unused similar page line; it has
no recipe-bound occurrence identity. For synthetic page lines `2 x` / `3 x`, a
crop voting for `3 x` changes the first line, yielding two `3 x` lines. The
single-occurrence control changes its amount as expected; reversing the page
line order avoids the wrong transfer. The reviewed path's no-quantity heading
guard and duplicate-append suppression do not solve that ambiguous existing
occurrence match. [C1, E6]

On October 26, AST-extracted pure functions from the baseline reproduced both
failures on both paths, while both discriminating controls passed. The full
pipeline module was not imported. The private synthetic receipt records the
method and results. These observations validate the mechanisms, not a proposed
fix. They do not prove that all book symptoms share the same cause, that a model
majority is correct, or that every source occurrence exists in the page read.
[C1, E6]

`patch_origins()` provides stable origins for nonblank output lines, while
`remap_labels()` refuses new origins and moves across cached blocks. A passed
remap demonstrates compatibility with cached labels. Its own contract requires
review of inherited part classification before acceptance. New or distinct
source-required appended occurrences cannot be discarded merely to make that
check pass. [C1, C2]

## Limits that later decisions must address

1. **Complete scope:** determine, from admissible evidence, all authored recipes,
   recipe parts, formulations/variations, recipe uses and supporting work that
   this destination requires. Existing section-page adjacency is a lower-level
   screening aid, not a completeness proof. Refusal classification research is a
   separate ticket; it cannot be replaced by this repair inventory. [E2, C3]
2. **Correction and ownership evidence:** establish the evidence required to
   associate each corrected amount and surviving procedure with the right
   occurrence and recipe, including rows split across table cells and pages.
   Cached labels and equal wording do not supply that evidence. [E4, E5, C1, C2]
3. **Missed errors:** choose a credible source-validation scope for unflagged
   wrong-majority values, omitted steps/ingredients, and misclassified sections.
   The current samples demonstrate failures but estimate neither their rate nor
   a complete upper bound. The existing unresolved-item count is not a quality
   score. [E5, E6, C3]
4. **Source limits:** obtain an admissible page/field inventory before attributing
   nonrefused uncertainty to blur. Unreadable quantities remain unresolved;
   culinary inference, source substitution and refused-page recovery do not
   close this evidence gap. [E5, E8; map standing constraints]
5. **Later validation:** a proposed derivative will need immutable evidence,
   occurrence and ownership dispositions, preserved correction/unresolved
   history, and exact refusal exclusion before structural import can validate
   its contract. Strict import verifies shape, identity, references and
   accounting; it does not inspect original pages or prove recipe accuracy.
   The owner still decides acceptance and the later publication route. [C2, C4]

No policy preference, human escalation threshold, repair implementation, source
recovery or activation decision is resolved here. The six holds, originals,
admitted digests, supervisor state, locks, workers, scheduler, credentials and
resource ceilings were not changed by this research.

## Primary sources and private evidence pointers

Code links are pinned to the investigated repository commit. Private paths are
context pointers for an authorized local researcher; their contents are not
copied into this branch.

- **C1:** [Pure voting, patching and origin functions](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/pipeline.py#L74-L285).
- **C2:** [Occurrence-label remapping contract and checks](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/review.py#L12-L65).
- **C3:** [Nonblank lines and label coverage](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/assemble.py#L88-L109),
  [section creation/continuation heuristics](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/assemble.py#L196-L268),
  and [quantity-review uncertainty generation](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/assemble.py#L405-L505).
- **C4:** [Candidate validation scope](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/src/cookbook/scanned.py#L283-L345)
  and [page/status/reference/accounting checks](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/src/cookbook/scanned.py#L470-L551).
- **E1:** `/Users/rick/cookbook-mcp-data/production/transcription/ops53-20261021/`:
  `assembly-state.json`, `latest-supervision.json`,
  `prepublication-review-state.json`, `owner-publication-selection.json`,
  `latest-review-remap-preview.json`, and `admitted-reviewed-candidates.json`.
  Use the held-book entries and timestamps; mutable receipts may advance.
- **E2:** `/Users/rick/cookbook-mcp-data/production/transcription/held-six-investigation-20261022/audit.json`:
  per-book registered identities, refusal sets, retained runs, boundary counts,
  legacy contamination counts and candidate payload integrity. Historical
  identity/structural evidence reconciled with E1 in this session; no refused
  content was reused for repair.
- **E3:** Same investigation directory: `preview-bindings.json` and
  `evidence-manifest.json`. The held previews are in
  `ops53-20261021/review-remap-previews/20261022T105405Z-2bbcf5/output/`.
- **E4:** `ops53-20261021/book33-source-review.json`: corrected nonblank
  `page_reviews`, source/record/preview bindings, required appended ingredients,
  printed inconsistency, and the explicit prohibition on generalizing Volume
  4's removal rules. The blank-inclusive predecessor is superseded.
- **E5:** `ops53-20261021/visible-review-state.json`: book 11 findings
  `b11-p222-duplicate-ingredient-and-headnote`,
  `b11-p114-contents-classified-recipe`,
  `b11-p215-p297-malformed-fractions`; book 32 finding
  `b32-p328-unflagged-oil-quantity`. Its historical page-180 quality finding is
  cited only to delimit ineligible evidence, never to recover its content.
  Also `ops53-20261021/malformed-fraction-audit.json`.
- **E6:** Investigation directory: `nonrefused-replay-check.json`,
  `synthetic-repro.py`, `synthetic-repro-result.json`,
  `minimal-repro-result.json`, and `synthetic-probes.json`. October 26 pure
  synthetic confirmation:
  `/Users/rick/cookbook-mcp-data/poc/held-six-wayfinder-20261026/repair-evidence-synthetic.json`.
- **E7:** `ops53-20261021/candidate-reviews/` per-book receipts for the five
  frozen held candidates; Thai Food's later validation context is
  `ops53-20261021/candidate-checks/20261022T115354Z-bd2fb3/output/`.
  The current deferred-review entries in E1 point to the exact identities.
- **E8:** `/Users/rick/cookbook-mcp-data/production/transcription/pipeline-claude-haiku-5-5-x3-fb-gpt-6-luna--low-a4/books/32/candidate/unresolved.jsonl`:
  retained-page reason metadata only, excluding the five refused pages before
  inspection. Its disagreement/matching reasons do not establish source blur.
