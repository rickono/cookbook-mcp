# Consumer recipe apps: composing multiple components

Research date: 2026-09-13. Scope: primary public documentation and selected official screenshots for Paprika, Mela, AnyList, Samsung Food, and a lighter Recipe Keeper check. No installed-app walkthrough or usability study was performed. “Not documented” below means this research did not establish a capability; it does not prove the capability is absent.

## Findings

Consumer apps offer three distinct patterns: headings inside one recipe, links to separate recipes, and switching between recipes while cooking. These should not be conflated with an automatically scheduled dependency graph. The strongest direct example is Paprika's official screenshot of **carrot cake and cream cheese frosting pinned together**: a compound dish remains two navigable recipes. [Screenshot](https://www.paprikaapp.com/static/images/help/ios/pinned_recipes.png)

### Paprika 3: a readable parent recipe with links to supporting recipes

Paprika supports ingredient headings, such as a sauce section, plus recipe links embedded in recipe text. Its main recipe view puts ingredients alongside directions on the documented large layout. Recipe links resolve by name; duplicate names require choosing a match on iOS, and renames require repairing links. The documented scaling control changes the selected recipe's ingredient quantities; recursive scaling across linked recipes is not established. [iOS guide, recipe fields and text](https://www.paprikaapp.com/help/ios/#addingandeditingrecipes)

