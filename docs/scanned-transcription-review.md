# Source-backed review prototype

`cookbook.transcription_review` is a pure stdlib module over the
[canonical scanned snapshot](scanned-transcription-contract.md). It neither
reads files nor invokes OCR. Its public interface is:

```python
source_evidence(snapshot, line_ids) -> list[dict]
target_digest(snapshot, kind, target_id, *, revisions=(), selections=()) -> str
make_revision(snapshot, changes, *, reviewer, revisions=(), selections=()) -> dict
reviewed_view(snapshot, *, revisions=(), selections=()) -> dict
review_queue(snapshot, *, revisions=(), selections=()) -> list[dict]
render_review_report(snapshot, *, revisions=(), selections=()) -> str
```

`selections` is a list of semantic selection records with `id` and `line_ids`
(and optional `kind`, `state`, `reasons`). It binds the initial membership
context; callers validate their entire boundary proposal separately. Selection
IDs and line references must resolve. Review cannot create a new selection.

Each change has required fields `kind`, `target_id`, `before_sha256`, `state`, `value`,
`reason`, and `evidence`. Kinds are `line_text` (canonical line ID), `quantity`
(table cell ID), or `membership` (canonical line ID). `before_sha256` comes from
`target_digest` over the same predecessor chain. Evidence comes from
`source_evidence` and must include the target's complete canonical line set.
States are `proposed`, `source_reviewed`, or `unresolved`; the last requires an
explicit null value. Resolved text/quantity values are nonempty strings;
membership values are a list containing exactly one existing selection ID.
`reviewer` has exactly `kind` (`agent` or `human`) and nonempty `id`.

A `line_text` change may additionally carry an `occurrence` object with exactly
`start`, `end`, `before`, `selection_id`, `role`, and `cell_id`. The half-open
`[start, end)` range counts Unicode code points in the **current effective line**;
`before` must equal that exact slice. `value` is then the replacement slice,
rather than a replacement of the whole line. `selection_id` must own the target
line, `role` names its culinary association (for example `ingredient:stock`), and
`cell_id` is null or a table cell containing that line. The source evidence and
snapshot binding retain physical position, geometry and candidate context.

For the synthetic line `2 cups water; 2 cups stock`, targeting `[14, 15)` with
`before: "2"` and `value: "1"` produces `2 cups water; 1 cups stock`. No string
search chooses an occurrence. Obtain a fresh `target_digest` after each revision;
a chained edit that shifts offsets requires a new exact range. Missing, stale,
ambiguous or unmatched targets raise an explicit validation error and are never
relocated or applied. Whole-line changes retain their existing semantics.

