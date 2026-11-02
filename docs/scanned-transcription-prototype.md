# Local scanned-transcription prototype

This opt-in prototype connects immutable recognized evidence, candidate semantic
selections, source-backed review revisions, and derived EPUB reading copies.
It is separate from the existing publisher, extraction policy, runtime index,
and EPUB whole-book schema. Original editions remain authoritative.

The modules share the [canonical contract](scanned-transcription-contract.md):

- `cookbook.transcription` validates evidence and adapts saved Docling JSON,
  retaining original lines, geometry, nested picture text and table structure.
- `cookbook.transcription_boundaries` proposes candidate or unresolved selections
  and continuation links. See [boundary limitations](scanned-transcription-boundaries.md).
- `cookbook.transcription_review` retains digest-bound corrections and unresolved
  values in separate reading overlays. See [review states](scanned-transcription-review.md).
- `cookbook.transcription_export` generates deterministic EPUB bytes with raw
  evidence, page citations and provenance. See [export behavior](scanned-transcription-export.md).

## Run the connected trial

Read [resource isolation](ocr-resource-isolation.md) and run doctor first. The
command consumes a previously validated saved JSON snapshot; it performs no
recognition or new rendering. Book-derived processing still uses the isolated
launcher and fails closed before input reads on a native invocation.

```sh
python3 scripts/ocr_sandbox.py doctor
python3 scripts/ocr_sandbox.py run \
  --inputs /absolute/private/snapshot-inputs \
  --output /absolute/private/NEW_EMPTY_JOB_DIRECTORY \
  -- python /work/scripts/transcription_pipeline.py \
     --snapshot /inputs/snapshot.json --output /output/result
```

The nested result directory must not exist. The command validates all inputs and
constructs its outputs before creating it. Results include the unchanged snapshot,
boundary proposals, revision chain, reading overlay, review queue, script-free
HTML report, EPUB and a digest inventory. Outputs stay outside Git.

Optional `--boundaries /inputs/boundaries.json` uses separately prepared validated
proposals. `--revisions /inputs/revisions.json` accepts a digest-bound revision
list. `--reading review` explicitly displays review overlays; the default is
raw OCR. Both are unapproved reading copies. Neither the command nor a review
state grants acceptance or changes the existing publication gate.

## Verification and limits

Ninety-four synthetic tests cover geometry and hierarchy validation, line preservation,
continued instructions beside an independent recipe, immutable review chains,
stale evidence, unresolved values, escaping, deterministic EPUB packaging and
the connected reading path. Ruff checks and formatting pass.

The private four-page saved-output check retained all 186 recognized lines and
50 predicted table cells. The final boundary rules asserted no recipes on those
mixed layouts: unsupported memberships remain unresolved. This is a restrictive
mechanism prototype, not a recall improvement. It preserves the snapshot's given
line order rather than independently establishing correct instruction order.

Guarded command-level checks also produced a combined two-page candidate reading
copy, checked line coverage, ZIP/XML structure, provenance, internal targets and
output digests. They do not establish complete-book coverage, numeric correctness,
EPUBCheck certification, e-reader interoperability or EPUB parity. No new OCR or
model inference was needed. Existing VM/job resource ceilings remain unchanged.

Private evidence is under
`~/cookbook-mcp-data/poc/pdf-prototype-20261011/report.md`. That report preserves
superseded smoke checks and a corrected verification-script field-name error.
The [next evaluation protocol](scanned-transcription-export.md) requires frozen
settings, independently enrolled new editions, complete ownership/reading checks
and total review effort. Prior samples are development material.
