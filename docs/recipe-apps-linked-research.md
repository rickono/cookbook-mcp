# Linked recipe research: Mealie

Researched 2026-09-13 against official documentation, release notes and a merged
pull request. Supplement to the consumer, guided and professional app research.

## Observed behavior

Mealie documents assigning ingredients to individual instructions, including
linking one ingredient to both a preparation step and a later cooking step.
That supports the basic premise of prototype B: ingredients can live next to
the action that uses them. It does not prove that each repeated amount is an
allocated portion of the ingredient rather than the total recipe quantity.
[Official FAQ](https://docs.mealie.io/documentation/getting-started/faq/#why-link-ingredients-to-a-recipe-step)

Release v3.5.0 explicitly introduced recipes as ingredients in other recipes,
using sauce for fried rice as its example. This supersedes older discussions
that described hyperlinks as a workaround.
[Official release](https://github.com/mealie-recipes/mealie/releases/tag/v3.5.0)

Merged PR #4800 describes referenced recipes as a distinct ingredient type.
Selecting the reference opens a new tab; adding the parent recipe to a shopping
list recursively includes the linked recipes' ingredients. A screenshot in the
PR shows a linked “Spicy Pickled Radishes” ingredient above a “Chicken” group,
with a servings control above the ingredient list. The screenshot was visually
inspected; the current running app was not tested. The GitHub API confirmed the
PR merged on 2025-11-04.
[PR and screenshots](https://github.com/mealie-recipes/mealie/pull/4800)

## Implications for our card (inference)

- Treat a prepared component as an ingredient in the parent method, with a
  reference to its own preparation. Do not show every nested instruction by
  default.
- Keep per-step quantities, but distinguish source batch quantities from
  amounts actually used in the step. Repetition is not quantity allocation.
- Preserve the parent reading position when consulting another recipe. A new
  browser tab is an observed implementation, not a recommendation for chat.
- Aggregate raw ingredients only when the user wants a shopping/prep view;
  expanding every ingredient recursively is a different task from reading the
  parent method.

No verified evidence here of automatic chronological scheduling across nested
recipes, cross-device cooking state, or actual ChatGPT widget behavior.
