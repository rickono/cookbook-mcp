# Transcription reports

A scanned cookbook's text can contain misreads, especially in quantities. The agent
that uses the library is shown the original page, so it can spot a misread while
cooking from it. This loop lets it report the misread, and lets a later publication
fix it, without any agent writing into the library.

Decided 2026-10-20:

- **Authority:** a blind re-read decides. The reporting agent's reading is a claim,
  never a correction.
- **Storage:** reports go to a separate reports-only bucket with its own key. The
  library bucket and its runtime key stay read-only.
- **What the agent checks:** quantities marked unresolved or uncertain, and quantities
  that look implausible in context. A few zooms per recipe at most.

## 1. The serving agent checks and reports

`get_page` takes an optional `region`: `[left, top, right, bottom]` as fractions of
the page, each side at least 0.02. The server renders the page larger, up to
`ZOOM_EDGE` (2400 px), and returns only that box, at most `edge` pixels. Small print
and fraction glyphs become legible without returning a huge image.

For a scanned section, `read_section` returns `check_regions`: the crop quantity-review
boxes (`crop_confirmed`) and the unresolved items (`unresolved`) on its pages, each with
a `physical_page` and a `box` that `get_page` takes unchanged as `region`. The agent
checks the unresolved ones first instead of guessing a box.

If the zoom shows something different from the library text, the agent tells the
user what the page shows. It then calls `report_transcription_issue` once, with:

- `publication_id`, `book_id`, `source_id`, `physical_page`, and an optional
  `section_id`;
- `quoted_text`, the exact library text as served. It must appear, whitespace
  normalized, on that page or in that section. Otherwise the report is refused;
- `proposed_text`, what the page shows. It must differ from the quote;
- `kind`, one of `quantity`, `missing_text` or `other`;
- `region`, the zoom box, plus an optional `note`.

Text is bounded to 500 characters (note: 1000). The server fills `source_sha256` and
`format` from the publication, not from the agent. The report id is the sha256 of
the claim: the identifiers, kind, both texts and region, but not the note or time.
A repeated report therefore lands on the same key. The store write is a conditional
create, so a report is never overwritten. Each server process accepts at most 60
reports an hour; the subject allowlist remains the access boundary.

The tool is the only one not marked read-only (`readOnlyHint=false`,
`destructiveHint=false`, idempotent). Some clients ask the user to confirm such a
call. If the server has no reports store, the tool returns `reporting_unavailable`
and nothing else changes.

The server instructions tell the agent never to present its own reading as library
text.

Reports are stored as `reports/<publication_id>/<report_id>.json`.

## 2. The Mac decides each report blind

`scripts/triage_reports.py` runs on the Mac. It reads reports from a local reports
store (`--reports DIR`) or from the reports bucket with the Mac's own key
(`--reports-s3`, with the `REPORTS_*` env vars). For each new report:

1. It finds the source among the guarded `pdf_helper` registrations by
   `source_sha256`. It cuts the report's region from the original, or the whole page
   if the report has no region. The crop runs inside `scripts/ocr_sandbox.py`, and
   triage refuses to start unless `ocr_sandbox.py doctor` passes.
2. Haiku 5.5 reads the crop three times. The prompt is the benchmark's crop prompt, or
   its page prompt for a whole page. It contains neither the library text nor the
   proposed text.
3. Each reading votes `proposed`, `current` or neither. Matching is on tokens, with
   vulgar fractions spelled out, so `2 g` never matches inside `12 g`. A reading that
   contains both claims separately votes neither. Two of three votes decide. A failed
   reading counts against both claims:

| Votes | Outcome |
|---|---|
| proposed ≥ 2 | correction: `source_reviewed`, reviewer `{"kind": "agent", "id": "blind-reread:..."}` |
| current ≥ 2 | rejected |
| otherwise | owner queue (a human edge case) |

A decision is written once, to `decisions/<report_id>.json` under `--out` (default
`$COOKBOOK_DATA/report-triage`, outside Git), and is never redone.

A crop failure or a timed-out reading is not recorded, so the report is retried on
the next run. A provider content-filter refusal is a result: the report goes to the
owner queue and is not worked around. A usage limit stops the run.

Each run rebuilds `ledger.jsonl`, `owner-queue.jsonl` and `owner-queue.md` from
all decisions. Sources not registered with the helper, and DjVu sources, go to the
owner queue.

```sh
python3 scripts/triage_reports.py --reports-s3 --dry-run   # list pending reports
python3 scripts/triage_reports.py --reports-s3 --limit 20  # decide up to 20
```

## 3. The next publication applies corrections

`ledger.jsonl` is the correction ledger (`cookbook.ledger`); triage runs before this
change wrote it as `corrections.jsonl`, which is no longer read. It is unrelated to the
reader pipeline's `corrections.jsonl` (reader-vote corrections, `vote-corrections.jsonl`
in a candidate). Each row carries an
`id` (the report id), `decided_at`, the source digest and id, the physical page, an
optional section and region, `from_text`, `to_text`, the reviewer and the evidence
(crop hash, readings hash, votes). Rows are in decision order. A row binds to the
source digest and page, not to the publication the report was filed against, so a
report against an older publication still applies. The same correction decided again
from a later report is kept once, at its first decision.

`cookbook build --scanned-registry registry.json --ledger ledger.jsonl` applies
the rows for each scanned source, in order, after unresolved markers are in place.
Matching is whitespace-normalized and case-sensitive, and text touching an
`[unresolved …]` marker never matches, so a correction cannot fill a marker:

