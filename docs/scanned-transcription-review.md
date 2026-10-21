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

Each change has exactly `kind`, `target_id`, `before_sha256`, `state`, `value`,
`reason`, and `evidence`. Kinds are `line_text` (canonical line ID), `quantity`
(table cell ID), or `membership` (canonical line ID). `before_sha256` comes from
`target_digest` over the same predecessor chain. Evidence comes from
`source_evidence` and must include the target's complete canonical line set.
States are `proposed`, `source_reviewed`, or `unresolved`; the last requires an
explicit null value. Resolved text/quantity values are nonempty strings;
membership values are a list containing exactly one existing selection ID.
`reviewer` has exactly `kind` (`agent` or `human`) and nonempty `id`.

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
