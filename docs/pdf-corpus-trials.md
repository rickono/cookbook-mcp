# Private PDF corpus trials

These scripts collect research evidence and candidate text. They do not modify
the extraction policy, approve OCR, or publish books. Source files, specifications,
reference transcriptions, images and results belong outside Git.

Read [OCR resource isolation](ocr-resource-isolation.md) before running any trial.
All parsing, rendering and recognition requires `scripts/ocr_sandbox.py`; native
execution fails closed. Each job mounts only the needed private inputs. Use a new
output directory and run jobs sequentially.

## Survey

`scripts/pdf_corpus_trial.py survey /inputs/book.pdf` collects whole-file native
text coverage and font metadata. It renders physical pages at 25%, 50% and 75%
of the file, with a 2300-pixel long edge, and saves bounding-box native text.
Image metadata is explicitly sample-only: unsampled page image lists are null,
not empty. Text coverage is not a scan-quality or correctness rating.

## Matched candidates

`scripts/pdf_candidate_trial.py /inputs/spec.json` compares native text with
default and best-English Tesseract on a frozen page image, plus manual regions
with and without grayscale autocontrast. Whole pages use PSM 3; regions default
to PSM 6. Original images and every candidate remain available.

The private input directory contains:

- `page.jpg`: a complete page render with at most 2500 pixels per side.
- `native.txt`: the unchanged page text being compared.
- `tessdata_best/eng.traineddata`: locally staged English model weights.
- `spec.json`: book ID, physical page, source SHA-256, image filename and SHA-256,
  native text SHA-256, normalized region boxes, and pixel-grounded reference probes.

Each region has `box: [left, top, right, bottom]` in the range 0 to 1. Each probe
has `kind` and `text`. Freeze references before recognition; leave unreadable
source content unresolved. Keep reference changes as separate experiments.

The scorer preserves numeric boundaries and punctuation while normalizing case,
whitespace and Unicode fractions. Snippet presence cannot establish complete
reading order, table associations, or whole-page accuracy. The triage helper
reports suspicious quantity forms and numeric-token disagreements; even perfect
candidate agreement never produces acceptance.

## Direct regional renders

`scripts/pdf_region_trial.py /inputs/spec.json` renders complete PDF layers into
bounded PNG regions at two sampling densities, then compares default and best
English recognition. The private directory contains `book.pdf`, the model weights,
and a spec with `page`, `source_sha256`, and `regions`. Each region has a normalized
box and a list of reference strings in `probes`.

Equivalent whole-page long edges are 2300 and 4600 pixels, but actual output
regions must remain at most 2500 pixels wide/high. Memory, process, CPU, file-size
and deadline ceilings remain unchanged. Nonzero or unverified PDF page rotation
is refused because those normalized coordinates need separate handling. Visually
inspect crop boundaries before interpreting a missing-text result.

## Invocation and validation

```sh
python3 scripts/ocr_sandbox.py doctor
python3 scripts/ocr_sandbox.py run \
  --inputs /absolute/private/page-inputs \
  --output /absolute/private/new-result \
  -- python /work/scripts/pdf_candidate_trial.py /inputs/spec.json

python3 scripts/ocr_sandbox.py run \
  --output /absolute/private/new-test-result \
  -- python -m pytest -q -p no:cacheprovider --basetemp=/tmp/pytest \
     tests/test_pdf_candidate_trial.py
```

The September 13 private corpus report is under
`~/cookbook-mcp-data/poc/pdf-corpus-20260913/report.md`. It includes the 19-file
survey, frozen cross-book comparison, diagnostic follow-ups, limitations, engine
and model identities, and unaccepted correction proposals. Research observations
do not transfer approval to existing publications or review records.
