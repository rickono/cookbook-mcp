# Derived scanned reading export

`cookbook.transcription_export.export_epub` is a pure stdlib function over saved,
validated evidence. It returns deterministic EPUB bytes without file IO, PDF
parsing, image rendering, model loading, publication, or library activation.

```python
export_epub(
    snapshot,
    *,
    boundaries=None,
    revisions=(),
    reading="raw",  # explicitly choose "review" to display correction overlays
    title="Scanned transcription — unapproved reading copy",
    language="en",
) -> bytes
```

The [canonical JSON snapshot](scanned-transcription-contract.md) remains the
transcription source of record; the original book edition remains authoritative.
The export visibly labels itself an unapproved reading copy, including when the
caller chooses a custom title. Digest validation establishes evidence identity,
not transcription truth, owner acceptance, or EPUB parity.

## Reading and navigation

One XHTML document retains every canonical raw line exactly once in the given
canonical page/line order, including unsupported text, prose, captions and
running furniture. Empty recognized lines remain represented. Each line has a
stable XML-safe fragment ID and visible edition/physical-page/line citation.
Separate list markers are exposed where the raw line does not already contain
them. No original book images or invented original-file URLs are included.

Optional [boundary proposals](scanned-transcription-boundaries.md) add navigation
links to individual source lines. Cross-page and discontiguous selections remain
links, without copying their transcription or pulling in neighboring sidebar
text. Selection IDs and candidate/unresolved states are displayed; they are not
reviewed titles, recipe completeness claims, or authored navigation. The original
physical-page list points to page sections. The module preserves the snapshot's
given order rather than attempting another layout sort.

`reading="raw"` is the safe default. Revisions are validated and preserved in
provenance, but corrected values are not substituted into raw reading. Known
unresolved text and quantities still receive prominent markers. Raw OCR is
explicitly evidence rather than a verified ingredient quantity.

`reading="review"` shows proposed/source-reviewed line overlays alongside the
once-preserved, labeled raw evidence. A null overlay displays unresolved content
without inventing a reading. Quantity overlays are separate cell annotations,
not automatic replacements for line text or inferred parsed amounts. An
unresolved quantity never falls back to raw OCR as its asserted value. A
multi-line quantity appears once at its first canonical line. Applying a line
correction does not settle a distinct quantity interpretation.

Review-mode selection links follow current membership overlays. Unresolved
membership remains visibly unresolved in source reading and is omitted from
semantic ownership links; reassigned lines link only from their current owner.
Raw-mode navigation retains the original boundary proposals. Neither mode moves
or duplicates source lines. Header flags, adapter diagnostics and unresolved
picture ownership remain explicit caveats. The [review contract](scanned-transcription-review.md)
binds revisions to snapshot, selection context and predecessor chain.

## Package and provenance

The EPUB 3 package has a navigation document, a single source-reading spine
entry, CSS, and embedded `provenance.json`. The JSON preserves the entire raw
snapshot, polygons, render-to-source affine transforms, edition/page/render/
recognition digests, diagnostics, boundary proposals, revision chain, and replayed
view. It does not contain original book bytes or verify those declared hashes
against external originals. A guarded file-owning caller must do that separately.

The ZIP begins with the uncompressed, extra-field-free `mimetype` entry. All
members use fixed timestamps, stable ordering and stored compression; the package
identifier hashes the evidence, options and export version. The fixed metadata
modified time is a reproducibility sentinel, not an inspection timestamp. JSON
has a manifest fallback to the XHTML reading. Source and reviewer strings are
escaped through XML serialization; unsupported XML 1.0 characters fail rather
than silently disappearing. Packaging follows the relevant
[EPUB 3.3 container and manifest requirements](https://www.w3.org/TR/epub-33/).

Synthetic tests verify ZIP/XML structure, internal links, source-line coverage,
escaping, citations, deterministic bytes, stale identities and unresolved
values. A complete synthetic canonical → boundary → review → EPUB test keeps a
continued recipe distinct from its neighboring sidebar. These tests do not prove
recognition accuracy, semantic ownership accuracy or reader interoperability.
No independent EPUBCheck or real e-reader certification is claimed.

## Private use and next evaluation

Synthetic pure tests can run locally. Any book-derived saved-evidence conversion
or scan experiment must use `scripts/ocr_sandbox.py`, after reading
[resource isolation](ocr-resource-isolation.md), with the guard before input
reads. Keep inputs, candidate EPUBs, review outputs and source-derived reports
outside Git. Preserve the existing 4 GiB/two-CPU VM and 2 GiB/zero-swap/two-CPU/
64-PID/five-minute job ceilings. The exporter has no CLI publication path.

Before another accuracy test:

1. Freeze the prototype versions, rule/configuration identities, export mode,
   outcome definitions and expected resource limits. Existing cohorts are now
   development material.
2. Independently enroll new book editions and a fixed source-page inventory
   before inspecting their content or predictions. Include continuation/sidebar,
   table formulation, prose and unreadable/edge cases without selecting for known
   prototype success. Freeze source references independently of candidate outputs.
3. Measure exact line coverage/order, complete and uncontaminated recipe ownership,
   quantity-to-ingredient/formulation associations, explicit unresolved content,
   source-page citation fidelity and unresolved semantic relationships. Keep raw
   recognition, boundary proposals and selected review overlays distinguishable.
4. Record total review effort from initial candidate/source reading through
   correction, escalation and final checking, including setup and tool delays.
   Instrumented correction windows alone do not estimate total effort. Agent
   source review remains separate from owner decisions.
5. Compare with an EPUB only when edition and authored content match, reporting
   unmatched/omitted content explicitly. Assess retrieval separately from correct
   reading and recipe ownership. Do not claim parity from target-word presence or
   ZIP conformance.

This protocol proposes a bounded new evaluation. It does not authorize open-ended
fresh-book OCR, publication or promotion of agent-reviewed content.
