# Reader benchmark

Scanned cookbooks are read by a small vision model, sampled three times. On
2026-10-20 the chosen reader was **Claude Haiku 5.5 x3**
(`claude:claude-haiku-5-5`), with **Luna low as its page-read fallback**
(`--fallback codex:gpt-6-luna@low`). The fallback reads only pages whose
Haiku page read is blocked by Anthropic's output filter; see
[Fallback reader](#fallback-reader). This page describes how to run a new small model
through the same pipeline and grading, and how to compare it with that baseline.

The kit lives in `scripts/reader_bench/`. Its inputs, outputs and grades stay
under `$COOKBOOK_DATA` (default `~/cookbook-mcp-data`) and never go into Git.

## What is frozen

The model is the only thing a re-benchmark changes. Everything below stays the
same.

- **Books:** b6 *Tu Casa Mi Casa* (233 pages), b79 *Mugaritz* (247 pages) and
  b81 *The Family Meal* (392 pages). Their page images, references and the
  evaluation template are in
  `$COOKBOOK_DATA/batches/model-comparison-three-books-20261015` (EXP).
- **Pipeline** (`pipeline.py`):
  - sample #1 reads the whole page;
  - three samples box the quantity regions, and a box is kept only when at
    least two samples agree;
  - each box is cut by the guarded `pdf_helper` crop and read by all three
    samples;
  - a page quantity is changed only on a strict majority of crop readings, and
    a missing reading counts against the change.
- **Prompts:** the page, region and crop prompts are verbatim copies of the
  2026-10-19 run.
- **Assembly** (`assemble.py`, assembler v4): one text-only sectioning call per
  page by sample #1, then deterministic candidate files.
- **Grading:** one Sol evaluation per book. The task points the evaluator at a
  brief built from the same template the earlier graded cells used.
- **Pilot:** 39 reference pages (`pilot-pages.txt`), scored against the
  references with no model grader.

`bench.py verify` checks the frozen part against the baseline without calling a
model. It re-votes and re-patches all 859 baseline pages from their recorded
readings, reassembles the three books offline, and requires these to match
`baseline.json`:

- the page texts and corrections;
- the hash of every candidate file;
- the pilot score;
- the costs.

Run it after any change to the kit. If it fails, the new numbers can't be
compared with the baseline.

## Running a new model

The reader spec is `backend:model[@effort]`, for example
`claude:claude-haiku-6` or `codex:gpt-7-luna@low`.

1. **Add a list price.** Add a row to `scripts/reader_bench/prices.json`, in USD
   per million tokens: input, cache_write, cache_read, output, and
   `max_prompt_tokens` if the price changes above a prompt size. `costs.py`
   refuses to price a reader that has no row.
2. **Read the OCR isolation doc.** See
   [ocr-resource-isolation.md](ocr-resource-isolation.md). `pilot` and `full`
   refuse to start unless `scripts/ocr_sandbox.py doctor` passes. Crops go only
   through the guarded helper. Don't relax either check.
3. Run the commands below in order. Every command resumes from its cache under
   `$COOKBOOK_DATA/batches/reader-bench/pipeline-<model>[--effort]-x3/`.

```sh
B=scripts/reader_bench/bench.py; R=claude:claude-haiku-6
python3 $B verify            # the kit still reproduces the baseline
python3 $B smoke    $R       # one page read: proves the CLI wiring and pricing
python3 $B pilot    $R       # 39 reference pages (~270 calls), prints the pilot score
python3 $B compare  $R       # stop here if the pilot is clearly worse than the baseline
python3 $B full     $R       # all 872 pages (~5,800 calls); one retry pass for failures
python3 $B assemble $R       # ~870 sectioning calls, then candidate files under EXP/runs/<config>/
python3 $B prompts  $R       # writes three evaluation briefs, prints three delegate_task calls
```

4. **Grade.** Issue each printed `mcp__t3-code__delegate_task` call as printed:
   - target `codex` / `gpt-6.1-sol`, reasoning effort medium;
   - async;
   - role review;
   - one call per book.

   Each evaluator writes its evaluation under
   `EXP/evaluation/candidates/<config>/books/<b>/`, including the
   `bench-summary.json` that `compare` reads.
5. **Compare.** Run `python3 $B compare $R` again. It prints the table and
   writes `compare.json` next to the work directory.

The config id is `pipeline-<model>[--effort]-x3-a4`, for example
`pipeline-claude-haiku-6-x3-a4`.

Once a book has been graded, `assemble` and `prompts` refuse to touch its
candidate files or brief. To try again, use a new config.

## Baseline

The baseline is `scripts/reader_bench/baseline.json`. Its work files are in
`$COOKBOOK_DATA/batches/paid-reader-pilot-20261019/full-haiku`.

**Pilot (39 reference pages)**

| | Haiku 5.5 x3 | Luna low x3 (not chosen) |
|---|---|---|
| Items correct | 528/578 | 517/578 |
| Quantity lines correct | 292/293 | 287/293 |

**Full three-book run**

| | Haiku 5.5 x3 | Luna low x3 (not chosen) |
|---|---|---|
| Pages transcribed | 859/872 | 837/872 |
| Page list cost | $2.16 | $2.46 |
| Sectioning list cost | $0.83 | — |
| Median call time | 2.8 s | 60 s |
| Median page time | 16 s | 243 s |

**Sol-medium grades for Haiku**

| Book | Fidelity | Retrieval (hit@1, hit@5, MRR) | Structure (errors / warnings / unknowns) |
|---|---|---|---|
| b6 | 220/221 | 4/8, 8/8, .729 | 2 / 4 / 5 |
| b79 | 224/242 | 6/9, 7/9, .722 | 8 / 5 / 4 |
| b81 | 143/146 | 8/10, 10/10, .875 | 2 / 4 / 3 |

Haiku lost 13 pages to Anthropic's output content filter. Those pages are
recorded as failed, not worked around.

For a new model to win, it must at least match the pilot and the fidelity
grades, at a comparable cost and run time.

## Caveats

- **The assembler is not blind.** Its join rules and quantity-review records
  were revised after evaluator feedback on earlier cells. The evaluation brief
  says so. A new model is still compared on equal terms because it gets the
  same assembler.
- **Baseline grades are for assembler v3 (cell `-a3`).** A new model is graded
  on v4 output. v4 changes only quantity-review and unresolved metadata, and
  `sections.jsonl` is byte-identical, so fidelity and retrieval compare
  directly. Structural counts may differ slightly. Regrading the baseline at v4
  costs three Sol evaluations.
- **Grades come from one fallible evaluator.** Sol-medium grades against
  references made by an Opus reviewer, not against human truth. Treat a
  difference of a few items as noise.
- **Costs are list prices computed from recorded tokens.** Claude reports its
  own cost, which is higher (`reported_usd`). For a Codex reader, check the
  subscription meter by hand, because Codex usage is metered differently from
  list price.
- **OpenCode readers are untested.** `readers.py` has an `opencode` backend
  with a separate data directory per worker. The free models were blocked from
  this IP on 2026-10-19, so it has never run end to end.
- **Content filters are not worked around within a provider.** There is no
  chunking, cropping or paraphrasing to get a refused page past a filter. A
  page the primary reader's provider refuses is either lost or, with
  `--fallback`, read by a different provider, and `compare` reports both
  counts.

## Fallback reader

Anthropic's output filter blocks the Haiku page read on some pages of long
continuous prose, apparently because it treats them as verbatim reproduction of
copyrighted text. In the baseline it blocked 13 pages of *The Family Meal*:
the opening essays (pages 11–27), the basic-recipes introduction (44) and
the glossary (382–383). Any Claude reader is likely to lose the same kind of
page in other books.

With `--fallback READER2`, the pipeline gives a refused page read to READER2,
once. It does this only when the failure is the filter's refusal, never for a
timeout or usage limit. Everything else on that page stays with the primary
reader:

- region boxes;
- crop votes;
- the quantity patch;
- sectioning.

The page record keeps both calls, and the fallback call is marked
`"fallback_for": "output filter"`.

The production config is
`pipeline-claude-haiku-5-5-x3-fb-gpt-6-luna--low-a4`. Its work dir was seeded
from the baseline's 859 pages, and on 2026-10-20 Luna read the 13 refused
pages:

- **Pages:** 872/872 transcribed.
- **Cost:** about $0.03 more at list price; check the Codex meter for the 13
  Luna calls.
- **Assembly:** b6 and b79 are byte-identical to the baseline.
- **b81:** the essays, basic-recipes introduction and glossary sections now
  carry text, and the 13 "page transcription failed" entries are gone.

The fallback text is a single sample. Prose is not voted on, so a misread
stays. For example, the glossary has "ACH IOTE PASTE" where an earlier Luna
reading had "ACHIOTE PASTE". Across the 13 pages, word-level agreement with
that independent earlier Luna run was 0.99–1.00. Quantities on these pages are
still voted by the three Haiku crop readings.

A fallback run is a separate config (`pipeline-<model>-x3-fb-<model2>-a4`) with
its own work dir, so it never mixes with plain runs. Grade a new reader
without a fallback, so that the pages it loses to filters stay visible. Add the
fallback only for a production run.

## Production runs

`production.py` runs the production config over any book registered with the
guarded helper (`$COOKBOOK_DATA/batches/pdf-library-18-20261014/manifest.json`),
covering pages 1..N rather than the frozen benchmark page list. It never reads
or writes EXP, the benchmark work dirs or `baseline.json`. Its output goes to
`$COOKBOOK_DATA/production/transcription/<config>/`.

- `production.py run BOOK... | --all` refuses to start unless
  `ocr_sandbox.py doctor` passes. It renders page images through the helper,
  20 pages per job, and checks them against the registered source hash. Then it
  runs the frozen pipeline page by page. A rerun resumes: finished pages are
  never paid for twice. A page whose page read fails is not cached as done.
  Its calls go to `work/failures/` so that their cost is counted, and the next
  pass retries it.
- A page is **blank** only with evidence: two passes in which every page read
  came back empty. Any other page without text is **failed**.
- `production.py assemble BOOK...` runs sectioning and assembler v4 into
  `books/<b>/assembly/`. It then writes the book's `scanned-candidate.v1` to
  `books/<b>/candidate/` (`candidate.py`). The candidate holds:
  - `candidate.json`, with its freeze identity: reader samples, fallback,
    prompt and code hashes, and coverage;
  - one row per physical page in `pages.jsonl`;
  - `sections.jsonl`;
  - `quantity-review.jsonl`;
  - `unresolved.jsonl`, where each item has a code, a crop box and a review
    link;
  - `vote-corrections.jsonl`.

  The command refuses a book that still has failed pages unless you pass
  `--allow-missing`. With `--offline`, reassembly makes no model calls and
  reproduces the same bytes.
- `production.py seed BOOK... [--from WORK]` copies books that another work dir
  already read with the production config into the production work area, so they
  are not paid for twice. By default it copies from the benchmark cell. It copies
  their page records, label caches and failure sidecars, and their page images from
  the frozen benchmark inputs. It refuses a work dir read by another reader config,
  and page records read from other page images. It never overwrites production work
  and changes nothing in the source; the manifest records each seed. Then
  `assemble --offline` writes the candidates without model calls.
- `production.py status [BOOK...]` reports, for each book, the pages
  transcribed, blank, failed and pending, and the list-price cost so far.