Any change may additionally carry `readings`, a nonempty list of alternatives.
Each has exactly `id` (candidate/evidence identity), `value`, `state`, `reason`,
and `evidence` (bindings from the change's inspected source evidence). States are
`selected`, `rejected`, `tied`, and `unmatched`. At most one reading is selected;
its value must equal the proposed replacement. A `source_reviewed` change requires
one selected reading and no outstanding ties or unmatched readings. To retain
unsettled alternatives, record an `unresolved` change with null value and their
reasons. Raw source text remains intact. Agreement between candidates does not
turn a `proposed` change into source review. Original alternatives remain in the
revision chain; `reviewed_view.readings` also exposes their identities, decisions
and reasons when present, including superseded readings.

Clearance refuses proposed/unresolved text and unreviewed table quantities.
Source-reviewed quantity overlays must agree exactly with the corresponding
effective canonical lines; metadata-only amendments cannot establish that
agreement or clear uncertainty. Administrative inspection reports contradictions;
clearance, approval, replay of those decisions, and finalization refuse them even
if their stored identity hashes are recomputed. Quantity-only overlays remain
unsupported approval scope; use an exact line occurrence to correct served text.

Revisions bind the snapshot, selection context, predecessor revision, reviewer,
and changes by SHA-256. They do not modify recognized text or the snapshot.
`reviewed_view` validates the complete chain and returns `snapshot_sha256`,
`boundary_sha256`, `revision_id`, `lines`, `quantities`, and `memberships`.
Each line includes `line_id`, `page_id`, `physical_page`, `raw_text`, `text`,
`state`, `reason`, `revision_id`, and `evidence`; unresolved displayed text is
null. Quantity and membership maps contain state/value/reason/revision ID.
Original line state is `original`, initial quantity state is `unparsed`, and
initial membership state is `candidate` or `unresolved` when no owner exists.

`source_reviewed` describes inspection, including agent review. It is not
owner acceptance, publication approval, or a claim that all errors are found.
The existing OCR acceptance commands and publisher gates are untouched.

The deterministic queue includes all unparsed or merely proposed table-cell
readings, unresolved quantities/memberships, uncertain table quantities and
suspicious numeric header cells. A high-confidence integer or unit-only reading
can still contain a missing digit, so confidence and numeric appearance never
exclude an unreviewed cell. Cell roles remain model proposals; this conservative
rule can also queue ingredient labels and other non-quantity cells. Confidence
prioritizes items but never approves content. Source-reviewed readings remain
separate from approval and can still carry suspicious-header or uncertainty
diagnostics. Script-free HTML displays
escaped raw and revised text, exact hashes and line/page/geometry evidence; it
makes no network requests and offers no acceptance controls.

This prototype does not establish that a proposed correction matches the
visible source. Digests establish evidence identity, not transcription truth.
No arithmetic or scaling recovers a missing quantity. Source-derived callers
must run through `scripts/ocr_sandbox.py` after admission and before input reads;
pure synthetic tests may run locally. Book data and reports stay outside Git.

## Explicit standalone complete-content approval

Saved scan evidence can now enter an additive administrative path without changing
legacy OCR decisions or the unapproved EPUB export. `ReviewStore` in
`cookbook.transcription_review` retains every candidate snapshot, selection,
revision, effective reading and administrative decision. It performs no rendering,
recognition or inference. Book-derived artifacts belong outside Git.

Use `cookbook review-transcription --review-store /private/review.json` with one
of these operations:

- `--candidate-file /private/candidate.json`: a JSON object with `snapshot`,
  `selections` and `revisions` (the existing canonical saved-evidence interfaces).
  Saving a candidate is a proposal, not an approval.
- `--decision-file /private/decision.json`: arguments to `ReviewStore.decide`:
  `selection_id`, `action`, `actor` (`kind` and explicit `id`) and `reason`.
  Actions are `apply_draft`, `clear_flag`, `metadata_amendment`, `approve` and
  `revoke`. Every record has a timestamp, predecessor, exact candidate, source
  snapshot and effective-reading identities, reviewer configuration and policy.
  `relates_to` links superseding or revoking decisions to retained history.
- `--selection-id ID`: inspect current eligibility, reasons, candidate evidence
  and immutable decision history.

Approval requires explicit human action, `complete: true`, and `evidence` equal
to `source_evidence(snapshot, selection.line_ids)` for the inspected source.
Revised candidates require a separate `apply_draft` decision before approval.
Recording an agent actor does not grant approval authority. Proposed or unresolved
readings and ambiguous ownership cannot qualify. `required_content` must be empty:
this path supports a standalone recipe and line-text corrections; quantity and
membership overlays remain pending until their consistency rules are implemented; dependencies, formulations and variations
need the subsequent complete-content dependency work. The owner must establish
standalone completeness rather than infer it from a boundary proposal. Flag
clearance and metadata amendment do not constitute source comparison.

Pass `--transcription-review /private/review.json` to `finalize-local`, alongside
its existing build, cache and new output directory arguments. Original bytes must
already be backed up in that build with the same source digest. Existing OCR
quality checks still run. Finalization freezes the review history, adds recipe
sections and backs up `quality/content-review.json` in the immutable manifest.
Pending sections expose title, status and original-page citations, with empty
read text and no full-text search row. Only exact approved recipe text enters
search and reading. Citation `content_review` references contain candidate and
decision identifiers and the history artifact path, not correction prose.
Publication quality checks replay the retained evidence and verify text, citation
and search consistency. Use the existing local publication command afterward;
recording approval does not publish or activate anything.

Search/read responses now include `eligibility`. Existing native and legacy OCR
content keeps its previous reading behavior and provenance but gains no implied
complete-content approval. Opening another candidate leaves immutable published
versions alone. A revocation in this review store affects later finalization;
live withdrawal across retained versions is a separate dependency of the parent
spec, not a property of this standalone slice. The history uses digests and
process locking for identity and consistency, not signatures or an authenticated
multi-user authorization service.

These JSON-only operations do not admit source processing. Any PDF/DjVu parsing,
rendering, OCR or model work still requires the unchanged sandbox launcher and
VM/cgroup ceilings in `ocr-resource-isolation.md`.
