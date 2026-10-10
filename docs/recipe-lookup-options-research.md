# Recipe lookup: evidence and options

Research date: 2026-10-09. Factual investigation for
[Research evidence for recipe retrieval and suitability evaluation](https://github.com/rickono/cookbook-mcp/issues/17),
within [Specify recipe lookup for a 20,000+ recipe library](https://github.com/rickono/cookbook-mcp/issues/14).

This report informs an implementation-ready spec; it does not select an architecture,
model, result count, operating budget, interpretation policy, or acceptance threshold.
Only documentation, original papers, source code, and relevant local prototype code
were read. No books, extracted passages, raw experiment records, credentials,
ingestion, OCR, inference, benchmarks, or paid API calls were used or published.

## Findings that matter to the map

1. **Finding good candidates and judging suitability are distinct obligations.**
   A reranker can reorder the candidates it receives, but cannot restore recipes
   absent from that set. TypeSafe's own reranking documentation explicitly separates
   fast search from this later step. Whether that step earns its place depends on
   the quality of the final matches, not its existence in a pipeline.
   [TypeSafe reranking](https://docs.typesafe.ai/cookbooks/rerank_typesafe).
2. **There is evidence for several viable approaches, but no measured winner for
   this library.** BEIR evaluated 10 retrieval systems across 18 datasets: BM25 was
   a robust baseline, while reranking and late interaction performed best on
   average at greater computational cost. This is evidence against assuming that
   a semantic model automatically solves a new domain.
   [BEIR paper](https://arxiv.org/abs/2104.08663).
3. **Recipe-specific retrieval benchmarks do not establish subjective request fit.**
   Recipe1M learns joint representations of ingredients, instructions, and food
   images for image–recipe retrieval. Its reported success does not demonstrate
   finding an “easy, elegant dessert” under a particular cook's constraints.
   [Recipe1M paper](https://openaccess.thecvf.com/content_cvpr_2017/html/Salvador_Learning_Cross-Modal_Embeddings_CVPR_2017_paper.html).
4. **20,000 recipes alone does not force approximate vector search.** Exact flat
   vector search exists. Representation length, vectors per recipe, request volume,
   evaluation work, and deployment hardware still determine feasibility; these
   have not been measured here.
   [Faiss index documentation](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes).
5. **Direct LLM selection deserves a fair comparison.** RankGPT establishes
   competitive LLM passage reranking on IR benchmarks, and LOFT establishes that
   long-context models can rival retrieval/RAG systems on some benchmark tasks.
   Neither establishes cost, quality, or supporting-work correctness for this
   cookbook library.
   [RankGPT](https://arxiv.org/abs/2304.09542),
   [LOFT](https://arxiv.org/abs/2406.13121).

## What the current prototype establishes

Local observations from `src/cookbook/jev_rank.prototype.py` and its adjacent
Markdown, read in the main working directory on the research date:

- The documentation reports 2,632 provisional recipe candidates across 20 books,
  not a verified count or a completeness measurement. This report did not inspect
  the private catalog or independently verify the counts.
- Candidate retrieval tokenizes the request, removes a stop list, applies a small
  literal expansion dictionary, and builds an OR query over SQLite FTS5. Title
  matches receive more BM25 weight than body matches. Requests are capped at
  40 unique retrieval terms and 100 returned candidates.
- `easy` gains “easy simple straightforward”; `dessert` gains dish-family words;
  `elegant` is removed without an expansion. The original request is preserved
  for subsequent evaluation. Consequently the lexical step has no explicit
  retrieval mechanism for elegance beyond incidental overlap in other terms.
- Optional hosted Jev is capped by this prototype at 32 independent candidates
  or eight Choice candidates. These are local prototype limits, not general
  provider limits. The code pins `jev-1.13.0` and rejects oversized packages.
- The documented package includes source references, parts, selected uses, linked
  text, unresolved supporting work, and source uncertainty. This is a more useful
  suitability input than a title alone, but its fidelity and coverage remain
  unmeasured in this investigation.

These observations show a flow and expose testable weaknesses. They do not prove
that 50–100 lexical hits contain enough good matches, that Jev improves selection,
or that increasing the catalog preserves either property.

## Candidate-generation and judgment options

### Lexical retrieval

SQLite FTS5 supports phrases, prefixes, proximity, column filters, Boolean queries,
custom tokenizers with synonym support, and BM25 with per-column weighting.
It does not infer culinary suitability from the query. Its `NOT` operator expresses
absence of matching text, not an application-level assertion that an ingredient
or required preparation is absent.
[SQLite FTS5](https://sqlite.org/fts5.html).

**Library hypothesis:** a strong lexical baseline could separately index title,
ingredient occurrences, instruction text, headnotes, and supporting-work text.
Controlled culinary aliases and dish-family expansion could recover vocabulary
mismatches without turning every request into one broad OR query. Rare named
ingredients and authored recipe names provide useful exact anchors. Conversely,
“simple” might describe one sauce rather than the complete dessert. Expanded
words are retrieval hints, never new user requirements or evidence of fit.

### Semantic retrieval

A bi-encoder embeds a request and indexed texts separately, permitting comparison
against precomputed document vectors. A cross-encoder jointly processes a
request–candidate pair to score relevance; Sentence Transformers documents the
trade-off between efficient retrieval and more expensive pairwise reranking.
[Retrieve and rerank documentation](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html).

**Library hypothesis:** dense retrieval could find dish or technique descriptions
that lack the request's words. Possible indexed views include the authored recipe,
its headnote, an evidence-linked retrieval description, and relevant supporting
work. A summary and a full recipe need not have the same retrieval behavior.
One vector for a long multipart recipe may obscure a decisive part; multiple
views increase index size and require aggregation back to the recipe identity.
“Related to dairy” is different from “contains no dairy”; similarity alone should
not be taken as a constraint verdict. Which model, text views, and aggregation
produce useful coverage requires library judgments.

Faiss documents exact `IndexFlatL2` and `IndexFlatIP`, each storing `4*d` bytes per
vector; cosine search can use normalized vectors with inner product. It also
documents non-exhaustive alternatives such as HNSW and IVF.
[Faiss indexes](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes).

**Illustrative arithmetic, not a measurement:** 20,000 float32 vectors of
dimension 1,536 occupy 122,880,000 bytes, about 117 MiB, before other storage and
runtime overhead. Four views per recipe multiply that vector storage by four.
An exact search performs comparisons with all indexed vectors, eliminating
approximate-neighbor misses but not semantic-ranking misses. This makes an exact
baseline plausible to investigate; it is no claim about latency or permission
to run a model on the host.

### Structured and derived attributes

Schema.org Recipe provides ingredients, instructions, yield, category, cuisine,
diet annotations, prep/cook/total time, and related fields. It is a useful
interoperability vocabulary, not evidence that any imported record contains
complete or accurate values.
[Schema.org Recipe](https://schema.org/Recipe).

**Library hypothesis:** authored quantities, techniques, equipment, timings, and
dependency structure could support filters and preference judgments. A derived
attribute should carry its derivation, source pointers, relevant scope, and
uncertainty. “Easy” and “elegant” should remain owner-calibrated judgments, even
if stable evidence such as active steps or make-ahead ability helps them.
Missing time is unknown time; missing ingredient text is not evidence of an
exclusion. Precomputed tags can reduce repeated reading but can also make a
systematically wrong assumption affect every request.

### Hybrid generation and missed-candidate recovery

Reciprocal rank fusion (RRF) combines ranked lists through reciprocal rank
contributions, avoiding the need to put their raw scores on a shared scale.
Its original TREC/LETOR experiments generally improved over individual rankings,
but included exceptions. The paper's constant of 60 is an experimental choice,
not a cookbook-specific optimum.
[Original RRF paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf).

**Library hypotheses to compare:** union lexical and semantic results; use RRF or
a tuned combination; reserve space for candidates unique to each route; retrieve
separately for major preference dimensions; vary representations or query wording;
increase the pool when too few candidates survive suitability checks. Deduplicate
by recipe identity without silently merging different authored variations or
book editions. A fusion cutoff can discard a uniquely good recipe, so inspect
route contributions and union coverage as well as final ordering.

HyDE generates a hypothetical relevant document, embeds it, and retrieves real
documents by similarity; the original paper reports zero-shot retrieval gains
on its evaluated tasks.
[HyDE paper](https://arxiv.org/abs/2212.10496).

**Library hypothesis:** query expansion or a hypothetical description could
bridge “elegant” to relevant culinary language. It could also insert an
unrequested dish style and hide other good options. Preserve the original
request, keep generated hints separate, and compare with unexpanded retrieval.
Generated text is never a source-backed recipe or proof of fit.

Recovery policy is a future decision: which routes to retry, how much additional
work is allowed, when clarification is warranted, and when to stop. “No suitable
candidate was found” is weaker than “the library contains none.” A valid recipe
absent from the catalog is an ingestion coverage failure; one indexed but not
retrieved is a retrieval failure; one retrieved but discarded is a judgment
failure. More reranking only addresses the last category.

### Suitability evaluation, Jev, and direct LLM selection

Possible later stages include deterministic checks over reliable fields, a
cross-encoder, a general LLM evaluating recipes individually, a general LLM
selecting from a shared pool, or a combination. RankGPT uses listwise permutation
generation and a sliding-window strategy to work within context limits; its
experiments concern passage relevance, not recipe usability.
[RankGPT paper](https://arxiv.org/html/2304.09542v3).

**Library hypothesis:** independent judgments permit explicit treatment of each
requirement and uncertainty, while shared-pool selection permits comparison and
variety among candidates. A relevance score is not automatically a validated
suitability probability. Rank order also cannot identify whether any recipe is
good enough. An approach must support rejection or abstention as well as ranking.

Jev's documented primitives support three different judgments:

- **Noul** returns the model's probability of yes for a specified binary question.
  It is not a measure of how much a recipe possesses a quality.
  [Noul](https://docs.typesafe.ai/primitives/noul).
- **Score** rates ordered descriptive levels; the returned score is the
  probability-weighted mean of their indices. Confidence summarizes distribution
  concentration, not guaranteed correctness. TypeSafe recommends separate
  questions for separate dimensions.
  [Score](https://docs.typesafe.ai/primitives/score).
- **Choice** selects among a defined set and returns option probabilities and
  confidence. It is a relative distribution over the supplied alternatives.
  [Choice](https://docs.typesafe.ai/primitives/choice).

TypeSafe's reranking example reports top-1 accuracy increasing from 5% to 18%
and top-10 from 38% to 62%, on 40 CLERC legal queries over 3,565 passages with
30-candidate BM25 pools. This is a first-party worked experiment with a narrow
sample, not independent evidence of cookbook improvement or current operating
performance. The report does not reuse its price or latency figures as guarantees.
[TypeSafe reranking example](https://docs.typesafe.ai/cookbooks/rerank_typesafe).

Jev need not only rerank: TypeSafe demonstrates Choice over 218 clause IDs with a
separate Noul existence check. The documentation states a maximum of 255 Choice
options and proposes two-pass selection beyond that. It warns that a normalized
Choice distribution still puts something first when no option answers the query.
[TypeSafe line-by-line search](https://docs.typesafe.ai/cookbooks/semantic_find).
This is evidence of a documented pattern, not validation that hierarchical Choice
would preserve coverage across 20,000 rich recipes.

**Library hypothesis:** if a general LLM receives a sufficiently good candidate
pool and already performs the necessary suitability checks, Jev or another
additional evaluator must demonstrate a useful incremental quality, cost, or
latency benefit. Typed numerical decisions alone do not supply the source-backed
evidence the receiving LLM needs. Evidence can come from preserved source facts
and locators, with separate validation of any selected or generated explanation.
No Jev role is established by this report.

## Recipe and request representations to investigate

The following are implications of this project's glossary and approved scope,
not findings that external benchmarks have validated:

- Retain the original **recipe request**, its concrete requirements, subjective
  preferences, relevant cook context, and unresolved ambiguity. The specification
  must distinguish stated facts from an inferred interpretation. Exact wording
  matters when an expansion or summary changes meaning.
- Preserve **recipe** identity and source locators across **book editions**.
  Separate authored text, **recipe parts**, **recipe formulations**, variations,
  and supporting **passages** rather than flattening their applicability.
- Follow a **recipe use** through the selected formulation/variation and whole
  or partial scope. **Supporting work** includes required preparations and
  techniques, plus unresolved requirements. A headnote backlink is not itself
  required work, and an optional garnish is not automatically mandatory.
- Avoid treating ingredient presence across all variations as presence in every
  possible preparation. Conversely, a required sauce can introduce an excluded
  ingredient absent from the main ingredient list. Repeated uses, shared batches,
  and ingredient allocations can affect effort; simply summing recipe times or
  counting every linked ingredient can misrepresent the actual preparation.
- Keep completeness/boundary state and unresolved content visible in retrieval
  representations and final judgment packages. The contract must decide when an
  unknown critical fact prevents a **recipe match**, versus permitting a result
  with a clear limitation. A confident model answer cannot complete missing text.
- A compact retrieval representation may point to a richer judgment package.
  Both need versions and links back to the same source-backed identity. Compression
  choices must be tested for loss of decisive ingredients or required work.

Synthetic failure examples for later judgments include a quick main recipe using
a required overnight preparation; a dairy-free main ingredient list using a
cream-based sauce; and an uncomplicated recipe with unresolved quantities.
These examples are invented, not extracted from source books.

## Context size and operational applicability

Lost in the Middle found sensitivity to the location of relevant information in
long inputs on multidocument QA and key-value tasks. RULER subsequently found
performance degradation with increasing context length/task complexity in the
models it tested. These historical results justify testing ordering and length;
they do not prove that a particular current model has the same failure rate.
[Lost in the Middle](https://arxiv.org/abs/2307.03172),
[RULER](https://arxiv.org/abs/2404.06654).

LOFT provides evidence in the other direction: long-context models can rival
retrieval/RAG on some tasks, while compositional reasoning and prompting still
matter. Whole-catalog selection therefore remains an empirical option, rather
than being rejected categorically because of library size.
[LOFT](https://arxiv.org/abs/2406.13121).

**Illustrative arithmetic:** at 1,000 input tokens per complete recipe package,
20,000 packages require 20 million tokens; 50 require 50,000. These are assumed
lengths, not observed library statistics. A title catalog would be much smaller
but omits the evidence needed to judge effort and exclusions. Any proposed model
needs verified input/output limits, measured package-size distributions including
supporting work, and a documented reject/split/compress policy. Byte caps are
different from tokenizer-based limits.

Other quantities to measure later: one-time attribute/embedding preparation and
updates; per-request query generation; candidate retrieval; reading/judging the
pool; retries and recovery; returned evidence size; concurrency and provider
rate limits; warm-cache versus cold-cache behavior. Independent pair evaluation
scales with evaluated candidates and their package lengths. Listwise evaluation
scales with supplied pool size and any repeated windows/passes. Neither can be
assigned a credible operating budget from recipe count alone. Hosting choices
must preserve this repository's execution-isolation policy.

## Evaluation design to inform later decisions

BEIR's evaluation code implements nDCG, MAP, Recall, and Precision at cutoffs,
plus optional metrics including MRR and top-k accuracy. These provide useful
building blocks; they do not specify this library's suitability judgments.
[BEIR evaluator source](https://github.com/beir-cellar/beir/blob/main/beir/retrieval/evaluation.py).

The following is a proposed measurement design, not owner-approved policy:

1. **Build judgments independently of one retriever.** Collect representative
   requests and owner-reviewed examples covering literal ingredients, dish
   families, subjective preferences, combinations, equipment/time constraints,
   sparse wording, ambiguous interpretation, variations, supporting work,
   incomplete content, and genuine absence. Pool candidates from different
   approaches, add deliberate hard negatives, and manually inspect broader
   portions for selected queries. If judgments are incomplete, label recall
   against known relevant items honestly; unjudged does not mean unsuitable.
   “No match exists” requires more inspection than no pooled hit.
2. **Measure candidate coverage before judgment.** For each request and pool size
   K, report known suitable recipes present, whether at least one strong match
   survives, and whether enough survive to produce the desired final count.
   Report Recall@K where the denominator is credible, route-specific gains,
   losses from hard filters and fusion cutoffs, and misses caused by catalog
   omissions. Separate approximate-vector neighbor recall from recipe relevance.
   A count of 100 retrieved records says nothing about any of these.
3. **Measure judgment on a fixed pool.** Give approaches the same packages and
   compare with owner judgments. Report acceptance precision, unsuitable recipes
   accepted, strong recipes rejected, graded ordering where appropriate, evidence
   correctness, uncertainty treatment, and supporting-work mistakes. Holding the
   pool fixed isolates whether Jev, a cross-encoder, or an LLM improves selection.
   Also compare direct LLM selection without an added evaluator.
4. **Measure the end-to-end result.** Report final precision and usefulness at the
   chosen count, requests successfully served, fewer-than-requested results,
   false “no match” outcomes, unsuitable output for genuine no-match requests,
   abstention rates, and clarification outcomes. An empty answer must not inflate
   precision; report result counts and abstention alongside it. Inspect diverse
   alternatives and duplicate versions, if variety becomes an owner requirement.
5. **Keep uncertainty distinct from preference fit.** Record clearly supported,
   contradicted, and unknown critical facts separately. If using a probability as
   a threshold, check its empirical reliability against reviewed examples;
   score magnitude or reported confidence alone is not calibration evidence.
   Measure quality versus the share of requests/recipes the system accepts.
6. **Test sensitivity and feasibility.** Vary pool size, query expansion, text
   views, supporting-work inclusion, ordering, long packages, and unknown values.
   Keep held-out requests for comparison after tuning. Report per-request and
   worst-slice results as well as averages, uncertainty from a small sample,
   elapsed-time distributions, tokens/calls, failures, and recovery cost. Model,
   index, catalog, rubric, and judgment versions must make comparisons interpretable.

Such evaluation must be separately authorized and use the repository's applicable
isolation controls. This factual research authorizes no experiment.

## Decisions still required from the owner and map

- What qualities count as strong matches, how requirements and preferences are
  interpreted, and when clarification is necessary.
- Which recipe/supporting-work facts must be available and what unknown critical
  facts permit, including whether incomplete candidates can be returned.
- Desired result count, tolerance for misses and false acceptance, abstention
  behavior, and whether diverse alternatives are part of quality.
- The representative judgment set, required evidence strength, sample coverage,
  and measurable acceptance thresholds.
- Latency/cost ceilings and operating environment, then the experiment scope that
  can compare approaches within them.
- Approach, models, route/pool sizes, recovery policy, derived-attribute contract,
  and any Jev role, based on those measurements rather than benchmark transfer.

The factual ticket can close with this asset. Its evidence does not settle any
of these policy or architecture choices.
