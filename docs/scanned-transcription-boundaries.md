# Scanned transcription boundary prototype

The opt-in `cookbook.transcription_boundaries` module proposes semantic selections
over the [canonical scan evidence](scanned-transcription-contract.md). It opens
no files, runs no recognition, and changes no production extraction, search,
publication or approval policy.

```python
propose_boundaries(snapshot: dict) -> dict
validate_boundaries(snapshot: dict, proposals: dict) -> None
```

The result has exactly `version` (`scanned-boundaries.v1`), `snapshot_digest`,
`selections`, `links` and `unresolved_elements`. The digest binds the complete
validated canonical snapshot, including its edition, renders and immutable
recognition. Callers retain the module/code identity separately when recording
an experiment or persisted proposal.

Each selection is `{id, kind, line_ids, state, reasons}`. Kinds are `recipe`,
`passage`, `reference_entry` and `unclassified`; states are `candidate` and
`unresolved`. IDs are deterministic within that snapshot/proposal run, not
permanent identities across changed evidence. Selections reference canonical
line IDs in canonical order; they copy no source text. Every recognized line
has exactly one selection owner. Ambiguous, caption, picture and furniture text
receives separate unresolved selections rather than a combined fallback result.

Each continuation link is `{kind, selection_id, from_page_id, to_page_id,
line_ids, state, reasons}`. Its kind is `continuation`, its state is `candidate`,
and its evidence belongs to the recipe selection on the immediately following
physical page. The selection also contains source-page evidence. The link
records why the continuation was proposed without creating another text copy.
There are no inferred recipe-use links: adjacency and a preparation's name do
not establish its requiredness, amount or scope. An independent preparation
remains a separate candidate; a future source-backed recipe use must be a
separate interpretation, not concatenation of its text into a consumer.

`unresolved_elements` contains `{block_id, reasons}` for every picture occurrence.
No image is assigned to a recipe by proximity or appearance. Independently
represented text children of picture blocks remain readable and can participate
in semantic candidates using their own heading/list evidence.

## Conservative rules

The prototype considers layout headings at every vertical position, including
single-word headings. Consecutive aligned heading fragments can form a
multi-line title. Known ingredient/method headings remain local part labels.
Body regions attach to the latest compatible heading by geometry; competing
matches remain unresolved. Repeated parent/child evidence is selected once,
preferring the smallest direct leaf region; equally specific competing leaves
remain unresolved.

A recipe candidate requires an independent heading, at least two quantity-led
ingredient lines, and numbered instructions beginning at 1. Authored list
markers retained separately from text count as numbering evidence. Prose that
contains `serves` is insufficient. Explicit menu/passage/reference-region labels
take precedence, and exact authored Menu, Shopping list or Meal plan headings
remain passage candidates. A heading plus ordinary prose remains unclassified
and unresolved: absent ingredient/method cues cannot distinguish a passage from
a detached recipe headnote. A title-only window edge also remains unresolved.

Only a headingless, numbered method region can continue a recipe. Its first
number must be the exact next number, the physical page must be consecutive,
render dimensions must agree, and the previous numbered method must occupy a
compatible horizontal lane. Multiple possible predecessors remain unresolved.
A neighboring preparation's own heading starts an independent selection.
Unnumbered detached paragraphs are not carried forward by adjacency.

For two-column recipes, a heading whose geometry spans and encloses both
ingredient and method columns can propose a common scope. A narrow title with
no evidence linking the other column leaves membership unresolved. This is a
deliberate measured limitation, not automatic recovery of ordinary multi-column
layouts. Model table labels, header flags and nearby quantities do not establish
formulation semantics or exact amounts.

## Validation and evidence limits

The validator rejects stale digests, unknown shapes/states, missing/duplicate or
foreign lines, reordered selections, invalid continuation endpoints, and omitted
unresolved picture ownership. Structural validity is not source-supported
ownership, correct classification, complete transcription or owner approval.
An unresolved selection still points to readable canonical evidence.

Synthetic unit tests reproduce the earlier failure mechanisms without book
quotations: independent sidebar beside a final continued step; single/multi-line
headings; menu, title-only, reference and wine prose; number/page gaps; ambiguous
ownership; parent/child duplication; retained photograph instruction children;
and the two-column supported/unresolved cases. These test mechanisms, not
recognition accuracy or library recall.

The private development integration report is
`/Users/rick/cookbook-mcp-data/poc/pdf-prototype-20261011/boundaries/report.md`.
It uses four existing saved structured pages and measures line coverage and
proposal counts only. The rule requires structure that these saved layouts
often do not provide, so it does not yet recover their recipes automatically.
There is no new-book evaluation, held-out claim, query-recall improvement or EPUB
parity result. Neither the old cohort nor the private report is a Git fixture.

Any caller opening book-derived JSON to run this proposal is a private scan
experiment and must first read [resource isolation](ocr-resource-isolation.md),
run the doctor, and invoke a guarded entrypoint through `scripts/ocr_sandbox.py`.
Keep the existing 4 GiB/two-CPU VM and 2 GiB/zero-swap/two-CPU/64-PID/300-second
job limits. Pure synthetic functions/tests can run locally.