| `from_text` | Outcome |
|---|---|
| exactly once on the cited page | applied to the page and to every section part from that page that holds it |
| otherwise, exactly once in the cited section's text from that page | applied there (section-scoped) |
| nowhere in the cited scope (the cited section's text from that page, else the page) | stale; nothing changes |
| more than once in the cited scope, or `to_text` holds a marker | ambiguous; nothing changes, owner queue |

Chained corrections work because each row sees the text the earlier rows left. Every
unit a correction changed lists `{id, reviewer}` in `extraction.corrections`.

The source's rows are backed up beside its candidate as
`quality/scanned/<sha256>/ledger.jsonl`; the transcription summary lists the applied,
stale and ambiguous ids and the ledger digest. The publish gate re-imports the
candidate with the stored ledger and requires the same text and outcomes. It refuses
a stored row for another source digest, and an applied row whose page unit does not
record it or whose page lies outside the source. `build-report.json` in the build
directory (`scanned.build_report`, `scanned.read_build_report`) gives, for each
source, its Calibre ids, its page coverage (total, transcribed, blank, failed), and its
section and unresolved counts. It counts applied, stale and ambiguous corrections and
holds the owner queue of ambiguous ones. It is not published. The library changes only when a new publication is built and activated.
Earlier publications stay as they were.

Every build also records what it was built from, as `quality/build-inputs.json` in the
publication (`build-inputs.v1`). The record holds:

- the snapshot path and the sha256 of its `snapshot-manifest.json`;
- the OCR cache;
- the approved Calibre ids, in order;
- the forced OCR ids;
- for each imported scanned source, its digest, physical page count and the sha256 of
  its `candidate.json`.

## 4. The refresh command closes the loop

`scripts/refresh_library.py` runs steps 2 and 3 in one go. It runs on the Mac, by
hand, and nothing schedules it. One run:

1. reads the stored reports (`--reports DIR`, or `--reports-s3` with the Mac's
   reports key) and finds those without a decision;
2. if any are pending, runs `ocr_sandbox.py doctor`, and stops before triage if it
   fails;
3. blind-triages up to `--limit` (default 20) of them, exactly as in step 2. Reports
   over the limit stay pending for the next run;
4. regenerates `ledger.jsonl` from every decision;
5. compares the ledger's rows for each scanned source with the `ledger_sha256` the
   active publication's transcription summary records. If none differ, for example
   when there were no new decisions or only rejections, it publishes nothing and
   reports `"status": "unchanged"`;
6. otherwise rebuilds from the active publication's `quality/build-inputs.json`, with
   the new ledger. It uses the same snapshot, which must still match its recorded
   proof, the same approved selection and OCR choices, and the same candidates. The
   candidates are restored from the publication's `quality/scanned/<sha256>/`
   inventory and checked against the recorded digests. The build goes under `--work`
   (default `$COOKBOOK_DATA/refresh`);
7. publishes and activates the rebuild through the usual lifecycle and records it in
   `control/successful.json`, then prints a JSON report:
   - the new and previous publication ids;
   - the triage counts;
   - the applied, stale and ambiguous corrections;
   - the new and total owner-queue items, and the queue file.

A publication with no recorded build inputs is refused; build and publish it once
with `cookbook build`. A failed build or publish leaves the active publication
unchanged, and earlier publications are kept for rollback. Publishing uses the
Mac's publisher credential, which never goes to Fly. With `--s3`, the run uploads
with the library bucket's write key from the `S3_*` and `AWS_*` env, the same env as
`cookbook publish-s3`, with `COOKBOOK_AUDIENCE` set. It then waits for the
hosted readiness acknowledgement, signing in with `--browser-login` or using
`--token-file`, as `cookbook publish-s3` does.

```sh
uv run python scripts/refresh_library.py --reports DIR --store STORE --runtime RUNTIME
uv run python scripts/refresh_library.py --reports-s3 --s3 \
    --state-directory STATE --readiness-url https://HOST/readyz --browser-login
```

The owner queue is `owner-queue.md` under `--out`, a readable file the owner works
through. It holds every report the blind re-read did not settle, including
content-filter refusals, which are kept as they are. It also holds every accepted
correction that the active publication's build could not place unambiguously; the
refresh writes these to `ambiguous-corrections.jsonl` after each activation. Each item
shows:

- the report: id, publication, book, source, page, section, region, library text,
  proposed text and note;
- each blind reading, marked when the provider's filter refused it or the read
  failed;
- the reason.

Resolving an item stays a manual owner step.

## Not done yet

- **No scanned book is hosted yet.** The build imports a scanned PDF from a frozen
  `scanned-candidate.v1` candidate (`cookbook build --scanned-registry registry.json`);
  the gate accepts its text only through the transcription summary. A PDF without a
  registered candidate is refused unless it is named in `--force-ocr-books`, which
  keeps native page OCR and its assessments; a book cannot have both. The three production-transcribed books
  (#49) are built and published to a local store only; hosted activation waits for the
  owner. `get_page` renders with poppler's `pdftoppm`. The hosted image installs it;
  on the Mac it is not on `PATH`, so for local checks put Calibre's bundled copy
  (`/Applications/calibre.app/Contents/utils.app/Contents/MacOS`) on `PATH`.
- **The owner queue has no resolution tooling.** Items in `owner-queue.md` wait for
  the owner; nothing records an owner decision back into the ledger yet. The refresh
  runs only by hand.
- **Hosting is not configured.** See
  [hosted-runtime.md](hosted-runtime.md#transcription-reports--not-deployed). The
  bucket, its keys, the Fly secrets and the deploy each need the owner's approval.

For a mixed publication that also contains a native EPUB whole-book model, refresh
carries that verified model forward after rebuilding the scanned content. Native
reading targets, interpretation states and the model snapshot are retained. The
new publication reuses the existing keyword collection only after its recorded
model identity and complete keyword-document digest match. See
[mixed native and scanned publications](whole-book-typesense.md#mixed-native-and-scanned-publications).
