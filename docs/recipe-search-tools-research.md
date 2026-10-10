# Ready-made search tools for recipe lookup

Researched 2026-10-09 against first-party documentation. This is a bounded shortlist for a throwaway prototype, not an architecture decision or evidence that any engine meets recipe-match acceptance criteria. Nothing was installed, ingested, or run.

## Shortlist

### Typesense: structured recipe search with a direct cloud agent interface

Typesense searches named text fields and supports typo tolerance, exact phrases, word exclusion, numeric/facet filters, sorting, grouping, and pagination. Semantic and hybrid search combine keyword and vector retrieval with adjustable rank fusion; embeddings can be generated on the server, through remote APIs, or supplied externally. Keyword search needs no embedding model. [Search API](https://typesense.org/docs/30.2/api/search.html), [vector and hybrid search](https://typesense.org/docs/30.2/api/vector-search.html).

It supports self-hosting and Typesense Cloud. The official **Cloud** MCP server exposes collection search, including vector/hybrid queries, and document/schema administration; OAuth permissions include a search-only preset. This is not evidence of an official equivalent MCP server for self-hosted deployments, where an API wrapper remains an option. [Installation](https://typesense.org/docs/guide/install-typesense.html), [Cloud MCP](https://typesense.org/docs/guide/typesense-cloud/mcp-server.html).

There is already a source-linked reference implementation advertised over two million recipes with ingredient filtering. That demonstrates a reusable interface, not suitability or completeness for this library. [Recipe-search implementation](https://typesense.org/docs/guide/reference-implementations/recipe-search.html).

### Meilisearch: similar structured search, with an official MCP bridge

Meilisearch offers document indexes, configurable searchable attributes and ranking rules, typo tolerance, filters/facets/sorting, semantic vectors, and keyword/semantic hybrid search. Its official MCP repository advertises these search capabilities as well as index/document management; the bridge connects to an existing instance. [Official MCP repository](https://github.com/meilisearch/meilisearch-mcp), [integration overview](https://www.meilisearch.com/integrations/mcp).

Both self-hosting and Cloud are available. Hybrid search requires an embedder and supports a configurable semantic ratio; the documented remote-provider path uses an API key and a document template selecting the fields to embed. The keyword baseline can avoid embedding inference. A locally configured embedding service would involve local model execution and require this repository's isolation boundary. [Self-hosting](https://www.meilisearch.com/docs/resources/self_hosting/getting_started/quick_start), [hybrid setup](https://www.meilisearch.com/docs/capabilities/hybrid_search/getting_started).

Filters require indexing the corresponding attributes as filterable; they operate on supplied data, not independently verified recipe properties. [Filtering setup](https://www.meilisearch.com/docs/capabilities/filtering_sorting_faceting/getting_started).

### QMD: a local, agent-oriented search tool for prepared documents

QMD provides BM25 keyword, vector, and hybrid modes; its full pipeline adds query expansion and reranking. CLI, SDK, and built-in MCP support document search and retrieval. MCP offers stdio or Streamable HTTP, typed subqueries, metadata filters/discovery, and configurable candidate limits. Typed metadata comes from namespaced Markdown frontmatter. Its semantic pipeline uses local GGUF models through node-llama-cpp; keyword BM25 requires no model. [QMD repository and README](https://github.com/tobi/qmd).

This is the most direct fit for giving an agent searchable recipe documents and then letting it retrieve complete documents. It is a local tool, rather than a managed recipe-search service. Before experimenting with embeddings, query expansion, reranking, or model-loading MCP modes here, read [OCR resource isolation](ocr-resource-isolation.md) and use the Linux VM/cgroup admission boundary in `scripts/ocr_sandbox.py`; do not launch those paths natively. This is a project requirement, not a claim that QMD provides that boundary.

## Transformation still needed

Recommended prototype representation (inference from the tools' document interfaces): one searchable record/document per already available recipe, with stable recipe identity; title; authored ingredients, method and associated prose; book-edition/page source references; known recipe uses and supporting work; unresolved-content flags; and only source-supported filter attributes. JSON records suit Typesense/Meilisearch; Markdown with typed frontmatter suits QMD.

None of this replaces identifying complete recipes, recovering uncertain source content, resolving supporting work, or judging whether a recipe is a strong fit. Unknown dietary status, effort, time, or make-ahead suitability must remain unknown. A search-score cutoff does not establish that no suitable match exists. Keep prepared book content, indexes and raw prototype outputs outside Git.

## Minimal prototype comparison

Recommendation: try **Typesense or Meilisearch first**, plus QMD if agent-driven document exploration is the main question. Avoid building three production integrations. Use one small existing recipe subset and **5–10 seed requests**, including the three approved requests, an exact known recipe, a vocabulary mismatch, a concrete exclusion, and a difficult request. This is exploration, not the 30-request pilot benchmark or the later held-out acceptance evaluation.

1. Keep the current keyword shortlist as a baseline; compare one engine's keyword mode, its hybrid mode, and an agent that searches then reads full recipe evidence. Use identical source records and comparable candidate/result allowances.
2. Measure candidate coverage of independently identified strong fits separately from final selection. Name must-find recipes in advance. Record catalog omissions, candidate misses, selection misses and explicit-requirement violations separately.
3. Review top results and missed known recipes with the owner using strong-fit / acceptable-compromise / unsuitable / unknown judgments. Do not equate relevance with recipe-match suitability or claim complete coverage of the library.
4. Learn whether the limiting factor is retrieval, missing metadata/source content, supporting-work interpretation, or subjective judgment. That observation should drive the next decision ticket.

Expected practical difference (inference): Typesense/Meilisearch make structured filtering and a conventional search interface straightforward; QMD makes local multi-query document exploration and retrieval straightforward. Either can be called by an agent; an agent is an additional search strategy, not a replacement for measuring misses.
