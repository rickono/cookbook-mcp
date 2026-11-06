# Section validation and withdrawal observations

## Problem

[Trace slow book opening, saved-location resolution, and recipe reading](https://github.com/rickono/cookbook-mcp/issues/135)
identified two repeated operations. `Library.read_section` fetched withdrawal policy
separately for suppression and two eligibility projections. `resolve_current`
then discarded its successful pinned read when it derived a missing source key.
A scanned text response made six serial policy reads. A withdrawal between those
reads could also make text and eligibility disagree.

## Usage

Callers keep the existing interface. A delivery reads once, derives its source
reference, and resolves current availability with the same validated result:

```python
data = read(library, location)
saved = source_location(library, location, _validated=data)
update = resolve_current(library, saved, _validated=data)
```

Saved locations and passive update checks have no earlier validated result:

```python
update = resolve_current(library, saved_location)
```

MCP and artifact callers keep using `library.read_section(...)`. Each section
call observes current withdrawal policy independently.

## Shape

There are no new runtime types, fields, or public signatures. These signatures
and pseudocode specify the two ownership boundaries:

```python
def read_section(self, publication_id, book_id, source_id, section_id,
	             offset=0, limit=4000) -> dict:
	raise NotImplementedError
	# Check bounds, publication, book, source, and section first.
	# Observe current withdrawals once, in a local variable.
	# Derive suppression, citation eligibility, and response eligibility
	# from that observation. Build text and continuation as before.


def resolve_current(library, location, *, _validated=None) -> dict:
	raise NotImplementedError
	# Use the supplied validated result or read the pinned location.
	# Derive a missing section key with source_location(..., _validated=pinned).
	# None keeps the existing independent fallback read after a failed pin.
	# Keep all local locator and uniqueness checks.
	# A different current publication still gets its own content read.
```

`library.py` owns the section's policy observation. `withdrawal.py` retains
parsing and event validation. `reader_updates.py` owns reference derivation and
reuse of its pinned result. Delivery and personal-state callers stay unchanged.
The existing interface hides acquisition and reuse without exposing policy
objects or a new lifecycle to callers.

The observation lives only in the `read_section` call. Nothing is retained on
`Library`, `Runtime`, or ambient request state. The next call fetches again.
Policy errors still fail before text delivery. Keeping acquisition after identity
checks preserves unavailable-location responses during policy-store outages.

## Synthesis decision

Two models designed distinct alternatives: local function ownership and a typed
`ReadingOperation` with proof and passage caches. An independent cross-model
review and the implementing agent both selected local ownership. The review simplified the
proposed identity helper to direct forwarding of `pinned`: reachable callers
already supply a result for the same publication, book, source, and section.
No helper or new cache is needed.

The selected design keeps the failed-read fallback. Reader links permit larger
offsets than the library's read bounds. A pinned read can fail while a subsequent
read with offsets stripped succeeds. Returning unavailable immediately would
change existing recovery and the 404 notice. The alternative operation design
made that behavior change and required migrating callers, tests, and docs.

Both candidates agreed that policy belongs inside each section call. The wider
operation's proof and policy wrapper types add no benefit on this confirmed
path. Its migration was rejected. The final design also retains the minimal
candidate's response-coherence and offset-recovery regression cases.

The design adds no module, public API, forwarding wrapper, shared writer,
or duplicate source-key policy. Optional projection arguments remain because
making them mandatory would also change the separate image paths.

## Tradeoffs accepted

- A changed current publication gets a separate read and policy observation.
- Failed pinned reads retain existing fallback work and availability outcomes.
- Local row and uniqueness checks still run during source-reference derivation.
- A policy change after the observation is enforced on the next call. Removing
  later redundant reads also removes failures that occurred only on those reads.

## Alternatives considered

A process-level policy cache would miss withdrawals and violates freshness.
An explicit reading operation would expose a new caller lifecycle without saving
more work on the diagnosed path. Request-wide event threading would expand the
arguments across modules to save an additional read only during publication updates.

## Open questions and risks

Should the existing excessive-offset recovery change in a separate revision?
Should image paths also share their policy observation under their own scope?
Neither decision is required for this change.

EPUB stalls and historical HTTP 503s remain unexplained. Follow-up instrumentation
should measure executor queue delay, native reads and projection, local SQL, and
personal-state loads under the real request deadline. Timing-only measurements
must leave failure attribution unchanged: `reader_diagnostics.stage` also selects
the failure category and stage. No new diagnostic stage belongs in this fix.

## Verification

`tests/test_reader_validation.py` exercises authenticated synthetic HTTP requests.
It checks policy read counts, next-request freshness, response coherence during a
withdrawal, independent current-publication reads, preserved offset recovery,
policy failures, identity errors, contents, and unavailable saved locations.
Existing reader tests cover exact publication links and complete continuations.
These fixtures create synthetic database rows without ingestion or OCR.

The changes are implemented. Before the fix, the new tests had five failures
and seven passes. The failures reproduced repeated policy reads and inconsistent
text and eligibility. After the fix, all twelve checks pass.

The combined selection below passed 88 checks on November 5, 2026. It includes
reader, withdrawal, library authorization, MCP, and session-race regressions.

```sh
PYTHONPATH=src python -m pytest -q \
	tests/test_reader_validation.py tests/test_reader_content.py \
	tests/test_reader_updates.py tests/test_reader_personal.py \
	tests/test_content_withdrawal.py tests/test_library_auth.py \
	tests/test_mcp.py tests/test_reader_session_races.py
```

These checks establish behavior and remote-operation counts on synthetic fixtures.
They do not establish browser latency or resolve EPUB stalls. An authenticated
hosted comparison on the original workload remains separate from deployment.