Recipes can be pinned for fast switching during cooking. The app retains crossed-off ingredients and the highlighted direction for each pinned recipe. The reviewed screenshot shows cake and frosting as two entries under pinned recipes. This is a particularly relevant concrete example of component navigation. [Pinning documentation](https://www.paprikaapp.com/help/ios/#pinningrecipes), [reviewed screenshot](https://www.paprikaapp.com/static/images/help/ios/pinned_recipes.png)

The separate support article explicitly permits links in ingredients or directions; an editor button inserts a chosen recipe link. This is a real reference to another recipe, not just a visual section heading. [Recipe-link support](https://paprikaapp.zendesk.com/hc/en-us/articles/360048240514-How-do-I-link-to-another-recipe-from-within-a-recipe)

**Inference for our card:** keep the dish readable and link the name of a preparation where it is needed. A local reader could open that preparation and provide an obvious return to the dish. The pinning pattern is useful evidence for navigating a few active preparations, not justification for adding a 13-item tab bar.

**Scope limit:** these findings concern the documented Paprika 3 interface. Paprika's support page mentions a Paprika 4 beta, whose UI was not reviewed. [Version context](https://paprikaapp.zendesk.com/hc/en-us/requests/new)

### Mela: named sections, with an optional focused cooking surface

Mela groups ingredients with headings. It also groups instructions; a heading restarts instruction numbering. This establishes a readable multi-part document, not reusable subrecipe identity. Its help explicitly says imported Paprika links to other recipes are unsupported. Cook mode enlarges ingredients and steps, focuses the current step, and lets users mark ingredients. [Editing and cook-mode documentation](https://mela.recipes/help/)

Mela also advertises adding several recipes to cook mode and switching among them, with timers managed there. That is coordination of separate recipes, rather than documented automatic interleaving of their methods. [Official product page](https://mela.recipes/)

**Inference for our card:** descriptive component headings can do much of the organizing work without a control on every section. Keeping each component's numbering local makes a preparation easier to discuss. A focused cooking view is a separate concern from making the first chat card compact.

**Evidence limit:** the help page was fully readable; the homepage supplied indexed official text but subsequently returned a verification interstitial. Mela screenshots were not independently inspected in this pass.

### AnyList: explicit multi-part formatting and adaptive reading layouts

AnyList directly recommends ingredient headings for multipart recipes. Its editor can insert a heading or convert an imported ingredient row into one. [Ingredient-heading documentation](https://help.anylist.com/articles/recipe-ingredient-headings/)

Its preparation editor supports headings, emphasis, and multiline steps. The reviewed **Homemade Cherry Pie** screenshot has a **Make the crust** heading, then numbered steps in one scrolling document. The section is typographic, not an accordion or card. [Preparation-formatting documentation](https://help.anylist.com/articles/recipe-prep-step-formatting/), [reviewed screenshot](https://help.anylist.com/img/articles/recipe-prep-step-formatting-0.png)

“View Full Recipe” opens cooking view. Phones separate ingredients, steps, and recipe information into swipeable tabs, preserving each tab's scroll position. Larger screens show ingredients and steps side by side. Users can mark ingredients and highlight a step. A recipe switcher supports cooking several dishes; opening from the meal calendar includes that day's other recipes. The reviewed tablet screenshot confirms the plain two-column reading layout. [Cooking-view documentation](https://help.anylist.com/articles/recipe-cooking-view/), [reviewed screenshot](https://help.anylist.com/img/articles/recipe-cooking-view/cooking-view-full.png)

Scaling changes ingredient quantities and servings, but quantities embedded in preparation steps do **not** scale. The official guide explicitly illustrates this mismatch. [Scaling limits](https://help.anylist.com/articles/scale-recipe/)

**Inference for our card:** familiar recipe typography may matter more than compact/expanded controls. B's step-adjacent quantities can avoid tab switching, but only if each quantity is genuinely assigned to that step; repeating a whole component's batch amounts beside several steps risks implying multiple uses. No reusable linked-subrecipe behavior was established from these AnyList pages.

### Samsung Food: ingredient sections, but no demonstrated component composition

Recipe Builder supports ingredient section headers, individually authored instruction steps, servings, and prep/cook times. This is evidence of grouping within one recipe; this guide does not establish reusable recipe references or a multi-component schedule. [Builder documentation](https://support.samsungfood.com/hc/en-us/articles/18369261226644-Getting-Started-with-Samsung-Food-Create-and-Edit-Recipes)

The documented recipe page separates ingredients, instructions, and health information. It offers serving and unit adjustments, and explains that many imported recipes show their instructions on the creator's site within the app. [Recipe-page documentation](https://support.samsungfood.com/hc/en-us/articles/18588916048276-Recipe-Page-101)

The newer Food+ documentation advertises Smart Cook Mode with guided steps and AI tips. That is not evidence that it decomposes or schedules nested recipes correctly. [Food+ capabilities](https://support.samsungfood.com/hc/en-us/articles/32709269852052-What-s-Included-in-Your-Samsung-Food-Subscription)

**Inference for our card:** Samsung is useful as evidence that an overview and a cooking surface can differ. It provides weaker public evidence for the actual EMP composition problem than Paprika or AnyList. No claim about Samsung's current nested-recipe UX should be made from these sources.

### Recipe Keeper: insufficient public evidence for this question

The official site establishes serving adjustment with ingredient recalculation and a meal planner that can add its recipes' ingredients to a shopping list. It does not demonstrate ingredient/step component groups, reusable subrecipes, or dependency-aware preparation timing. It was screened but is not a strong design precedent for this task. [Official site](https://recipekeeperonline.com/)

## Implications to test, not conclusions about usability

1. **Separate a component from a supporting recipe.** A section such as roasting carrots can remain within the dish. Lemon oil or stock can be referenced as a distinct preparation with its own batch yield. Paprika provides the clearest precedent for this distinction.
2. **Explain the dish before presenting all the labor.** For the EMP case, an initial orientation should say what comes together on the plate and expose advance preparation requirements. The scanned consumer sources do not demonstrate a sufficient make-ahead schedule; this would be our design hypothesis, not a copied best practice.
3. **Use headings before adding controls.** AnyList's actual multipart screenshot is simply a component heading followed by steps. A disclosure on every part is not necessary to make hierarchy visible.
4. **Keep recipe quantities and step allocations distinct.** A batch of stock is not the same amount as the stock the dish consumes. Consumer serving controls do not establish recursive scaling, and AnyList documents the risk of stale quantities inside steps.
5. **Do not copy session machinery into a stateless chat card.** Pins, remembered positions, timers, and checked ingredients are part of these apps' cooking sessions. We can borrow their navigational clarity while keeping our card a reloadable document.
6. **Test the supporting-recipe round trip in ChatGPT.** An EMP user should be able to see a required preparation, read it, and return to the exact parent context. Whether a linked detail panel, inline expansion, or fuller reader does that best remains untested.

No prototype or production code was changed for this research.
