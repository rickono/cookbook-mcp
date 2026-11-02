# Professional recipe apps: composed recipes

Research date: 2026-09-13. Scope: meez, Galley, Fillet, and Apicbase, using their own documentation. This is a design investigation for a stateless chat recipe card, not a recommendation to install kitchen management software.

## Main finding

These products generally model a composed dish as a recipe containing measured amounts of other recipes. That provides a useful distinction between **making a preparation** and **using some of it to assemble a dish**. The strongest cook-facing evidence is Galley's compact component list followed by procedures. The sources do not establish that any of these apps automatically interleave a large recipe tree into an optimal cooking sequence.

A supporting recipe is therefore not necessarily another top-level step. A stock, sauce, or infused oil can be a linked ingredient at its point of use, with its own preparation document behind the link. The design inference for our EMP example is to preserve that relationship, while separately making advance work discoverable.

## Galley: strongest observed cooking layout

Galley offers a simplified, mobile-oriented Recipe Card alongside its full detail view. Its component section is condensed like a printed recipe. Procedures can be a grid or carousel. The documentation warns that fullscreen image navigation skips steps without images, so that interaction is a poor default for recipes extracted primarily as text. [Recipe Card view](https://support.galleysolutions.com/what-is-the-recipe-card-view)

I inspected frames of the official component and phone GIFs. The desktop card shows a short bulleted component list next to the dish photo: the sauce appears as an underlined name, a measured quantity, and a small Recipe badge. Other ingredients remain ordinary ingredient rows. A separate Procedures section follows. The mobile example stacks numbered procedure text with images in one vertical document. These are vendor demonstration screenshots, not a live authenticated test. [Official component demonstration](https://support.galleysolutions.com/hs-fs/hubfs/components.gif?height=423&name=components.gif&width=670), [official phone demonstration](https://support.galleysolutions.com/hs-fs/hubfs/phone.gif?height=460&name=phone.gif&width=212)

The display can hide or reorder sections; description, notes, and procedures are collapsible. Layout configuration is company-wide, while collapse preferences are stored locally per browser. We can adopt disclosure without adopting either persistence mechanism. [Recipe Card settings](https://support.galleysolutions.com/how-do-i-customize-what-appears-on-recipe-cards)

Galley can include all descendants of a parent recipe in an export, and its PDF option can show or hide sub-recipes. That separates the concise parent recipe from a complete preparation packet. [Export with subrecipes](https://support.galleysolutions.com/how-can-i-export-a-recipe-with-its-subrecipes)

**Adaptable:** measured, visibly linked preparations; a continuous method; optional complete expansion. **Unverified:** how deep subrecipe navigation behaves in the live card, or whether it returns to the exact previous reading position.

## meez: reusable preparations and explicit prep actions

meez adds an existing recipe to another recipe's ingredient list. Its documentation uses composed dishes such as Beef Wellington, with separate pastry, filling, and sauce recipes. It also treats ingredient prep actions such as slicing or chopping as structured information, including yield changes. [Ingredients and subrecipes](https://intercom.help/getmeez/en/articles/5761292-adding-ingredients-and-sub-recipes-to-recipes)

Headers can divide ingredient groups and preparation steps; notes can hold longer explanations. Total yield is separate from the ingredient list and supports scaling. Preparation steps can include image/video instructions. [Creating a recipe](https://intercom.help/getmeez/en/articles/4664927-creating-your-first-recipe)

Its order-list export consolidates ingredients across recipes. Correct yields and defined units are necessary: a named batch must have a quantitative equivalency. This is a purchasing calculation, not evidence of a cooking-oriented mise en place display. [Order lists](https://intercom.help/getmeez/en/articles/5017091-exporting-order-lists)

A completeness caveat: printing a recipe book does not automatically print its subrecipes unless those are also included in the book. [Printing](https://intercom.help/getmeez/en/articles/4487873-printing-recipes)

**Adaptable:** preparation names as ingredients, grouping without extra navigation, source-supported prep verbs. **Unverified:** a compact nested reader or automatic sequencing. The documentation does not show an LLM extracting a complete prep checklist from adjectives.

## Fillet: preserve hierarchy, offer a flattened inventory

Fillet distinguishes ingredients, subrecipes, and labor activities as recipe components. A recipe has a quantity/unit yield; a parent specifies how much of the child it uses. The example of using 200 mL from a 1 L vinaigrette batch illustrates the difference between required quantity and full batch yield. [Recipe model](https://help.getfillet.com/docs/production-costing/recipes/)

On the web, Layers tables show ingredient and recipe relationships through nested subrecipes. Mobile's List all ingredients includes ingredients contained in child recipes. Layers can reveal repeated uses and the route through intermediate preparations. This interface is documented largely for tracing and resolving data/conversion problems, not for following a cooking method. [Layers for recipes](https://getfillet.com/en/guides/layers/2/layers-for-recipes)

**Adaptable:** keep a complete dependency model internally; offer a complete ingredient view when needed. **Avoid:** presenting the full dependency graph as the default reading experience. A deeply nested component browser is not demonstrated to solve the cook's order-of-work problem.

## Apicbase: separate composition from production

Apicbase marks reusable preparations as semi-finished recipes, then inserts them into parent recipes like ingredients. Its ingredient table distinguishes ingredients from recipes. Explicit finished yield matters: its example uses 400 g from an 800 g mayonnaise recipe, and the app calculates half the ingredient quantities. Summing input weights can be wrong because of units or cooking loss. [Subrecipes and yield](https://support.apicbase.com/help/how-to-use-sub-recipes)

Ingredients and preparation methodology share a recipe tab; the method has ordered steps, optional images, and separate timing fields for preparation, cooking, plating, and passive work. This is an authoring/documentation feature, not demonstrated automatic scheduling. [Creating a recipe](https://support.apicbase.com/help/create-a-new-recipe)

A separate production-plan workflow expands required subrecipes in the needed quantities. A cook can exclude a preparation already in stock. That supports the distinction between the dish's composition and what must actually be made today, but the workflow has assignments, workstations, and state that are inappropriate for our current scope. [Production planning](https://support.apicbase.com/help/how-can-i-make-a-production-plan)

**Adaptable:** explicit amounts, advance preparations, separate final assembly. **Avoid:** importing the production planner and its status controls into the chat card.

## Application to our prototypes (design inferences)

The EMP example has five main sections plus eight supporting preparations. Flattening all thirteen into one method obscures which items are finished components; showing all thirteen as equal navigation targets turns the recipe into a document browser. Neither problem is solved just by compacting the same content.

A more promising next test is:

1. Keep B's readable method and ingredients at the point of use.
2. Refer to a prepared ingredient by name and required amount. Its linked detail shows both the amount used in this dish and the original recipe's batch yield. Do not silently scale minimum practical batches or book recipes.
3. Put a short advance-work note before the method so overnight and long-running preparations cannot be discovered only at plating time. Treat this as our design inference, not a feature verified across these apps.
4. Give final assembly its own clear section; keep supporting preparations attached to the components that consume them.
5. Let the same document collapse to named method sections while retaining the title, yield, and advance-work note. Disclosure is presentation state only; no progress tracking is needed.
6. Keep access to the full preparation packet and complete ingredient list, because a concise card must not hide missing dependencies.

The next evaluation should ask concrete cooking questions: What has to happen the day before? What can I start now? How much vinaigrette do I need? Where does it get used? Can I return from its recipe without losing the parent step? Test these in the actual ChatGPT host rather than claiming a standalone mockup settles the experience.

## Evidence limits

No accounts were created and no paid applications were exercised. Findings come from first-party documentation and, for Galley, inspected official demonstration images. No source established an automatic dependency-aware chronological cooking plan. Backend costing, purchase consolidation, and production planning are explicitly separated from observed reading UI. UI preferences and collapsible sections are not evidence of cross-device cooking-session persistence.
