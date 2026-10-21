# Recipe composition prototypes

Question: does a complete method, a parent dish with linked recipes, or a
preparation workspace make an ambitious composed dish easier to understand?
This round follows [recipe-app research](../../docs/recipe-composition-research.md).

Run `python3 src/cookbook/recipe_viewer.prototype.py`, then open:

<http://127.0.0.1:8766/recipe-compare.prototype?variant=B&recipe=emp>

- **A — The complete recipe.** All thirteen sections in one document, ordered
  with prerequisite recipes before their consumers. Three chapters, jump links,
  and a compact method outline. Ordinary text stays continuous.
- **B — A dish of recipes.** Four parent actions: foundations, carrots/grains,
  sauce, then assembly. Named preparations show needed quantities and open
  inside the same surface. Nested references have a back stack restoring the
  parent disclosure state, focus and scroll position. No HTML modal.
- **C — The prep plan.** A grouped preparation index beside one recipe at a
  time; below 560px it becomes a select control. Needed quantity, source yield,
  prerequisites, prep and method stay together.

All three use the same uncomplicated method for the synthetic simple recipe.
It needs no component navigation. Mise en place uses source-supported fixture
prep tasks. Contextual ingredient amounts remain source-batch amounts, labeled
as such for EMP; there is no scaling. Source references remain available.

The EMP source fixture stays outside Git, at the path documented in
`recipe_viewer.prototype.md`. Sequence and summaries are prototype suggestions,
not the original book's ordering or an optimized service schedule. Oven conflicts
and overnight work are surfaced. No holding durations are invented.

Use the bottom bar or left/right arrows to compare; recipe and variant are URL
parameters. In-memory reading state is logged to the console. Escape returns
from a supporting preparation. No checkoffs, progress tracking, persisted state,
live model calls or production changes.

The previous A/B/C round (including B's compact toggle) is preserved as
`recipe_compare.v1.prototype.html`. The earlier `/recipe.prototype` still exists.

Browser checks: all thirteen sections present in A, compact control works;
B supports dish → wheat berries → vinaigrette → lemon oil and back to the
original parent focus/scroll; C preparation selection updates its method; the
simple fixture renders a single method with prep and contextual ingredients.
These are browser prototypes in simulated chat, not verified ChatGPT widgets.

No final design has been accepted. Capture the prototype and verdict on a
throwaway branch once accepted, then separately implement host integration.

## Scope decision: everyday meals first

The user considers these layouts promising but has not accepted them as suitable
for chat. The first recipe display should focus on ordinary, self-contained
meals. Multi-part restaurant recipes are deferred; their eventual presentation
may be a different surface entirely. Do not make an inline widget accommodate
the EMP workload as a condition of shipping the everyday experience.

Preserve the everyday sample's readable method and ingredient context. Keep
servings/time and provenance clear, with optional mise en place and compact
display. Do not introduce preparation navigation, dependency trees or cooking
sessions into this first version.

The next validation is one everyday recipe inside actual ChatGPT using the MCP
UI resource/tool-result path. Verify initial height, expansion, source access
and narrow layouts there. The existing image widget supplies a working project
integration precedent, but no recipe tool/resource is registered yet. Browser
prototypes alone do not satisfy this acceptance check.
