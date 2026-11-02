# Cookbook retrieval and hosted Jev prototype

Throwaway experiment: can a larger source-backed cookbook catalog retrieve useful
candidates for a natural-language request such as “an easy, elegant dessert”?
Search alone supports 50 or 100 candidates without model calls. Hosted Jev ranking
remains optional, capped at 32 independent candidates or eight Choice candidates.

Start from the repository root:

```sh
.venv/bin/python src/cookbook/jev_rank.prototype.py --allow-hosted-jev
```

Open <http://localhost:8770/>. The owner explicitly authorized hosted Jev for
this prototype on 2026-10-05. The switch permits only HTTPS requests to the
TypeSafe Jev endpoint. Native OCR, local model execution, source ingestion and
publication writes remain disabled. Without the switch the server prepares a
real shortlist but performs no inference. The general OCR sandbox policy is
unchanged.

The server reads the private whole-book snapshot under
`/Users/rick/cookbook-mcp-data/poc/recipe-catalog-20-20261006/whole-book-model` and keeps response
caches and experiment records under
`/Users/rick/cookbook-mcp-data/poc/recipe-catalog-20-20261006/jev-runs`. Both locations stay outside
Git. Override with `--data` and `--output`. Credentials come from the server's
`TYPESAFE_API_KEY`, falling back to the existing private `trying-jev/.env`;
they are never sent to the browser.

## Optional decisions to compare

**Score is the proposed default**, because this experiment asks about degree of
fit to several stated preferences. Each candidate receives one independent
0–4 decision against the same descriptive rubric. A score of 3 is a position
on that rubric, not a 75% probability. This recommendation is a design choice,
not a conclusion from a judged evaluation set.

**Noul** asks whether the source supports recommending each candidate. Its
0–1 result is the probability of that yes/no decision; uncertainty is different
from moderate fit.

**Choice** selects one candidate from a shared set, with a “none suitable”
option. Its probability distribution is relative to that set and cannot be
compared across different shortlists. This prototype caps Choice at eight
candidates; Score and Noul accept up to 32.

Official semantics: [Score](https://docs.typesafe.ai/primitives/score),
[Noul](https://docs.typesafe.ai/primitives/noul),
[Choice](https://docs.typesafe.ai/primitives/choice). Requests pin
`jev-1.13.0`; returned model versions and typed decisions are inspectable.

## Retrieval and coverage

The recipe scope searches 2,632 proposed recipe records across 20 cataloged
books. All 538 prior records are retained, with 2,094 additional candidates.
The source snapshot holds 23 editions: the 20 recipe-catalog books plus the
retained Wine Bible, Flavor Bible, and image-only Passard source. The passage
scope searches 160,744 native text units; Passard has no substantive native text.
Candidate counts include authored supporting preparations and some variations.
They are not verified recipe totals or a completeness/recall measurement.

Retrieval uses SQLite FTS with an explicit small vocabulary expansion. The
optional candidate terms affect retrieval, while Jev receives the original
question. Jev can only rank the shortlist; rankings do not measure retrieval
recall. Passage mode drops isolated text units shorter than 40 characters,
which would otherwise admit headings as evidence without their context.

A recipe can span multiple source documents. The expansion retains 317 such
candidates. Publisher profiles require paired ingredient/method markup; title
continuations are joined and unrelated captions/essays/back matter are bounded
out. Source tree and body-text fidelity are validated independently of semantic
boundary accuracy.

Source packages contain the proposed source span, provenance, boundary state,
uninterpreted-image markers, available linked text, local parts and selected
preparation uses. Contextual links are not assumed to be required work.
Unresolved supporting work and unread quantities remain visible. A default
home-kitchen profile is explicit and overridden by the user's request.

## Practical limits

One ranking job runs at a time. Score and Noul evaluate up to four candidates
concurrently; Choice uses one request. Cancellation stops scheduling new calls
and retains results from the calls already in flight. Requests are cached by a
hash of the complete pinned-model request. The UI checks progress every 200 ms
and avoids rebuilding unchanged results. Retrieval, evaluation, and first-result
timings are recorded in private experiment files.
Oversized packages are rejected rather than silently truncated. Errors and
partial results are visible; no fallback scores or generated explanations are
invented. “Read source” shows what was supplied, with source locators.

Before treating this as a product ranking system, review recipe boundaries and
supporting work, populate the remaining recipe catalogs, and compare decisions
against human judgments on a fixed candidate set. The prototype currently
establishes that the retrieval → hosted decision → inspectable ranking flow
works.

## Expanding the candidate catalog

[scripts/recipe_catalog.prototype.py](../../scripts/recipe_catalog.prototype.py)
consumes a bounded native EPUB block capture and the prior candidate list. It
writes private candidate ranges, rejected headings and a coverage report. Run:

```sh
.venv/bin/python scripts/recipe_catalog.prototype.py \
  --blocks PRIVATE/source-blocks.json \
  --prior PRIVATE/prior-candidates.json \
  --output PRIVATE/new-catalog
```

This script has no OCR/model/network path. Native source capture and strict-schema
materialization drivers are preserved privately with the expanded snapshot.
Original EPUB bytes, experiment outputs and source-derived review samples stay
outside Git. The original 12-book snapshot remains untouched.
