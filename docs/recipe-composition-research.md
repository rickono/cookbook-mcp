# Recipe composition research

Research date: 2026-09-13. Question: how should a stateless recipe card present
a simple dish and an ambitious dish with many supporting preparations?

Three parallel agents researched consumer managers, guided/editorial cooking
experiences, and professional recipe systems. A fourth pass checked Mealie's
released linked-recipe implementation. Sources are first-party help pages,
public recipes, release notes and selected inspected product screenshots.
Findings describe documented or observed behavior, not comparative usability
scores. No authenticated commercial applications or actual ChatGPT recipe
widgets were tested.

## Subsequent scope decision

After reviewing the prototypes, the user chose to focus the first version on
everyday, self-contained meals. Ambitious multi-part recipes are deferred and
may need an entirely different presentation surface. The recommendations below
remain research for that later problem, not first-version requirements. The
immediate acceptance check is an everyday recipe rendered in actual ChatGPT.

## What changes our thinking

The central design question is how the recipe is composed, before how much text
is visible. Our current B displays five main sections first and places eight
required supporting preparations under a disclosure at the bottom. Compact mode
reduces those main sections to an outline. That saves space but does not clarify
what must be made first, where a preparation is used, or how a batch relates to
the amount needed. This is a hypothesis based on the prototype and user feedback,
not a demonstrated cause of the user's reaction.

The research supports two distinct reading models:

1. **One complete, authored method.** Component headings organize a continuous
   recipe; preparation is ordered explicitly and ends in assembly. This works
   when the author has already composed the instructions into a whole.
2. **A dish built from other recipes.** A prepared ingredient remains a named,
   measured item in the parent. Its preparation has its own recipe, and the
   parent makes prerequisites visible before the point of assembly.

A chapter heading, a reference to another recipe, and an automatic cooking
schedule are different capabilities. None of the inspected sources establishes
that a generic recipe app can optimally schedule the EMP recipe's complete
nested dependency structure.

## Most useful precedents

| Product | Evidence | Implication for this card |
| --- | --- | --- |
| Great British Chefs | A nine-part carrot dish uses 36 continuous steps with ingredient quantities beside relevant actions; long-lead work precedes assembly. | B can work when the complete method is deliberately composed in preparation order. |
| ChefSteps | Salmon 104 °F places four linked component recipes in the parent method before finishing and plating. | Required preparations should be explicit actions, with access to their own recipes. |
| Paprika 3 | Links in ingredients/directions; pinned cake and frosting recipes in the official example. | Let a supporting preparation remain its own recipe and make the return to the parent easy. |
| AnyList / Mela | Named component headings within ingredients and instructions; optional cooking views. | Plain document hierarchy can organize a recipe without a control around every part. |
| Galley | Measured linked recipe ingredients in a condensed component list, followed by procedures. | Show a sauce as an ingredient the dish consumes, not all of its instructions by default. |
| meez / Apicbase / Fillet | Reusable preparations have yields; the parent uses a specified amount. | Separate the amount needed here from the amount the source batch makes. |
| Mealie | Released recipe-as-ingredient references and ingredients assigned to instructions. | B's local ingredient context is viable, but ingredient allocation and subrecipe navigation need explicit treatment. |

