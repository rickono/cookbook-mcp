# Typesense recipe-search prototype

Throwaway exploration for [Try Typesense for source-backed recipe lookup](https://github.com/rickono/cookbook-mcp/issues/23): can a ready-made keyword engine improve candidate retrieval and expose misses on the existing source-backed snapshot?

From this worktree, run one command:

```sh
python3 src/cookbook/typesense_search.prototype.py
```

Open <http://127.0.0.1:8772/>. Python 3.9+ and an official Typesense 30.2 binary are used. On first run the script downloads the binary to the private output directory, without installing a global service. The page starts and owns its loopback-only engine on ports 8109/8110; Ctrl-C stops both. Each run builds a fresh scratch index. Occupied ports are refused instead of reusing someone else's engine. The administration key is generated locally, retained in a private mode-0600 configuration file and never sent to the page.

Defaults read `/Users/rick/cookbook-mcp-data/poc/recipe-catalog-20-20261006/whole-book-model` and write beneath `~/cookbook-mcp-data/poc/typesense-prototype-20261009`. Override with `--data`, `--output`, `--port`, `--engine-port` and `--peer-port`. Source text, credentials, indexes, owner judgments and raw trial output remain outside Git. The existing snapshot is opened read-only; the prototype performs no EPUB/PDF ingestion or OCR.

## What to try

- Compare the approved dessert, mushroom dinner and weeknight chicken requests.
- Try an exact preparation name and a deliberately misspelled ingredient.
- Toggle keyword expansion, title/body weighting, typo tolerance and book scope.
- Vary Typesense's token-dropping recovery target: stop at the first hit versus looking for 10, 100 or 250 keyword hits. It is a target, not a guarantee or a strict candidate cap. “Require every keyword” disables token dropping and may return nothing for an expanded bag of alternatives.
- Read the same full source package from either column. Source locators, candidate boundary state, unread images, selected recipe uses and linked context remain visible. Linked context is not assumed to be required supporting work.
- Find a known recipe title directly in the full catalog and mark it must-find for the current request. Compare its rank or absence at the displayed result allowance. This title finder is independent of the two shortlists, but remains limited to the same provisional catalog.
- Record strong-fit / acceptable-compromise / unsuitable judgments, or leave fit unjudged when evidence is insufficient. Flag uncertainty independently of the fit judgment. These are owner inputs, not model-generated grades. They persist privately by snapshot, original request and selected book scope, so changing ranking settings does not erase them. Clear a judgment using “Your judgment…” and remove must-find flags with the coverage controls.

Both columns use the displayed keyword list and the same source recipe body. With keyword expansion enabled and default title weighting, the SQLite OR/BM25 baseline retains the prior prototype's retrieval policy. With expansion disabled it retains literal preference/dish terms as well as the remaining content words. Typesense uses its own text matching, typo handling and token-dropping policy. Their scores are not comparable, and their keyword match sets need not be identical. Client round-trip timings are exploratory single-request observations; they are not production latency benchmarks.

Long requests have a 1.5-second Typesense search cutoff, reported if triggered; this is an engine early-return control, not an OCR/model isolation mechanism. The original request is preserved separately from keyword retrieval hints. Dietary suitability, effort, make-ahead ability and other subjective or concrete requirements are not judged by this prototype, and no inferred dietary/time filters are supplied.

## Execution boundary and limits

This version is **keyword-only**: no embedding/vector fields, model configuration, model downloads, inference or paid service calls. Native Typesense is used only for keyword indexing/search. Semantic or hybrid search requires a separately protected model path under `scripts/ocr_sandbox.py` and the existing Linux VM/cgroup boundary; the prototype offers no switch or fallback to native auto-embeddings. Docker was unavailable during this trial, so semantic retrieval was not evaluated.

The source snapshot contains 2,632 provisional candidates across 20 books, including supporting preparations and some variations. It is not a verified recipe total or a complete catalog. Must-find tracking measures known items in the selected output allowance, not full-library recall. Empty keyword results do not establish absence of suitable recipes. Building and running this tool does not establish the provisional acceptance thresholds discussed in [Define representative requests and recipe-lookup acceptance criteria](https://github.com/rickono/cookbook-mcp/issues/15).

Official implementation references: [installation and binaries](https://typesense.org/docs/guide/install-typesense.html), [search parameters](https://typesense.org/docs/30.2/api/search.html), [vector/hybrid search](https://typesense.org/docs/30.2/api/vector-search.html). The source/package reader and baseline policy were adapted from the existing local `jev_rank.prototype.py`; this trial contains none of its hosted-model execution path.

## Frozen retrieval comparison

With the server running, execute:

```sh
python3 src/cookbook/typesense_evaluation.prototype.py
```

Open <http://127.0.0.1:8772/evaluation>. The runner reads the private `evaluation/cases.json` beneath the default output directory. Use `--cases PATH`, `--output PATH` and `--url http://127.0.0.1:PORT` to override these. A custom output directory must be the running server's output directory plus `/evaluation` for the page to load it.

Case selection is deliberately a separate manual step. Browse catalog titles independently of either ranked shortlist, inspect actual source ingredients/instructions and locators, and freeze the positive anchors before comparing engines. The private manifest contains `schema_version`, `snapshot`, `selection_method`, `anchor_policy`, and `cases`. Each case has `id`, `query`, `criteria`, `book_id` (0 for all books), `book_title`, and `anchors`. Each anchor has the recipe `id`, `title`, `book`, `book_id`, source-review `reason`, `evidence` (term/excerpt pairs), `citations`, `source_state`, `uninterpreted_images`, and SHA-256 of the UTF-8 selected source text as `source_sha256`. The runner verifies the snapshot, frozen source hashes and book scope before searching. It never selects anchors from engine results or writes owner fit grades. This local pool is not shipped in Git because it contains source evidence.

Eight configurations are compared sequentially at allowances of 10 and 25: SQLite literal/expanded, Typesense literal/expanded, and Typesense literal with first-hit recovery, every-term matching, title weight 10, or typo tolerance disabled. Other settings remain fixed at title weight 5, recovery target 100, typo tolerance enabled and the same recipe bodies. Each allowance is searched separately. The output stores original requests, keywords, effective parameters, returned identities/ranks, cutoffs, timings and every anchor omission. Both missing-anchor counts and checks with any miss are reported; finding one anchor does not cancel another's miss.

Immutable `run-*.json` observations and an atomic `latest.json` stay private. Optional agent notes in `source-reviews.json` are attached only to the same case-file hash; they distinguish supported concrete facts, mismatches, scope ambiguity, source spillover and incomplete content. They do not become owner judgments. The evidence page lets the owner read full sources, record fit and uncertainty, inspect misses and open the selected settings in free-play search.

The first exploratory pool used ten concrete requests plus a book-scope control, 16 unique anchor recipes and 19 anchor occurrences. The correctly spelled/misspelled pair and book control repeat some anchors. Named-dish, ingredient-combination and vocabulary checks were selected from the catalog; they are neither held out nor a representative owner-request sample. Before source grading, the cocktail request was clarified to explicitly require lemon juice, matching its criterion. Anchor identities were unchanged and the comparison was rerun; the earlier wording and run remain private.

Observed known-anchor misses:

| Configuration | First 10 | First 25 |
| --- | ---: | ---: |
| SQLite expanded | 7 / 19 | 7 / 19 |
| SQLite literal | 5 / 19 | 3 / 19 |
| Typesense expanded | 6 / 19 | 3 / 19 |
| Typesense literal | 4 / 19 | 0 / 19 |
| Typesense literal, first-hit recovery | 7 / 19 | 5 / 19 |
| Typesense literal, every term | 7 / 19 | 5 / 19 |
| Typesense literal, title weight 10 | 4 / 19 | 0 / 19 |
| Typesense literal, no typos | 4 / 19 | 1 / 19 |

No engine search cutoff was reported. Literal Typesense with recovery target 100 retained this pool at 25; increasing title weight from 5 to 10 did not improve these miss counts. Requiring every term or stopping after the first hit lost anchors. Several unexpected results were traced to chapter material included in recipe spans, comparisons in headnotes, ingredient substitutions, or recipe parts/uses with a different scope. Source audits of the 16 anchors and selected unexpected hits cover 56 unique source records, with 64 case-specific notes. This selective audit does not estimate precision. It also found source-supported alternatives outside the frozen pool, confirming that unlisted results cannot be treated as irrelevant automatically.

This supports trying literal Typesense as a candidate supplier with a larger allowance. It does not establish suitability, complete recall, a production setting, or acceptance-gate compliance. The next useful experiment is to correct or isolate audited source-boundary spillover, then compare on fresh independently pooled requests before adding semantic retrieval.
