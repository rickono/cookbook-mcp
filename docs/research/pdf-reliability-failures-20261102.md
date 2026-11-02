# PDF failure boundaries and retained evidence

Research for [Trace PDF failures from model response through served content](https://github.com/rickono/cookbook-mcp/issues/112), under [Make PDF transcription and assembly reliably source-faithful](https://github.com/rickono/cookbook-mcp/issues/110). This answers the factual failure-tracing question. The destination is a pipeline specification and repair plan with measured acceptance criteria. It does not authorize implementation or publication.

The failures cross several independent boundaries. Recognizable assistant responses can become book text. Correct words can have the wrong reading order or section owner. Page uncertainty can survive candidate validation yet disappear from a recipe's completeness status. Source-image delivery can fail independently of text delivery. The retained evidence establishes these mechanisms, not their prevalence across the library.

## Evidence scope and provenance

The owner confirmed that the first audit covers all currently published PDFs and known local candidates. This ticket supplies selected failure evidence for that audit, not a complete inventory or full-book review. Transcript discovery also includes retained outputs, embedded PDF text, matching local EPUB editions, and legitimate publisher or author sources. Discovery and edition alignment belong to the companion research; no acquisition or new parsing occurred here.

Current source was read from `/Users/rick/Documents/ChatGPT/cookbook-mcp`, separately from the prepared research worktree. Both had HEAD `0384b358d2f51e5ef2ad54c64e72f4291366adf0`. The root has concurrent uncommitted changes. In particular, the response gates in `quality.py`, `readers.py`, `pipeline.py`, and `candidate.py` are not all represented by HEAD. Root file links below identify inspected files, not immutable committed versions. The private SHA-256 manifest binds the inspected bytes; no dirty implementation was copied into this branch.

Private evidence is under `/Users/rick/cookbook-mcp-data/planning/pdf-reliability-wayfinder-20261102/failures/`. Its `evidence-sha256.json` identifies selected code, saved results, and logs. `observations.json` records the selected response trace. `capture-evidence.py` repeats only saved JSON/text inspection and hashing. Original evidence remains at the paths cited below. No source text, per-book inventory, raw response, or image is included in Git.

## Earliest failing boundaries

| Failure class | Earliest established failure | Evidence and limit |
|---|---|---|
| Response classification | Heston physical page 63, printed page 59, returned refusal plus summary as a successful page read. The saved raw text equals final text; the call record contains one Haiku call with no errors or fallback. The candidate calls the page `transcribed`. | [Saved raw record][raw63], [response audit][haudit], and [candidate pages][hpages]. This is a saved observed defect, not a newly executed trial. |
| Cache reuse | A saved page record can preserve contaminated final text across resumed assembly. Current `run_page` now rejects recognized contamination on a cache hit before calling a reader. | [Pipeline][pipeline] `run_page`, [quality tests][qtests]. This closes the recognized-pattern path; it does not establish cache content fidelity or source approval. |
| Layout order | Heston physical page 25 interleaves columns before section assembly. The retained local repair records source-reviewed splits and preservation of the word multiset. | [Repair evidence][hrepair]. Equal words do not prove equal meaning. The repair receipt establishes the selected-page finding; this research did not repeat visual review. |
| Section identity and continuation | An essay across physical pages 23, 25, 27, 28, 29, and 30 was separated across labels. Its modern recipe on pages 31–32 is a distinct section. | [Repair report][hreport], [repair evidence][hrepair], [assembler][assemble]. The exact contribution of individual label mistakes versus title matching is not isolated by an experiment. |
| Physical versus printed location | Physical page 26 is artwork, while printed page 26 is physical page 30. A duplicate printed label on physical page 29 was removed locally because no folio was visible. | [Repair evidence][hrepair]. Other printed labels remain unverified. This is a location-label failure, not evidence that the text of printed page 26 is absent. |
| Quantity occurrence and ownership | Historical text patching could target a repeated ingredient occurrence incorrectly or corrupt a fraction span. Current `patch` rejects unbound proposals rather than editing text. | [Saved synthetic reproduction][heldsynthetic], [current pipeline][pipeline]. Historical reproduction covers two patch paths and controls. It does not show that the current no-edit path still has the historical mutation. |
| Uncertainty propagation | Current assembly intentionally leaves rejected crop votes without an owner or source fragment. Candidate pages retain uncertainty, but import can label an intersecting recipe `complete_in_book` without its unresolved marker. | [Full-suite log][fullsuite], [baseline log][baseline], [assembler][assemble], [candidate writer][candidate], [importer][scanned]. This is a demonstrated synthetic visibility defect, not a confirmed wrong amount in a real book. |
| Candidate validation | Hash, schema, page coverage, and reference checks accept internally consistent content without establishing source fidelity. The new writer rejects recognized response contamination; the generic importer validates the frozen contract. | [Candidate writer][candidate] `write`, [importer][scanned] `validate_candidate`. Candidate import success is not source/content approval. |
| Serving images | Saved Heston decoder probes produced PNG bytes and exit zero together with decoder errors. The serving worker rejects stderr, so text availability does not establish source-image availability. | [Follow-up investigation][followups], which identifies retained low-level probes and serving code. This research did not call the service or render sources. Four low-level probes were recorded; a default renderer edge is not a fifth executed probe. |

## Fallback and gate scope

Current `readers.call` classifies recognized textual refusal or commentary as terminal for that call. Provider output filtering is represented separately by error text matching `content filtering policy`. `pipeline.run_page` invokes its configured fallback only if page text is absent and `filtered(record)` is true. Timeouts, rate limits, ordinary empty replies, and newly classified textual refusals do not automatically qualify. Region and crop calls use the configured reader samples without this page fallback. A historical filter error followed by Luna output appears in the [saved audit][haudit], so the configured route is evidenced beyond documentation. [Readers][readers], [pipeline][pipeline].

The Heston page-63 response originally escaped refusal detection. A nonempty reply was accepted and no fallback condition was reached. Current reader checks would reject the recognizable response instead. Cache and candidate-writer checks reject matching saved `final_text`; neither check automatically repairs an existing candidate. The tests cover mocked live responses, cache refusal, candidate refusal, normal authored prose, reviewed column splits, and heuristic audit findings. [Quality module][quality], [tests][qtests].

The quality detector examines only the first 700 characters and uses explicit patterns. The reader also retains an older refusal regex, including a broad copyright match in the first 400 characters. Cache and writer checks use the newer detector only. These paths therefore have different classification coverage. False positives, paraphrased refusals, late commentary, and undetected omissions remain unmeasured. Width and interrupted-section findings are review prompts, not confirmed defects. The inspected gate paths do not enforce all structural audit warnings. [Quality module][quality], [readers][readers], [candidate writer][candidate].

The assembler labels numbered text with limited neighboring text context. Its `check` verifies contiguous line coverage, not correctness of title, folio, or continuation. `find` uses normalized title similarity, page distance, and recent section ownership. Those rules explain how plausible labels can produce mistaken associations, but do not independently prove each Heston label's causal contribution. [Assembler][assemble] `label_page`, `check`, `build`.

The owner explicitly authorized one local Luna retry despite older blanket refusal guidance. Its saved result contains nonempty text, records one-call scope, and states that the candidate was unchanged, the response unreviewed, and publication false. This establishes response availability only. It neither approves replacement text nor decides general automated recovery. The historical policy remains historical evidence; the current human fallback decision remains open. [Retry result][retry], [map](https://github.com/rickono/cookbook-mcp/issues/110).

## Contrasting retained cases

Ikoyi provides independent saved evidence of assistant commentary entering a candidate. Its source-review receipt removes such content while preserving raw evidence and withholding full-content approval. The replay audit distinguishes excluded commentary from retained source captions. Its old-patch audit records quantity and wording changes; its repair validation records targeted repaired-content checks. Those records support a quantity-association and classification failure family, not a general accuracy rate. The receipt, replay output, and final validation name different candidate digests and stages; they must not be combined into one approval receipt. [Source-review receipt][ikreceipt], [replay audit][ikreplay], [old patch audit][ikpatch], [validation][ikvalidation].

World Atlas of Coffee's early processing report records visible map labels missed by baseline OCR, a misrecognized title, and a paragraph continuation exported out of order. Its first visual audit identified missing or obscured sources. A later rescan update records resolution of the required physical rescan requests. A later structural receipt distinguishes authored reference entries and caption boundaries and still marks content unapproved. The early missing-source findings are historical, not a statement that those sources are still missing. Empty OCR, a clean physical scan, a structural pass, and content approval are separate claims. [Processing report][atlasprocessing], [initial scan audit][atlasscan], [rescan update][atlasupdate], [structural receipt][atlasstructural].

The older held-six investigation retains a synthetic reproduction of fraction-span corruption and ambiguous-occurrence replacement in both historical patch paths. Single-occurrence and reordered-line controls pass. Its resolution also distinguishes retained required ingredients, duplicate procedures, ownership uncertainty, and source-printed inconsistency. These are useful regression families. The old refusal totals and route restrictions are historical dispositions, not current library inventory or a blanket blocker under the owner's override. [Synthetic results][heldsynthetic], [historical resolution][heldresolution].

## The six older test failures include a real defect

The retained full-suite log reports 516 passes and six failures. A baseline using original HEAD `production.py` with current reader modules reports the same six failures and eleven passes. This excludes the new production entrypoint as a necessary cause. It does not establish that the historical HEAD suite failed, or that current reader behavior is correct. No suite was rerun here. [Full-suite log][fullsuite], [baseline log][baseline].

Two failures concern the older configuration identity. Three concern prior assumptions about crop replacement, ownership, or reviewed lists. Their assertion updates still need intentional verification. The contract-roundtrip failure reports actual `complete_in_book` versus expected `has_unresolved`. It must not be dismissed with those obsolete expectations.

The code trace is specific. `pipeline.patch` keeps the read and rejects unbound votes. Assembly clears the occurrence fragment and owner for rejected votes. The writer attaches part markers only with a section and matching fragment. Import adds explicit ownership and failed-page markers, but cannot mark an unowned amount without its fragment. It then derives recipe status from marked rows. Uncertainty therefore survives on the page while disappearing from the recipe's completeness status. Conservative propagation must preserve unknown ownership rather than invent an ingredient association. [Pipeline][pipeline], [assembler][assemble], [writer][candidate], [importer][scanned] around lines 796–871.

## Observable regressions for the future specification

These are proposed observables, not executed acceptance results:

- A refusal plus summary never becomes source text through a fresh response, cache hit, candidate write, import, or served recipe. Synthetic authored first-person prose remains unchanged.
- A provider filter error, textual refusal, timeout, rate limit, and empty reply retain distinct dispositions. Allowed attempts and fallback decisions are observable without live calls.
- Column order and multi-page passage ownership match a reviewed oracle. Word preservation alone cannot pass. A later recipe remains separate from its historical essay.
- Physical-page citations remain stable through artwork and absent or duplicated printed folios. Unverified printed labels remain explicitly unverified.
- Repeated ingredient wording, fraction variants, and reordered lines never permit an unbound proposal to mutate an occurrence. Required ingredients and unique procedure steps survive duplicate handling.
- A recipe intersecting page-scoped quantity uncertainty exposes that uncertainty after candidate import and serving, including on a two-recipe page. No owner is fabricated. Page and recipe reads retain source bindings and check regions.
- An empty OCR response never proves blankness. Decoder stderr, incomplete images, and unexercised rendering remain distinct from verified source-image delivery.

A later controlled comparison should report source-reviewed substantive and critical errors, false clearance, abstentions, review failures, and complete-content outcomes separately for page recognition and multi-page assembly. The present evidence provides failure cases, not a measured superiority claim for OpenAI Decisions, Jev, or any reader. Corpus coverage, oracle authority, missed-error validation, retry bounds, external handoff, and spending limits remain human decisions. No model comparison ran.

The Heston local repair is evidence preservation and selected repair, not a general pipeline fix. Its saved verification records targeted synthetic passes alongside a separately retained contract-roundtrip failure. It does not establish full-book fidelity or approve the alternate-provider text. All Heston repair remains local. [Repair report][hreport], [verification][hverification].

[raw63]: /Users/rick/cookbook-mcp-data/production/historic-heston-20261101/transcription/pipeline-claude-haiku-5-5-x3-occurrence-v1-fb-gpt-6-luna--low-a5/work/pages/b90-p063.json
[haudit]: /Users/rick/cookbook-mcp-data/production/historic-heston-repair-20261101/final/saved-response-audit.json
[hpages]: /Users/rick/cookbook-mcp-data/production/historic-heston-20261101/screened-candidate-v2/pages.jsonl
[hrepair]: /Users/rick/cookbook-mcp-data/production/historic-heston-repair-20261101/final/repair-evidence.json
[hreport]: /Users/rick/cookbook-mcp-data/production/historic-heston-repair-20261101/final/report.txt
[hverification]: /Users/rick/cookbook-mcp-data/production/historic-heston-repair-20261101/final/verification.json
[retry]: /Users/rick/cookbook-mcp-data/production/historic-heston-repair-20261101/luna-page63-owner-retry-01/result.json
[followups]: /Users/rick/cookbook-mcp-data/planning/heston-followups-20261101/report.md
[fullsuite]: /Users/rick/cookbook-mcp-data/poc/pdf-workflow-full-suite-20261101-02/job.log
[baseline]: /Users/rick/cookbook-mcp-data/poc/pdf-workflow-baseline-20261101-01/job.log
[heldsynthetic]: /Users/rick/cookbook-mcp-data/poc/held-six-wayfinder-20261026/repair-evidence-synthetic.json
[heldresolution]: /Users/rick/cookbook-mcp-data/poc/held-six-wayfinder-20261026/repair-evidence-resolution.md
[ikreceipt]: /Users/rick/cookbook-mcp-data/production/ikoyi-repair-20261031/inputs/source-review-receipt.json
[ikreplay]: /Users/rick/cookbook-mcp-data/production/ikoyi-repair-20261031/output/replay-audit.json
[ikpatch]: /Users/rick/cookbook-mcp-data/production/ikoyi-repair-20261031/non-base-old-patch-audit.json
[ikvalidation]: /Users/rick/cookbook-mcp-data/production/ikoyi-repair-20261031/repair-validation.json
[atlasprocessing]: /Users/rick/cookbook-mcp-data/production/world-atlas-coffee-20261101/summary/processing-report.txt
[atlasscan]: /Users/rick/cookbook-mcp-data/production/world-atlas-coffee-20261101/visual-review/rescan-audit.txt
[atlasupdate]: /Users/rick/cookbook-mcp-data/production/world-atlas-coffee-20261101/rescan-update-01/summary/rescan-audit-update.txt
[atlasstructural]: /Users/rick/cookbook-mcp-data/production/world-atlas-coffee-20261101/pipeline/structural-review-receipt.json
[quality]: /Users/rick/Documents/ChatGPT/cookbook-mcp/scripts/reader_bench/quality.py
[readers]: /Users/rick/Documents/ChatGPT/cookbook-mcp/scripts/reader_bench/readers.py
[pipeline]: /Users/rick/Documents/ChatGPT/cookbook-mcp/scripts/reader_bench/pipeline.py
[candidate]: /Users/rick/Documents/ChatGPT/cookbook-mcp/scripts/reader_bench/candidate.py
[assemble]: /Users/rick/Documents/ChatGPT/cookbook-mcp/scripts/reader_bench/assemble.py
[scanned]: /Users/rick/Documents/ChatGPT/cookbook-mcp/src/cookbook/scanned.py
[qtests]: /Users/rick/Documents/ChatGPT/cookbook-mcp/tests/test_reader_quality.py
