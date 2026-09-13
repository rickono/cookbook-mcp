# PDF evidence: what is established before agent-first review

Assessment date: 2026-09-13. Repository baseline: `d7516c9c2ae4816c4193cbf8d4f7f0c2c508dc3c`.
This assessment reads existing reports and source code only. It does not rerun
experiments, independently reinspect page pixels, approve content, or select an
acceptance policy. Private reports are cited by local reference; book passages,
images and raw records are deliberately absent.

## Finding

The evidence supports retaining competing extraction candidates, targeted recovery
and source-grounded corrections. It does **not** establish that an agent pass can
correct everything except the owner's real edge cases. That is a measurable
hypothesis: the missing evidence concerns errors left behind, correct content
damaged, omissions missed, and the resulting human workload—not simply whether a
review agent can find some errors. [P1, P2]

## What the existing trials establish

| Evidence | Observed result | Limit on interpretation |
| --- | --- | --- |
| September 13 survey | 19 PDFs, including 18 cookbooks; 57 fixed page renders; 22 pages visually inspected. Text coverage and source types vary. | Metadata and text presence do not certify accuracy or completeness. Most pages were not visually inspected. [P1] |
| Matched diagnostic comparison | 11 cookbook pages, 31 frozen probes: 14 quantities, 10 controls, seven title/region probes. Native text passed 15; default whole-page OCR 17; best-English whole-page 16; manual regions 14; contrast-adjusted regions 19. Quantity passes were respectively 5, 5, 5, 5 and 6 of 14. All five explicit fraction probes failed in every OCR variant. | Purposive sample, agent-read references, short-span presence scoring; neither a corpus error rate nor complete-recipe accuracy. The strongest aggregate candidate also loses content preserved elsewhere. [P1, C1] |
| Denser regional follow-up | Two sampling densities on six regions from four difficult pages; no recovery of the three fraction probes tested. Two initially clipped crops were expanded and rerun without changing their probe outcomes. | Selected follow-up, not held-out evidence. Crop selection and bounds affect results; more pixels alone are not a demonstrated solution. [P1] |
| Earlier visual agent review | 35 purposively selected pages, including four unflagged controls, revealed quantity errors, omissions, merged columns and obscured source content. An unflagged control contained a source limitation. | Demonstrates that agents can identify defects and that automatic flags miss some problems. No independent complete gold reference, measured review sensitivity, correction-precision estimate or workload reduction. Labels were recommendations, not applied approvals. [P2] |
| Earlier seven-page engine trials | Manual-region Tesseract repaired 6/17 selected errors while retaining 5/5 controls. Automatic-layout English Paddle without dewarping repaired 8/17 and retained 5/5; dewarping repaired 10/17 but retained only 3/5. All five fraction probes still failed. | Baseline zero repairs is by construction: probes were selected from baseline errors. Automatic layout showed promise on selected pages, not measured full-region recall. Historical native runtime does not establish admission or performance inside today's sandbox. [P3, P4, C6] |

The four September 13 correction proposals show that specific errors can be
transcribed from source evidence. They are unaccepted proposals, not a measured
agent-correction system or a transferable approval batch. [P1]

## Trial methods versus the current implementation

The September 13 native candidate uses Poppler `pdftotext -layout`. Its direct
whole-page OCR candidates use the same 2,300-pixel-long-edge JPEG source render,
PSM 3 and no production orientation/deskew processing. Manual crops use PSM 6,
padding and optional grayscale autocontrast. The frozen regions supply both
selection and concatenation order. The experiment therefore does not test
automatic region discovery or the complete production extraction pipeline. [P1, C1]

Production PDF ingestion instead uses pypdf `extract_text()`, invokes OCR when
`len(re.sub(r"\W", "", native)) < 40`, and otherwise retains native text without an
OCR assessment. Explicit forced-OCR sources bypass native text on every page.
Production OCR renders a PNG at a 2,500-pixel edge, compares quarter-turn
orientations using 1,600-pixel probes, deskews, then performs English PSM 3
recognition. Its confidence flags are not the research candidate-disagreement
helper. Neither path implements a source-inspecting review agent. [C2, C3]

Consequently, the 19/31 versus 17/31 comparison does not measure an improvement
over the current production pipeline. Candidate agreement also cannot detect a
shared omission or prove that a number is attached to its correct ingredient;
the research helper explicitly never accepts text. [C1]

Production already supports digest-bound, whole-page accept/correct/non-text
decisions and new-publication finalization that updates section text and search.
These decisions currently describe explicit human action. The publication gate
checks OCR provenance and requires decisions for flagged OCR pages; ordinary
native pages can pass without an OCR assessment, and unflagged OCR does not
require an explicit decision. This enforces the existing policy, not complete
recipe correctness. A general native-text correction route, agent approval
authority and partial unresolved-content publication are not established by this
mechanism. [C2–C5]

