# Existing PDF trials against the agreed review policy

Assessment date: 2026-10-27 (owner's local date). Repository baseline:
`34d88711fb529b181bb33e6d71f3a50ab40dff81`.
Research for [Assess existing trial gaps against the agreed review policy](https://github.com/rickono/cookbook-mcp/issues/64).

## Finding and scope

October materially extends September: geometry-aware recognition, layout and
source-assisted review improve selected results; whole-book image-first proposals
report visual inspection of 872 pages; a clean synthetic-raster control has a
native EPUB text reference; and later scripted-reader benchmarks add source-first
sample references, full-page submission accounting and machine-cost telemetry.
Crucially, later source checks expose missed quantity
errors, an uncorroborated reviewer replacement, and changed readings that began
without uncertainty flags. None establishes an independently validated, all-page
review process on real scans, a false-clearance rate, or reduced total human
effort. The reports support further evaluation, not enabling agent approval.
[P2–P25]

This audit reads existing reports and source code only. It does not independently
inspect book pixels, adjudicate transcriptions, rerun scoring, perform OCR or
inference, transfer book data, or approve content. Private sources below are
report/section locators, not upload instructions. Only aggregate findings and
method limitations are reproduced; no book passages, page images, raw outputs,
credentials, or incident evidence are included. The owner's current glossary was
read in the parent checkout without modifying it or copying its diff. [G]

## Contract being evaluated

The agreed policy requires source inspection of **every physical page**, including
native text and initially unflagged OCR; full-page omission checks; complete
candidate comparison within a declared scope; sufficient neighboring context for
associations and continuations; and explicit uncertainty rather than inferred
amounts or instructions. Proposing a correction, applying a draft correction,
clearing a flag, and granting agent approval are separate actions. Agent approval
is conditional on independent validation; publication is another action. Changed
outputs do not inherit existing human approvals. [R1]

The route decision adds retention of native and OCR alternatives, complete PDF
composition, original geometry and transforms, nested picture text, enumeration
markers, and source/page/image/text/configuration identities. Neither confidence
nor agreement proves correctness. Layout cannot establish an unreadable value.
These are planned requirements, not assertions about the implementation. [R2]

The agreed accounting is an initial extraction route and review, followed by at
most **two additional recovery attempts per problematic region** and **six per
physical page**, shared across tools and agents. Each additional alternative run
consumes the affected region/page budget; a predefined preprocessing/recognition
run counts once, while multiple configurations count separately. Unchanged
requests, failures and timeouts consume attempts. Plainly impossible recovery
stops early. Exhausted content recovery becomes a human edge case; technical
failure leaves review pending as a review failure. [R1, R2]

## Evidence inventory: keep the denominators separate

| Existing evidence | Measured result | What the result does not establish |
| --- | --- | --- |
| September corpus survey and diagnostic comparison | 19 PDFs, 18 cookbooks; 57 rendered samples and 22 visually inspected pages. Eleven cookbook pages supplied 31 frozen short probes. Best contrast-region candidate passed 19/31 versus 17/31 default whole-page OCR and 15/31 native layout extraction. All five explicit fraction probes failed every OCR arm. | Whole-file text presence is not source review. Purposive snippets and manual regions do not measure full-page omissions, automatic discovery, or corpus accuracy. [P1, “What completed,” “Matched comparison”] |
| September vision sample | 35 selected pages: 31 flagged, four unflagged. Recommendations total 24 correction, seven substantively acceptable, two no-text, two uncertain. | These are recommendations, not approvals or independent judgments. The sample favored suspicious pages and cannot estimate clearance or escalation rates. [P2, “Sample counts,” “Scope and next step”] |
| October frozen recall and recognition comparison | Twelve pages, six primary recipe targets, 36 positive queries and seven audited valid negatives. With manually checked recipe assembly, current extraction found 32/36, direct Tesseract 33/36, and RapidOCR 36/36; RapidOCR found all six cross-page targets. | Oracle recipe boundaries remove an important failure mode. Retrieval parity with an agent-written reference control is neither complete reading nor EPUB parity. [P3, “Sample and frozen controls”; P4, “Retrieval”] |
| October reading diagnostic | Geometry-ordered RapidOCR retained 61/67 ingredient phrases, 11/14 fraction-bearing ingredient lines, 14/38 instruction phrases and 9/24 table values; all 14 fraction-bearing table cells failed. | Phrase failures mix formatting and substantive mistakes. Presence and ordering diagnostics do not certify complete instructions or automatic recipe membership. [P4, “Reading, quantities, and ordering,” “Scorer audit”] |
| October layout with fixed recognition | On four previously tested pages, recursive structured output retained 186/186 recognized fragments; default Markdown retained 151/186. Table geometry assigned 24/24 quantities to the right ingredient row and formulation column, but 12/24 were incorrectly labeled as headers. | This isolates layout using a custom frozen-recognition adapter. It does not discover text omitted by recognition, repair quantities, validate global reading order, or test default end-to-end conversion. [P5, “Scope and controls,” “Table associations, independent of quantity strings,” “Reading and source order”] |
| October fresh-page automatic assembly | Primary 12-page cohort: 25/25 targets present, only 12/25 confined to intended content, 6/8 wrong negative associations, 3/6 complete recipes with clean membership. Separate eight-page supplement: 25/26 present, 6/26 confined, 2/8 wrong negative associations, 1/5 complete recipes with clean membership. | Frozen fresh-page enrollment is useful prospective evidence, but both cohorts use previously sampled editions. The builder annotated source regions; independent human adjudication is absent. Do not pool cohorts or count all targets as recipes. [P6, “Separately reported cohorts,” “Frozen prototype and annotation protocol”] |
| October source-supported agent review | Three selected recipe scopes over five page images, frozen before reference access. Ingredient phrases 19/22 → 21/22; instruction phrases 8/19 → 13/19; anchors 17/19 → 19/19; table matches 9/24 → 22/24 with two explicitly unresolved. | Independent post-freeze scoring is stronger than self-report, but the reference is an agent transcription with a disputed fraction. This is not independently adjudicated truth, complete-instruction certification, or approval. [P7; P8] |
| Later source-repair development comparison | One two-page recognized recipe: complete ownership 0/1 → 1/1, complete-target retrieval 0/8 → 8/8, exact quantities 9/23 → 23/23; all 24 targets retained, one unreadable and unscored. | Clean-context source reader and candidate-assisted reviewer were separate, but shared model/provider. Success depends on an amended correspondence witness after three strict full-cohort refusals; it is not fresh validation. [P11, “Reference correspondence and limits”] |
| Wider development cohort and repair | Eighteen previously surveyed editions, one saved page each. Final repair gives 3/11 complete recognized recipe groups and 5/22 recipe-query targets; all three groups are on one page. Quantity wording remains 8/23. | Wider edition coverage usefully exposes restrictive assembly, but source references are agent-authored with development exposure. Recognized ownership and short wording probes do not establish authored completeness. [P12; P13] |
| October 12–13 whole-book image-first proposals | Three ledgers report all 872 physical pages inspected and 283 recipe records; 20 explicit unknown records remain across two proposals. Nine purposively selected recipes subsequently checked over 18 images. | Visual authoring and integrity bookkeeping achieve coverage evidence beyond the earlier samples, but include inherited work and self-reinspection. Later candidate-assisted checks are local, same-provider/context-separated audits, not whole-book correctness validation. [P15–P18] |
| October 14 adaptive source-detail probe | Three tables, 112 amount cells recorded before detail. Eight filled readings change, four without prior uncertainty flags; four initial nulls receive proposals, two filled fields become unresolved, four final nulls remain. | Same parent reads both passes; no independent reference. Changes demonstrate instability and useful abstention, not certified corrections or the isolated effect of resolution. [P19, “Small source-first reading trial”] |
| October 14 native EPUB/synthetic-image control | Four complete recipe texts exact under NFC/whitespace normalization; 53/53 ordered ingredient lines, 94 numeric occurrences and four complete method streams match. Both indexes find 16/16 positive literal targets in the top ten. | Native extraction supplies a candidate-independent reference, but images are simple synthetic reflow with supplied recipe identities/boundaries. The other 290 index sections remain native. This is not genuine-scan parity or automatic discovery. [P20, “Controlled pair and frozen inputs,” “Reading comparison,” “Retrieval comparison”] |
| October 15–20 scripted-reader benchmark | Frozen 39-page mixed random/purposive packet; pilot 528/578 items and 292/293 quantity lines after three-sample voting. Full primary-reader run transcribes 859/872 pages; sampled assembler-v3 fidelity is 220/221, 224/242 and 143/146 adjudicable items by book. A separate fallback configuration later records 872/872 page texts. | Source-first model references and fallible model grading are stronger than same-context probes, but remain sampled; ambiguous/unknown items are separated. References were reused for development and assembler rules changed after feedback. The fallback configuration's comparison has null grades. No all-page correctness or validated approval follows. [P22–P25; C7] |

The September recommendation totals above are sums of P2's per-book counts,
not new classifications. October's 67-line recognition cohort, 27-line layout
subset, and 22-line review subset are different scoring scopes. The 24-cell table
is reused across experiments; repeated tests do not add independent tables.
No combined accuracy percentage is warranted. [P2, P4, P5, P8, P9]

## Later scripted benchmarks: additional evidence and its limits

The repository's reader-benchmark documentation points beyond the initially named
`poc/` reports to October 15–20 batch evidence. It must not be omitted: this later
work supplies source-first references, scripted full-book page reads, repeated
crop readings, independent-context grading and recorded cost/runtime. It does not
erase the earlier failures or establish the agreed approval process. [C7; P22–P25]

The reference protocol combines eight preregistered random pages per book with
purposive additions. The actual source-reviewer records describe 13, 14 and 12
reference pages, independently read from images/detail rather than candidate
outputs. Long methods are sometimes sampled excerpts; some index entries and
continuations are unassessed or ambiguous. The source reviewer is Opus; the
scripted reader is Haiku and the cited evaluator is Sol. Context separation and
cross-provider grading improve independence over earlier self-checks, while the
reference remains model-written, with same-family bias for some candidate cells
and no human adjudication. [P22, reference-reviewer metadata; P24]

Assembler-v3 fidelity counts above exclude two ambiguous items in the first book,
eight ambiguous/inferred items in the second, and 15 ambiguous items in the third;
one and two additional unknowns respectively are outside the latter two scored
denominators. These are item-level packet results, not complete recipes or
whole-book accuracy. Grading separately reports ownership/continuation defects,
duplicate or contaminated content, and unknown source relationships. Numerical
wording can pass an atomic item while a recipe has the wrong owner/title. No
representative audit specifically stratifies agent-cleared versus unflagged
content under R1's approval contract. [P24, per-book fidelity/structural reports]

The primary full run's 13 provider-filter failures are preserved as missing page
transcriptions. Ledgered image submission is not successful reading. Later,
another-provider fallback supplies those pages once in a distinct configuration;
its comparison records complete page-text coverage but null grades. This audit
does not authorize repeating or extending that fallback, select a provider, or
equate filled page records with reviewed content. Terminal unavailability,
technical failure, content uncertainty and publication eligibility still need
distinct handling under the current plan. [P23, “Full-book runs”; P25; R1; G]

Importantly, evaluated review metadata itself was unreliable: the third book's
v3 report identifies 14 internal discrepancies between text and crop-review
records. The experiment notes explain ties, rejected corrections, formatting drift
and matching the wrong repeated quantity occurrence. The v4 amendment changes
review/unresolved metadata while retaining byte-identical section text, and records
remaining ties or unmatched readings explicitly. That repairs a consistency claim;
it is not a fresh source-correctness evaluation or proof that majority readings
are correct. Assembler revisions followed evaluator feedback, making regrades
development evidence rather than a fresh held-out first pass. [P23, “Assembler
v2/v3 regrades,” “Assembler v4”; P24; C7]

This later work **does** measure machine economics: notes report roughly $2.98
at recorded list prices versus about $5.27 CLI-reported for the primary page and
sectioning stages, with a 16-second median page pipeline time in the frozen
baseline. These exclude total reference, grading, setup and human audit effort;
list prices are not subscription-meter charges. Stage/call medians are not full
workflow elapsed time. Thus older reports' lack of machine-cost measurement is
partly remedied, while total human effort and validated quality-adjusted throughput
remain unknown. [P23, “Full-book Haiku run”; C7 and baseline manifest]

## Coverage, omissions, order and ownership

**All-page visual authoring exists; independently validated all-page review does
not.** The earlier forced-OCR build assessed every page of one source, but an OCR
assessment is not visual review; the 35-page vision sample was non-exhaustive.
Later image-first proposals explicitly report all 233, 247 and 392 pages inspected,
including photographs and front/back matter, with page ledgers and frozen outputs.
This materially closes the earlier authoring-coverage gap. Two continuations
inherit prior work rather than independently reviewing every inherited word.
Integrity checks establish accounted pages and linked records, not absence of
missed wording. No separate independent all-page source/candidate review under
R1's contract is demonstrated. Later scripted benchmarks distinguish full page
submission, successful transcription and sampled reference grading, but likewise
do not independently review complete candidate text on every page. [P1, P2, P15,
P18, P22–P25; C4]

**Omission recovery is demonstrated locally, not measured comprehensively.**
September found missing ingredient columns and captions, including content native
extraction omitted. October RapidOCR recovered caption terms missed by the earlier
baseline. Docling's recursive output retained recognized picture-child text that
its default Markdown omitted, including four of five caption preparations on the
tested continuation page. Retaining every recognized line does not prove that all
source text was recognized: the assembly diagnostic's 26/26 and 23/23 source
regions with at least one line are region-hit checks, not complete-region recall.
There is no independently adjudicated all-region omission denominator. The later
whole-book proposal reports also preserve omission-repair history: one required a
separate pass for 48 omitted recipe badges; another revisited 37 transcription-gap
pages and found additional incidental text omissions. Their final completeness
statements are authoring reports, not an independent omission audit. [P1, P2,
P4–P6, P15]

**Order, joining, ownership and classification are different tests.** October
geometry ordering reduces column/caption interleaving but retains irregular-grid
mistakes. The layout experiment preserves within-region order on its eligible
uniquely identifiable fragments, excluding ambiguous/repeated substrings; it does
not establish a unique global prose order. A genuine instruction continuation in
the separate assembly supplement passes a complete frozen final-step comparison
under documented normalization, yet fails ownership because an independent
preparation is merged into the same group. Other instruction blocks were not
compared exactly. A passage with correct text ownership is also incorrectly typed
as a recipe. Neither all-word recall nor a successful continuation join proves a
complete, correctly bounded recipe. [P4, P5, P6]

Later image-first authoring retains real continuations, independently authored
supporting preparations, reference entries and multi-part formulations throughout
three whole-book proposals. The small page-structuring spike also separates
neighboring preparations, but its queries and short phrase checks were authored
post hoc by the same exposed context. Local follow-up audits check order and
ownership only within selected windows, leaving supporting target bodies and
whole-book mappings outside their scope. These are stronger authoring examples,
not independently established complete-book membership accuracy. [P14–P18]

Manual boundaries with unchanged OCR produce 25/25 confined positives and no wrong
associations in eight negatives for the primary assembly cohort; the supplement
produces 25/26 and no wrong associations in its eight negatives. That control
isolates assembly failure from recognition. It is not evidence that automatic
assembly achieved those results. Supporting work referenced outside the selected
review scopes was not expanded or validated. [P6, P7]

## Critical quantities, corrections and abstention

**Exact quantity occurrences and associations need separate references.**
September's short-span probes do not establish occurrence identity or association;
the same number elsewhere can be insufficient. October's table scoring uses
frozen source cell locations to check amount and unit in the correct formulation,
while the layout study separately tests predicted row/column geometry. Correct
24/24 geometry coexists with incorrect recognition and header semantics. Ordinary
ingredient phrases bind more context than bare numeric-token checks, but do not
provide independently adjudicated coverage of every yield, temperature, duration,
dimension, ingredient quantity, repeated quantity occurrence, or recipe use.
[P1, P3–P5; C5]

The separate fixed-cell diagnostic compares recognition-only PP-OCRv5/v6 at two
render densities on that same difficult table: respectively 5/24 and 4/24 exact
values for v5, 6/24 at both densities for v6, with 0/14 fraction-bearing cells in
every arm. This is a different context/crop experiment from whole-page recognition;
it cannot be used as an overall engine ranking or a held-out review result. [P10]

**Unsupported correction and missed-error rates are unknown.** September's four
source-grounded proposals were never accepted. October's review froze 23 artifacts
before reference access and all 22 non-null reviewed table values matched the
original frozen reference. That is evidence of selected recovery without guessing
those two unresolved fields. It does not independently verify all corrections,
show that no correct content was damaged, or establish correctness outside the
scored spans. The reference itself is agent-written and at least one fraction
reading is uncertain. A separate scorer and a frozen output reduce leakage; they
do not make the source reference independently authoritative. A later source-repair
trial supplies separate clean-context source readings, but retains shared-model
limitations and an unreadable target where the reviewer originally proposed a
value; the final reading explicitly restores uncertainty. [P1, P7–P9, P11]

The whole-book follow-up gives concrete evidence of **both missed errors and
overcorrection risk**. One candidate-assisted audit reports no discrepancies in six
selected recipes and 60 ingredient requirements; this is zero findings, not six
certified passes. Another checks 92 amount cells and proposes three probable
fraction discrepancies. Higher-detail parent inspection supports two, does not
corroborate the third proposed replacement, and identifies an additional candidate
error missed by that reviewer. The parent is also the same model/provider and no
human adjudication occurred, so these are documented source-reading disagreements
and proposed corrections, not independently certified error counts. The frozen
candidate and reviewer findings remain preserved. [P16–P18]

The 29 logged edits comprise 26 text/cell edits and three structural operations,
with overlapping reconstruction and cell work. They are not 29 independent errors
or an error-rate denominator. Residual phrase failures remain; some are line-wrap
or hyphen representation effects and others may be substantive. Resolving those
classes requires source adjudication beyond this audit. [P7, P8]

**Neither agent-cleared nor initially unflagged content has a measured residual
error rate.** No cited real-book experiment applied agent approvals. The older
sample's seven “substantively acceptable” recommendations were not independently
audited clearance decisions. Its four initially unflagged controls nevertheless
included a correction recommendation and an obscured-source uncertainty. The
embedded-text defect documented before forced OCR also bypassed the low-text
trigger. These establish failure modes of queue-only review, not their prevalence.
October adds candidate-assisted audits and a particularly relevant source-first
detail probe: four of eight changed non-null readings had no initial uncertainty
flag. These are later changed interpretations, not four certified errors, but show
why uncertainty-triggered requests alone would miss some unstable values. The
candidate's empty local unresolved list likewise did not prevent later probable
quantity findings. There is still no representative independent audit of clean
native text, unflagged OCR, or all content a reviewer would clear under the agreed
approval contract. Later random-plus-purposive fidelity grading adds sampled
missed-error evidence but does not supply that clearance denominator. [P2,
P17–P19, P22–P24; C1–C4]

**Abstention exists in examples, but is not calibrated.** The earlier vision
sample left obscured text uncertain. October retained two table quantities as
explicit unresolved markers/nulls rather than guessed values and preserved a
possible source-printed inconsistency instead of reconciling it. Photograph
ownership without source evidence was left unresolved in assembly annotation.
These align with the intended distinction between unresolved content and a
source-printed inconsistency. There is no independently adjudicated confusion
matrix for justified abstention, unnecessary escalation, missed uncertainty, or
false assurance; no complete-recipe eligibility judgment follows from the fields
that were recovered. Later whole-book proposals distinguish unreadable graphical,
occluded and fractional content from uninspected pages; adaptive detail can turn
filled fields back into nulls. An empty unknown list in another proposal is not
independent proof that uncertainty is absent. Terminal unavailability and release
visibility were not tested. [P2, P6–P8, P15, P17–P19; R1; G]

## Attempts, technical failures and effort

**Existing jobs do not demonstrate compliance with the agreed recovery budget.**
The experiments fix several candidate arms or revisit selected failures; they do
not implement a per-region/per-page adaptive ledger after a declared initial
route and review. September includes crop-boundary revisions; October includes
two-density/two-recognizer trials and a second source display during review.
Those records cannot simply be labeled “within two retries”: a source display is
not necessarily an alternative recovery run, and a batch job can affect several
regions/pages. The adaptive spike records three table-detail requests plus four
focused rows for its source-first cohort, and separately exposed regression and
verification requests. It does not predeclare policy regions or demonstrate
budget enforcement; root-level job totals cannot establish a page/region attempt
count. No audited mapping identifies which actions are initial, which
consume shared recovery attempts, when tools switch, or when the process stops
early. This is missing evidence, not a retrospective finding of policy violation.
[P1, P7, P9, P10, P19; R2]

The newer scripted reader records three region-box samples and three crop samples,
per-call retries, a full retry pass and optional provider fallback; its sectioner
also retries malformed labels. It lacks a demonstrated shared ledger translating
those actions into R2's initial-versus-recovery region/page accounting. A predefined
multi-sample route must not be equated automatically with either one allowed
attempt or multiple violations without that declared mapping. [P23; C8; R2]

**Technical failure is observable but review-state behavior is untested.**
The reports preserve a September missing-config failure, an October recall-scorer
self-check failure, a synthetic recognition API/configuration failure, and an
assembly wrapper failure on a no-detected-text result. The four-experiment root
report counts 22 jobs: 21 successful and one wrapper failure, with no reported
OOM/PID-limit events. Setup, scoring and recognition failures have different
scopes; these counts cannot be pooled into a review-service reliability estimate.
Correcting a wrapper does not show that a failed review remains pending or that a
retry consumes the correct shared budget. No systematic reviewer/service timeout,
exhausted-technical-failure, or mistaken approval-after-failure study is present.
[P1, “Safety, validation and reproducibility”; P3, “Execution and verification”;
P4, “Resource enforcement and verification”; P6, “Protocol amendments”;
P9, “Resource and protocol verification”]

Later development reports add a null-title diagnostic failure, a table-evidence
evaluation refusal, and formatting/harness failures. Some full-cohort reference
mapping refusals are deliberate evidence protection, not a judgment of source
unreadability. Such events need distinct categories in later accounting. [P11–P13,
P18, P21]

Later scripted runs add provider output-filter refusals, empty replies and capacity
failures. The benchmark's saved-file cost accounting can report zero failed calls
while separately listing missing refused pages; the refusal count must be read
alongside successful-file telemetry. Complete ledger rows do not eliminate these
failures. Fallback success is separately recorded, not evidence that the original
provider completed its review. [P23–P25; C7, baseline manifest]

**Total human effort is unmeasured.** The October review records 113.215 seconds
across three agent correction windows, including display/tool latency and artifact
writing. It excludes initial candidate reading, copying/setup, final report/freeze,
and evaluation; it measures no owner review time. Recognition and layout runtime
figures also exclude preparation, annotation, inspection and other work. There is
no matched human-only baseline, full backlog accounting, time for independent
audits, or measured burden of unnecessary escalation. Thus neither human minutes
saved nor whole-book review cost/throughput can be inferred. A separate
source-repair trial times a 61-second candidate-review window while leaving total
effort fields null; whole-book interactive image-first sessions and the adaptive/
synthetic controls also lack measured model/token economics and human effort.
The later scripted benchmark supplies machine-stage cost/time observations, as
described above, but still no total human-effort study or quality-adjusted
end-to-end comparison. [P3–P11, P14–P25]

Future evidence would need a complete effort ledger, including reference creation,
setup, source inspection, failed attempts, escalation/adjudication, independent
audits, and finalization, with agent/tool runtime and human minutes distinguishable.
That identifies what is missing; it selects no effort target. [Inference from
P7–P9 and the acceptance question R3]

## Actual tested methods versus the planned workflow

The production baseline extracts native PDF text with pypdf, applies a low-text
OCR trigger, and bypasses native extraction for forced-OCR sources. Its current
pending flag is conditional on OCR reasons and absent decisions. Digest-bound
human review and publication checks protect exact recorded outputs, but native
pages without OCR and unflagged OCR do not require an explicit source-review
decision. The decision function documents explicit human action and does not
record the planned agent/human distinction. These mechanics do not implement
R1's all-page visual review or R2's retention of native alternatives under forced
OCR. [C1–C3]

The September matched trial used Poppler layout text, direct whole-page Tesseract
without production orientation/deskew, and manually selected/ordered regions.
October adds actual current-policy controls, pinned RapidOCR candidates, a
post-baseline geometry-ordering diagnostic, a custom fixed-recognition Docling
adapter, frozen heuristic assembly, and a separate visual agent review. Those are
useful components with different evidence boundaries; they were not evaluated as
one all-page route→recovery→review→approval→eligibility process. [P1, P3–P9]

Source-assisted development repair, image-first whole-book authoring and
parent-operated source-detail requests add further components. These studies did
not evaluate one all-page route→recovery→review→approval→eligibility process on real
scans. The newer scripted reader uses full-page reading, repeated region/crop
sampling, voting and text-only assembly rather than a separately validated visual
comparison of every complete candidate with its source. Synthetic mechanism checks,
majority agreement and valid export links do not establish source correctness or
agent approval authority. [P11–P25; C7, C8]

No primary report establishes an independent held-out end-to-end test of the
agreed review process on genuine scans. There are
frozen controls, fresh pages, a separately enrolled continuation supplement, and
post-freeze scoring; each reduces a particular bias. The recognition/layout sets
reuse known pages, the ordering diagnostic follows observed failures, fresh
assembly uses familiar editions and builder annotations, and review uses three
purposive scopes against an agent transcription. Those distinctions must survive
any later comparison. Resource fit on small admitted jobs is likewise not a
worst-case whole-book guarantee. [P1, P3–P19]

The synthetic EPUB pair is an important exception to the agent-written-reference
limitation: frozen native extraction supplies text independently of the image
candidate. It verifies exact wording, numeric-occurrence sequence and methods on
four clean reflowed recipes, and re-extraction validates four reference locators.
One method paragraph is split without wording/order loss; the original positional
score and later alignment diagnosis are both retained. It neither tests production
citation UI nor provides a real scan/native-text pair. Simple layouts, supplied
boundaries, positive-only literal probes and 290 unchanged native distractor
sections limit transfer to the real-scan task. [P20]

## Questions for owner follow-up and later evidence design

These are questions, not acceptance thresholds, route promotions or approvals.

- In [Define usable-content acceptance and missed-error validation](https://github.com/rickono/cookbook-mcp/issues/5), what acceptance unit and partial-content visibility apply when a reviewed page contains an unresolved quantity, a recipe crosses pages, or supporting work remains outside the inspected scope?
- Who independently adjudicates complete source references and disputed glyphs, and how will development probes remain separate from held-out pages and new book editions?
- What sampling and evidence are required to bound missed omissions, introduced errors and false clearance, including initially clean native text, unflagged OCR and agent-cleared scopes? Which exact critical quantity occurrences and associations must be independently checked?
- How will a bounded pilot measure complete region coverage, correct order, continuation ownership, nonrecipe classification and original-page citation resolution together, rather than substituting query presence or line retention?
- How will the attempt ledger bind initial routes and additional runs to shared region/page budgets, distinguish review failures from human edge cases, and expose both early stops and exhaustion?
- Which independently adjudicated pilot will retest the frozen latest assembly/review metadata and any admissible refusal/fallback behavior, with a fresh sample after feedback-driven development? How will unavailable content remain distinguishable from filled but ungraded page text?
- What full human-effort accounting and comparison would demonstrate the intended workload reduction while including independent audit and adjudication costs?

The route-comparison work in [Assess whether PDF recovery alternatives are ready for initial routing](https://github.com/rickono/cookbook-mcp/issues/65)
can use this audit's separation of recognition, geometry, ownership and review
results. This report does not work or resolve that ticket. External-service
controls and spending authorization, quality/effort thresholds, rollout, and
publication eligibility remain their respective owner decisions. No new run or
policy change is authorized by this research. [R1–R3]

## Sources and audit limits

Private P1–P21 locators below are relative to `~/cookbook-mcp-data/poc/`; P22–P25
are relative to `~/cookbook-mcp-data/batches/`. These first-party
trial reports own the numerical observations. They remain private and may contain
source-derived evidence; none is copied into Git. The section locators above
identify the basis for each aggregate. This audit did not reopen raw candidate
artifacts or verify every retained hash/container record; operational statements
are attributed report evidence, not a new enforcement certification.

- **R1:** [Define the agent review authority and human escalation boundary — resolution](https://github.com/rickono/cookbook-mcp/issues/4#issuecomment-6458642261).
- **R2:** [Choose extraction and recovery routes for each PDF condition — resolution](https://github.com/rickono/cookbook-mcp/issues/6#issuecomment-6458755406), especially “Recovery budget and stopping.”
- **R3:** [Define usable-content acceptance and missed-error validation](https://github.com/rickono/cookbook-mcp/issues/5), open owner-decision question when read.
- **G:** Owner's local `/Users/rick/Documents/ChatGPT/cookbook-mcp/CONTEXT.md`, read-only terminology context; uncommitted additions are not reproduced here.
- **P1:** `pdf-corpus-20260913/report.md`, especially “What completed,” “Matched comparison,” “Measured improvements and regressions,” “Higher-resolution regional follow-up,” and “Safety, validation and reproducibility.”
- **P2:** `build-ocr-trial-20260912-fullscan/vision-review/sample-summary.md`, especially opening finding, “Sample counts,” “Scope and next step,” and the unflagged-control findings.
- **P3:** `pdf-recall-20261011/report.md`, especially “Sample and frozen controls,” “Negative controls and overbroad windows,” “Reading and quantities,” and “Execution and verification.” Its historical ingredient counts are superseded by P4's scorer audit; the regional arm was not rescored.
- **P4:** `pdf-layout-20261011/report.md`, especially “Retrieval,” “Reading, quantities, and ordering,” “Scorer audit,” and “Resource enforcement and verification.” Audited ingredient counts are used here.
- **P5:** `pdf-next-20261011/layout/report.md`, especially “Scope and controls,” “Table associations, independent of quantity strings,” “Reading and source order,” and “Resource fit and cleanup.” Only the marker-aware audited scoring is treated as final.
- **P6:** `pdf-next-20261011/assembly/report.md`, especially “Separately reported cohorts,” “Genuine continuation check,” “Frozen prototype and annotation protocol,” “Protocol amendments,” and “Resources and reproducibility.” Ownership-sensitive primary and separate supplemental results are used here.
- **P7:** `pdf-next-20261011/review/report.md`, full report; timing exclusions, edit-unit definition, unresolved fields, source scope and freeze limitations.
- **P8:** `pdf-next-20261011/review-evaluation.md`, full report; frozen before/after scoring, reference uncertainty and timing limits.
- **P9:** `pdf-next-20261011/report.md`, especially “Recipe ownership and continuation,” “What review established,” and “Resource and protocol verification.”
- **P10:** `pdf-next-20261011/fractions/report.md`, especially “What was controlled,” “Results,” and “Resource and source verification.”
- **P11:** `pdf-source-repair-20261011/report.md`, especially opening comparison, “Reference correspondence and limits,” review-window timing, and “Containment and preservation.” The amended correspondence is development evidence, not a strict-mapper success.
- **P12:** `pdf-wide-20261011/report.md`, especially “Enrollment and source freeze,” “Matched automatic progress,” “Reading probes,” and “Containment, failures and preservation.”
- **P13:** `pdf-wide-repair-20261011/report.md`, especially opening outcome table, “What improved and what remains,” and “Resource containment and preservation.”
- **P14:** `llm-page-structure-20261012/report.md`, especially “Actual experiment,” “Retrieval diagnostics,” “Reading diagnostics and source audit,” and “Resource boundary and artifacts.”
- **P15:** `llm-whole-books-20261012/books/6/output/report.md`, `books/79/output/report.md`, and `books/81/output/report.md` under that same root; whole-book page ledgers, inherited/reinspected scope, final unknowns, omission history and explicit source-accuracy limits. Read final reports rather than their preserved intermediate checkpoints.
- **P16:** `llm-whole-books-20261012/review-20261013/report.md`, full report; six-recipe audit, zero-findings interpretation, inspected and unassessed scope, candidate exposure and shared-provider limits.
- **P17:** `llm-whole-books-20261012/review-family-20261013/report.md`, full report; 92-cell scope, three provisional findings and unresolved limitations. The preserved `final-review-frozen/report.md` is separately cited by P18 as the frozen review record.
- **P18:** `llm-whole-books-20261012/diagnostics-20261013/report.md`, especially “Source checks and actual discrepancies,” “Literal retrieval diagnostic,” and “Execution and integrity.” This owns the parent follow-up's two supported reviewer findings, one uncorroborated replacement and one missed candidate discrepancy.
- **P19:** `adaptive-page-detail-20261014/report.md`, especially “Small source-first reading trial,” separately exposed regression case, “Local execution and overhead,” and “Result and next acceptance question.”
- **P20:** `epub-comparison-20261014/report.md`, especially “Controlled pair and frozen inputs,” “Reading comparison,” “Retrieval comparison,” and “What this establishes.” Native reference fidelity is distinct from real-scan or complete EPUB-extraction accuracy.
- **P21:** `pdf-prototype-20261011/report.md`, `pdf-prototype-20261011/boundaries/report.md`, `pdf-prototype-20261011/structure/report.md`, and `pdf-boundary-implementation-20261011/report.md`; preservation/export mechanisms, unresolved selections, synthetic verification and private harness failures. These do not supersede source-accuracy studies.
- **P22:** Batch root `model-comparison-three-books-20261015/`: `EVALUATION-PLAN.md`, `prompts/reference-freeze.md`, and actual `evaluation/references/{6,79,81}/reviewer.json`; protocol, selection/exposure, source-first reading, sampled methods, source uncertainty and model bias.
- **P23:** `paid-reader-pilot-20261019/NOTES.md`, especially “Pilot results,” “Full-book runs,” “Full-book Haiku run,” “Assembler v2/v3 regrades,” and “Assembler v4”; primary experimental record of coverage, cost, feedback, retries and metadata amendments. Initial candidate reports under `full-haiku/candidate/{6,79,81}/output/report.md` were also read and kept separate from later assembly versions.
- **P24:** Under `model-comparison-three-books-20261015/evaluation/candidates/pipeline-claude-haiku-5-5-x3-a3/books/{6,79,81}/metrics.json`; source of version-specific fidelity denominators, unknowns, coverage and observability limits. Also `books/81/structural-report.md` for the failed-page and 14 internal-review-discrepancy findings. No candidate excerpts or fidelity-item records are reproduced here.
- **P25:** `reader-bench/pipeline-claude-haiku-5-5-x3-fb-gpt-6-luna--low/compare.json`; separate fallback configuration, 872 page texts, 13 fallback pages, failed/retried call telemetry and null per-book grades. This audit reads summary fields, not source page records.
- **C1:** [PDF ingestion at the audited baseline](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/src/cookbook/extract.py#L475).
- **C2:** [Effective OCR state and explicit human decisions](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/src/cookbook/ocr.py#L268).
- **C3:** [Publication quality checks](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/src/cookbook/quality.py#L32).
- **C4:** [Historical review behavior and forced-source coverage](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/docs/ocr-review.md).
- **C5:** [Frozen-reference scorer and numeric boundaries](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/scripts/pdf_recall_trial.py).
- **C6:** [Trial method and limitations](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/docs/pdf-corpus-trials.md) and [mandatory resource isolation](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/docs/ocr-resource-isolation.md); read for the audit, with no execution authorized or performed.
- **C7:** [Reader benchmark, baseline and caveats](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/docs/reader-benchmark.md) and [frozen baseline manifest](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/scripts/reader_bench/baseline.json); historical observations and configuration provenance, not current service recommendations or new authorization.
- **C8:** [Scripted page/region/crop flow](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/scripts/reader_bench/pipeline.py#L339) and [section-label retries](https://github.com/rickono/cookbook-mcp/blob/34d88711fb529b181bb33e6d71f3a50ab40dff81/scripts/reader_bench/assemble.py#L110); source read only, never executed during this audit.
- **H1:** [September evidence assessment](https://github.com/rickono/cookbook-mcp/blob/92d41885527b16bf05a22bb261c79a7895d163e9/docs/research/pdf-review-evidence.md).
- **H2:** [September agent-review feasibility assessment](https://github.com/rickono/cookbook-mcp/blob/8b0dbd97841b0a40e3129e9e3b8baea596790ece/docs/research/pdf-agent-review-options.md).

H1/H2 provide the existing research convention and September context. October
observations in this report come from the newer primary reports P3–P25, rather
than being inferred from the old summaries. No thresholds are selected and no
source or transcription is accepted by this assessment.