Sources: [Great British Chefs carrot dish](https://www.greatbritishchefs.com/recipes/carrot-golden-beetroot-nasturtium-oil-goats-curd-recipe),
[ChefSteps Salmon 104 °F](https://www.chefsteps.com/recipes/salmon-104-f),
[Paprika links](https://paprikaapp.zendesk.com/hc/en-us/articles/360048240514-How-do-I-link-to-another-recipe-from-within-a-recipe),
[Paprika cake/frosting screenshot](https://www.paprikaapp.com/static/images/help/ios/pinned_recipes.png),
[AnyList multipart instructions](https://help.anylist.com/articles/recipe-prep-step-formatting/),
[Mela help](https://mela.recipes/help/),
[Galley Recipe Card](https://support.galleysolutions.com/what-is-the-recipe-card-view),
[meez subrecipes](https://intercom.help/getmeez/en/articles/5761292-adding-ingredients-and-sub-recipes-to-recipes),
[Apicbase yields](https://support.apicbase.com/help/how-to-use-sub-recipes),
[Fillet recipes](https://help.getfillet.com/docs/production-costing/recipes/),
[Mealie release](https://github.com/mealie-recipes/mealie/releases/tag/v3.5.0),
[Mealie step links](https://docs.mealie.io/documentation/getting-started/faq/#why-link-ingredients-to-a-recipe-step).

## Recommendation to evaluate

Keep B's ingredient context near the action, but change the organization of the
complex example. Test the following as a reading experience, without timers,
checkoffs or saved cooking sessions:

- Explain the finished dish and the advance work before showing the main method.
  Required supporting preparations must be discoverable here, not only at the
  ingredient that uses them or in a collapsed appendix.
- Use plain named sections for work that belongs to the dish. Keep reusable
  stock, oils and sauces as linked preparations. Do not make every nested recipe
  an equal top-level card or flatten the entire dependency tree automatically.
- Let a link open the preparation with its ingredients, prep and method, and
  provide a clear return to the parent location. The exact inline/reader host
  interaction remains to be tested in actual ChatGPT.
- Distinguish “needed for this dish” from “source batch makes.” Preserve source
  quantities until scaling is explicitly supported; some practical batch sizes
  cannot simply be multiplied down.
- Compact the supporting detail while keeping the dish's composition and advance
  requirements visible. A short outline alone is not enough orientation.
- Keep final assembly explicit so the cook can see what the preparations become.

For the simple sample, this should still read like one ordinary recipe. It does
not need a component navigator. The complex example earns additional structure
because it contains independently prepared ingredients.

## Where an LLM can help (proposed, not verified app behavior)

Resolve references to supporting recipes, identify long-lead prerequisites, and
translate source ingredient preparation into short tasks next to the appropriate
component. Tie each transformation to the original source. Keep preparation
that must happen just before use at that point in the method, rather than moving
all chopping, draining or seasoning to a universal checklist.

Scheduling requires more than sorting component names: equipment constraints,
passive waits, holding instructions and source dependencies must be accounted
for. Do not infer a single total duration or an exact service-time schedule from
component times alone. None of this research establishes that an LLM-generated
schedule is reliable without verification.

Ingredient links also are not necessarily step allocations. The amount shown
beside a step may be the whole recipe quantity. AnyList explicitly documents
that ingredient scaling does not update quantities embedded in instruction text.
[Scaling limitation](https://help.anylist.com/articles/scale-recipe/)

## Questions for the next actual-host prototype

The next experiment should answer these concrete reading questions:

1. Can I see that the dish requires advance preparation without opening every part?
2. Can I identify the prerequisite for the part I want to cook now?
3. Can I find how much of a supporting preparation is needed versus its batch yield?
4. Can I consult that preparation and return without losing my parent context?
5. Can I understand final assembly without opening a full dependency tree?
6. Does the simple recipe still feel simple at phone/chat width?

The recommendation is not a validated winning layout. Browser-only mockups have
not established the recipe UI's behavior inside ChatGPT.

## Research notes

- [Consumer managers](recipe-apps-consumer-research.md): Paprika 3, Mela, AnyList,
  Samsung Food; Recipe Keeper screened with insufficient composition evidence.
- [Guided and editorial experiences](recipe-apps-guided-research.md): concrete
  multi-component dishes, authored preparation sequence, and linked projects.
- [Professional systems](recipe-apps-professional-research.md): Galley, meez,
  Fillet and Apicbase; cooking UI distinguished from costing/production tools.
- [Mealie](recipe-apps-linked-research.md): released subrecipe references and
  ingredients assigned to individual instructions.

No prototype or production code was changed during this research.
