# Multi-component recipe presentation: published cooking experiences

Research date: 2026-09-13. Primary-source public pages only. Great British Chefs and ChefSteps were inspected in a live browser; SideChef and Serious Eats were inspected through extracted public page content. No account, paywall bypass, or native-app testing. Observations apply to these examples, not every recipe on each service.

## Great British Chefs: one authored method

**Observed:** [Lorna McNee's carrot and golden beetroot dish](https://www.greatbritishchefs.com/recipes/carrot-golden-beetroot-nasturtium-oil-goats-curd-recipe) has nine ingredient groups and 36 numbered steps. Desktop puts grouped ingredients in a left column and method in the centre. Relevant quantities repeat in boxes beneath steps. Pickles, mousse, sauce, oil, curd and other preparations appear within the method before assembly, rather than as required recipes hidden below it. Pickle work comes first, then mousse, including explicit infusion, pickling and overnight-setting waits. Final steps assemble the dish.

**Limits:** This is authored component ordering, not an automatically optimized schedule. It does not interleave the whole dish into a time plan. The headline time compresses several distinct waits; ingredient descriptions still assume preparation such as chopping or blooming.

**Inference:** B's contextual quantities have a strong precedent. Its bigger problem may be ordering: displaying main preparations before their required supporting work makes the page difficult to cook from. Embedding supporting work before use is more consequential than adding a compact toggle.

## ChefSteps: explicit prerequisite recipes, then assembly

**Observed:** [Salmon 104 °F](https://www.chefsteps.com/recipes/salmon-104-f) presents four component recipes as ingredient entries, each expressed as one recipe. Its six named steps first prepare those four components, then grind spices, then plate. Each prerequisite step includes a related-recipe panel and a button to open the recipe. Clicking the salmon component navigated to its own page. Step sections have collapse controls; recipe navigation includes ingredients, equipment, steps and class index. The parent separates active time from total time and yield. This is a composed dish with explicit prerequisites, rather than a single flattened ingredient list.

The [Salmon Mi-Cuit child recipe](https://www.chefsteps.com/recipes/salmon-mi-cuit) has its own yield, active and total time, ingredient list, and nine named steps. It includes preparation as cooking work: weighing, making brine, preparing fish while brine chills, and eventual chilling and portioning. This makes readiness instructions part of the method. We did not test scaling propagation between parent and child.

The [project's class page](https://www.chefsteps.com/classes/salmon-104-f) explicitly describes four components that can be prepared ahead, plus plating ideas. It links the dish and individual preparations. This supports the conceptual separation between preparing components and bringing them together, but does not establish automatic scheduling.

**Inference:** For EMP, a short dish-level method could explicitly introduce required preparations before finishing and plating. Each supporting recipe can remain a reusable recipe. In a chat widget, opening one in place with a clear return could reduce the navigation cost of ChefSteps' separate pages. That interaction is a proposal, not an observed ChefSteps behavior or a verified ChatGPT capability.

## SideChef: quantities inside the instruction

**Observed:** [Fish Wellingtons](https://www.sidechef.com/recipes/1429/Fish_Wellingtons) shows ingredient count, step count and total time up front, followed by an ingredient list and 13 cooking steps. Ingredient names and quantities appear directly in method sentences. Fish preparation and vegetable filling are embedded in the sequence before pastry assembly; they are not separate prerequisite recipe pages. Instructions also perform some ingredient preparation. Step photographs are accompanied by a Hide images control.

**Limits:** This modestly composed dish does not establish how SideChef handles an EMP-sized dependency structure. Native app cooking mode and image-toggle behavior were not tested.

**Inference:** For a simple recipe, putting quantities directly into sentences could give B less repetition and visual furniture than separate ingredient panels per step. Long ingredient sets may still need a short grouped list.

## Serious Eats: useful contrast, not the strongest structural match

**Observed:** [The Ultimate Beef Wellington](https://www.seriouseats.com/the-ultimate-beef-wellington-recipe) separates a detailed explanatory article from the recipe, offers jump navigation, lists prep/cook/chilling time, and provides one ingredient list and illustrated numbered directions. Components are prepared inside the sequence; optional homemade pastry is linked. Public content includes a keep-screen-awake control.

**Inference:** Keep optional technique explanation separate from the essential method. This example offers less support for organizing thirteen component preparations.

## Implications to test, not decisions already made

Two distinct structures deserve comparison:

1. A complete authored cooking sequence, with ingredients available where used.
2. A dish-level sequence that explicitly calls for component recipes, followed by finishing and assembly.

The first reduces navigation but grows long. The second preserves meaningful units but requires clear access to prerequisites and a reliable return to the dish. Neither needs progress tracking or cross-device state to be readable.

For our next evaluation, ask whether a cook can identify what must exist before a main step begins, find the exact preparation and quantity, and return to finishing without losing context. Test both simple and EMP fixtures. Do not assume a collapsed outline fixes a method whose dependencies appear in the wrong place. Any LLM-authored reordering or mise en place should be distinguished from the source author's sequence and checked against the source; these sites do not establish that arbitrary automatic scheduling is reliable.
