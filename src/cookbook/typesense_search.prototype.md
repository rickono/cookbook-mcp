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
