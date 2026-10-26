# Refusal blockers to complete publication of the six held books

Research for [Establish the refusal blockers to complete publication](https://github.com/rickono/cookbook-mcp/issues/56), within [Complete publication of the six held books](https://github.com/rickono/cookbook-mcp/issues/55). Investigated 2026-10-26 from the isolated `research/held-six-refusal-evidence` branch, based on `68961b3f9c160c64a38da12ce40d4e72214f91b6`.

## Finding

The current saved evidence still establishes **501 terminal-refusal pages across five held books**. None of those 501 has an independently established false-positive classification in the evidence checked. Repairing retained text cannot restore those pages under the map's mandatory refusal boundary. Complete, source-supported publication of all six therefore has no demonstrated permissible route from the present evidence. The destination remains unmet; this finding does not authorize partial publication or decide an owner's policy preference.

The sixth book, Modernist Cuisine Volume 5, has no refusal gap. That only removes this particular blocker; it does not establish quantity accuracy, recipe ownership, supporting-work completeness, or publication readiness.

## Scope and method

Read existing JSON control/status metadata and structural fields using Python's standard library; classified call diagnostics using the predicates in the pinned reader code; compared private record hashes without reproducing their values. No OCR, PDF/DjVu parsing, rendering, source-image viewing, model call, reconstruction, candidate generation, or production mutation occurred. Source text, response excerpts, raw records, images, and book-derived hashes are deliberately absent from this summary.

Private evidence roots used below:

- **Production**: `/Users/rick/cookbook-mcp-data/production/transcription/pipeline-claude-haiku-5-5-x3-fb-gpt-6-luna--low-a4/`.
- **Operations**: `/Users/rick/cookbook-mcp-data/production/transcription/ops53-20261021/`.
- **Investigation**: `/Users/rick/cookbook-mcp-data/production/transcription/held-six-investigation-20261022/`.
- **Registered manifest**: `/Users/rick/cookbook-mcp-data/batches/pdf-library-18-20261014/manifest.json`.

These files remain private and some operational files evolve. The dated supervision receipt is the accounting checkpoint, not a promise about later producer state. Private `Investigation/audit.json` and `Operations/refusal-safety-report.md` were pointers; counts below were checked against the owning saved records rather than copied from their narrative.

## Current refusal-safe accounting

The dated `Operations/supervision-20261026T122747Z.json` reports these book-level results. An independent walk of each registered physical-page universe, `Production/work/pages/bBOOK-pNNN.json`, and corresponding `work/failures/` sidecars reproduced them:

- **Il Viaggio di Vetri**: 312 physical pages; 287 retained; **25 refused**.
- **Modernist Cuisine Volume 3**: 399 pages; 394 retained; **5 refused**.
- **Modernist Cuisine Volume 5**: 420 pages; 420 retained; **0 refused**.
- **Thai Food**: 696 pages; 501 retained; **195 refused**.
- **The Professional Chef**: 956 pages; 735 retained; **221 refused**.
- **Café Boulud Cookbook**: 440 pages; 385 retained; **55 refused**.

Across the six: 3,223 pages, 2,722 retained, 501 refused, zero pending, zero blank, zero additional currently failed pages, and zero pages without a saved page record. Every refusal page matched its private quarantined-record digest in `Operations/refusal-quarantine-inventory.json` (501 of 501). Historical saved text can exist on a refused page; its existence does not make that text admissible.

At the same checkpoint the wider 15-book producer reports 7,494 pages: 6,861 retained, one blank, 632 failed, zero pending, and 11 completed candidates. `Operations/latest-progress-summary.json` instead retains an earlier 5,259-transcribed/6-failed/2,228-pending snapshot. It is stale for this question. Corpus-wide failed counts and historical quarantine counts must not replace the six-book page-level audit.

## What the refusal classifications mean

The classification is attached to **call records**, not arbitrary authored page text. The current predicate accepts a provider content-filter diagnostic, an explicit refusal to perform the task recorded by the reader, or an explicit refusal flag. Timeouts and empty responses alone do not establish a refusal. The pinned code also checks nested region/crop calls and historical failure sidecars. [Reader predicates](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/readers.py#L271-L291).

The current six-book records contain no flag-only refusal case:

- Vetri's 25 pages each have provider-filter evidence.
- Volume 3's five pages have explicit task-refusal diagnostics in crop calls. A page-only audit would miss them.
- Thai Food's 195 pages and Professional Chef's 221 pages each have provider-filter evidence; each book also has one such page with an explicit refusal diagnostic.
- Café Boulud has 54 provider-filter pages and one additional page with explicit task-refusal diagnostics. Crop refusal evidence is material here too.

These are positive saved refusal signals under the pinned classifier, rather than classifications inferred from missing content. The research did not reread response excerpts or source images to reassess their substantive meaning. It cannot prove that every possible detector false positive has been eliminated. It does establish that no checked evidence independently overturns any of the 501 current classifications.

The first refusal stops further page, region, and crop calls; resume excludes a previously refused page; historical fallback-derived text does not override the refusal. [Page execution](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/pipeline.py#L391-L451), [resume and progress](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/production.py#L147-L213).

## Detector mistakes and stale nonrefusal sidecars

A **historical detector defect is independently demonstrated in repository code**: the old expression treated broad first-person phrases and a copyright word as refusal signals; its replacement requires refusal to perform a task. Synthetic tests distinguish authored prose from task refusals without using book fixtures. [Detector correction](https://github.com/rickono/cookbook-mcp/commit/4d1769867ea15fcccee83b28bb6b22893b794977), [synthetic examples](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/tests/test_reader_bench.py#L16-L56), [historical-marker test](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/tests/test_reader_refusals.py#L114-L126).

The metadata supports a more precise reconciliation than the operations report's shorthand arithmetic:

- `Operations/refused-page-inventory.json` has 605 page-read-only entries. The 608-entry quarantine inventory removes three earlier entries (Café Boulud physical 16; Benu physical 8 and 226) and adds six crop-refusal pages (Volume 3 physical 110/148/180/200/234; Café Boulud physical 339). Thus **605 − 3 + 6 = 608**. Benu is outside this map.
- Café Boulud physical 16 retains an old `refusal:` marker but no provider-filter/current task-refusal signal. It is not in the current 55-page refusal set.
- Café Boulud physical 382 has a stale nonterminal sidecar with two historical attempts and six old detector errors; its later page record is retained. `Operations/recover-false-refusal.log` separately records the successful recovery and an old optimistic full-book summary. That receipt is a historical classification/recovery event, not permission to repeat recovery against a true refusal. The later refusal-safe accounting supersedes its zero-failure summary.
- Professional Chef physical 421 has a stale sidecar recording three empty responses and a later retained page record. This is a nonrefusal technical failure, not a terminal refusal or a current coverage gap.

The saved old-marker-only entries corroborate the detector problem, but a mismatch with the current regex alone is not independent proof of a particular page's authored meaning. This investigation deliberately did not inspect book-derived diagnostic excerpts. It therefore does not newly certify any source-level false-positive claim, and does not generalize the historical recovery to the current 501 pages.

To overturn an uncertain classification, the necessary evidence would be an independently saved, source-bound diagnostic/adjudication establishing that the original call was not actually refused, with record identity and relevant code version verified and with all page/region/crop/sidecar refusal evidence reconciled. Missing content, usefulness, an old zero-failure summary, later fallback success, or absence from an incomplete inventory cannot supply that proof. No new recovery or source read is authorized by this research.

## Frozen structure: known impact and limits

Five frozen original candidates exist under `Production/books/BOOK/candidate/`; their candidate digests still match the October 22 investigation, and all files named by each candidate manifest passed byte-digest checks. Professional Chef has no frozen candidate at the dated checkpoint. Checking candidate metadata is not admission or content approval.

**Vetri and Volume 3 originals are historical, contaminated candidates.** They advertise zero failed pages and retain legacy text/reviews from subsequently refused pages. Vetri has 25 such text-bearing pages, 115 text-bearing section parts, and 20 quantity-review rows; Volume 3 has five pages, 39 text-bearing section parts, and 10 quantity-review rows. Those old coverage summaries cannot support complete publication. The current writer rejects an assembly with refused-page text or reviews before writing a candidate. [Freeze guard](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/candidate.py#L160-L210).

Their historical structural metadata nevertheless locates known risk without exposing content:

- Vetri's refused pages intersect **18 sections**, including **five recipe sections**, eight passages, three chapters, and two frontmatter sections.
- Volume 3's refused pages intersect **eight sections**, including **five recipe sections**, a technique, a reference entry, and a chapter.
- Each has one saved reference from a different section into a gap-touching section. These links demonstrate dependency risk, but do not constitute a complete supporting-work graph.

Thai Food and Café Boulud originals were frozen with refusal-safe coverage: **501 retained/195 failed** and **385 retained/55 failed**, respectively. Checked exported pages, section parts, quantity reviews, and unresolved fragments contain no text from their refused pages. However, frozen section-page metadata names only **21 of Thai Food's 195** refused pages and **six of Café Boulud's 55** refused pages, all through passage sections. These are incomplete mappings, **not** evidence that only 21 or six recipes are affected, or that remaining recipes are safe. The assembler can emit a failed-page unresolved record with no section relationship. [Missing-page representation](https://github.com/rickono/cookbook-mcp/blob/68961b3f9c160c64a38da12ce40d4e72214f91b6/scripts/reader_bench/assemble.py#L278-L298).

Recipe continuation, recipe uses, required techniques, and transitive supporting work therefore remain incompletely accounted for. For Professional Chef that analysis cannot yet be grounded in a frozen candidate. A source-safe missing-page marker or a structurally valid import preserves an honest partial candidate; neither supplies the missing source-supported preparation.

## Consequences for the map

1. The refusal frontier remains an independent completeness blocker. No currently demonstrated detector correction recovers any of the 501 current refusal pages.
2. Fixing fractions, quantity associations, duplicates, and ownership on retained pages would leave the refusal gaps intact. A complete all-six publication must not be inferred from that work.
3. Whole-book completeness and supporting-work checks are not available from the present section links. Existing structure supplies risk locations and some dependency evidence, not an exhaustive affected-recipe inventory.
4. Ordinary source illegibility is separate unresolved content. This metadata-only audit neither revalidated scan legibility nor reclassified it as refusal. It provides no new source-supported reading of blurred quantities.
5. Under the map's present boundary, retries, alternate prompts/models/providers, crops, manual reconstruction, historical refused text, and source substitution cannot supply a route around true refusals. A factual blocker is the result to carry forward; the all-six destination remains unmet.

The research leaves all holds, admitted derivatives, originals, workers, locks, scheduler, selections, credentials, resource ceilings, and publication state unchanged. It resolves the factual research question only; the human decision tickets and implementation remain open.