## Proposed validation outline, not an acceptance decision

1. **Freeze the actual baseline and evaluation units.** Capture production
   configuration and immutable inputs. Use a varied development set plus a
   separate held-out set; include apparently clean native pages, unflagged OCR,
   images with small text, columns, tables, curved scans and multi-page recipes.
   Keep purposive challenge results separate from any representative sample
   intended to estimate corpus rates.
2. **Establish independent source references.** Transcribe complete selected
   recipes and annotate their regions, reading sequence, continuations and
   ingredient/quantity relationships. Include units, fractions, temperatures and
   timings. Have a reviewer independent of the tested agent adjudicate ambiguity;
   unreadable source spans remain unresolved. Today's agent-read probes alone
   cannot serve as independent validation of that same agent's judgments.
3. **Evaluate discovery and review separately, then end to end.** Compare actual
   production output, candidate recovery and the proposed agent pass on the same
   held-out material. An agent must inspect full-page evidence as well as crops:
   reviewing only flagged spans cannot find regions nobody detected. Score exact
   critical-value correctness, omitted/extra ingredients and instructions, region
   recall, reading order, table associations and complete-recipe correctness.
4. **Measure failures of delegation.** Count source-supported corrections,
   introduced errors, unresolved errors incorrectly cleared, real problems
   escalated and unnecessary escalations. Audit a representative sample of
   agent-cleared content independently, including pages that began unflagged.
   Candidate disagreement and confidence are input signals; calibrate them
   against these outcomes rather than interpreting them as probabilities.
5. **Measure usable results and cost.** Test finding a recipe, reading all its
   content, seeing unresolved spans and resolving citations to original physical
   pages. Record total agent time/cost, retries, human cases and human minutes,
   including audit work. Retain sufficient provenance to reproduce mistakes.
   Report uncertainty and breakdowns by source/layout type before proposing
   owner-approved thresholds.

Any future parsing, OCR or model evaluation must use the existing admitted Linux
VM/cgroup launcher. Current ceilings are fixed; historical model successes do not
authorize native execution or a ceiling increase. [C6]

## Questions now sharp enough to decide

- What independent reference process and held-out sampling design will test
  agent corrections and catch errors on agent-cleared or initially unflagged pages?
- What evidence must the agent inspect to declare a recipe complete across
  omitted regions, column/table relationships and physical-page boundaries?
- How will candidate recovery and agent review be compared against the actual
  production baseline, with both quality regressions and end-to-end review cost
  recorded?

These questions supply evidence for later decisions about escalation, approval
authority and acceptable error/workload levels; this assessment settles none of
those owner policies.

## Sources

Private references are relative to the owner's local `~/cookbook-mcp-data/poc/`
directory. They are not public assets or instructions to upload evidence.

- **P1:** `pdf-corpus-20260913/report.md`, sections “Matched comparison,” “Higher-resolution regional follow-up,” and “Safety, validation and reproducibility.”
- **P2:** `build-ocr-trial-20260912-fullscan/vision-review/sample-summary.md`.
- **P3:** `ocr-experiments-20260912/report.md`, design, results and limitations.
- **P4:** `ocr-experiments-20260912/paddle/report.md`, fixed comparison and configuration limitations.
- **C1:** [Trial methods](https://github.com/rickono/cookbook-mcp/blob/d7516c9c2ae4816c4193cbf8d4f7f0c2c508dc3c/docs/pdf-corpus-trials.md) and [candidate scoring/triage implementation](https://github.com/rickono/cookbook-mcp/blob/d7516c9c2ae4816c4193cbf8d4f7f0c2c508dc3c/scripts/pdf_candidate_trial.py).
- **C2:** [PDF ingestion and page provenance](https://github.com/rickono/cookbook-mcp/blob/d7516c9c2ae4816c4193cbf8d4f7f0c2c508dc3c/src/cookbook/extract.py#L475-L543).
- **C3:** [OCR processing, flags and review decisions](https://github.com/rickono/cookbook-mcp/blob/d7516c9c2ae4816c4193cbf8d4f7f0c2c508dc3c/src/cookbook/ocr.py).
- **C4:** [Publication gate and finalization](https://github.com/rickono/cookbook-mcp/blob/d7516c9c2ae4816c4193cbf8d4f7f0c2c508dc3c/src/cookbook/quality.py).
- **C5:** [Review behavior and historical limitations](https://github.com/rickono/cookbook-mcp/blob/d7516c9c2ae4816c4193cbf8d4f7f0c2c508dc3c/docs/ocr-review.md).
- **C6:** [Mandatory resource isolation](https://github.com/rickono/cookbook-mcp/blob/d7516c9c2ae4816c4193cbf8d4f7f0c2c508dc3c/docs/ocr-resource-isolation.md).
