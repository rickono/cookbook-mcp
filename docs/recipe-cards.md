# Everyday recipe cards

The selected design places each cooking action beside only the ingredient
quantities used in that action. Prep belongs in the method at its point of use;
useful overlap can be described in the same prose. There are no readiness
subtitles, prerequisite labels, timers, checklists, or stored cooking sessions.
This is the accepted B direction from the everyday HTML study (September 14,
2026). Multi-component project recipes remain outside this card's scope.

## MCP contract

`show_recipe(recipe)` renders one finalized recipe using
`ui://cookbook/recipe-v2.html`. It is a read-only presentation tool; it does not
search, verify, save, or modify recipes. Search and source-reading tools remain
free of recipe templates. Brainstorming stays in prose; the selected everyday
recipe gets one card. Avoid repeating the complete recipe below it.

The input contains a title, optional short metadata/description, ordered actions
with ingredient quantities and method text, and source attribution. Book and
adapted recipes require exact publication/book/source/section identifiers.
These identifiers are supplied by the model, not independently verified by the
render tool. A citation may carry `physical_pages` for a scanned section. The tool
does not trust the model's value: it looks up the cited section in the publication
and fills `physical_pages` from that section's `scanned-section` locator. The field
is dropped when the cited section is not a scanned section or cannot be found. Tool instructions require reading the complete source, following
continuation offsets, preserving quantities and dependencies, and identifying
adaptations. Original recipes are explicitly labeled. Divided ingredient
amounts must be supplied separately at their points of use.

The Pydantic model bounds inputs and rejects unknown fields. The component
validates received data, escapes all text, accepts messages only from its
parent, and requests no network or external assets. The full data is also
returned as text and structured content for clients without widgets. The MCP
endpoint and resource use the existing OAuth authorization.

Only the standard `_meta.ui.resourceUri` links the recipe tool to its UI;
the recipe tool does not also set the legacy output-template alias.
The component uses the MCP Apps initialize/tool-result/theme/resize bridge,
with the existing ChatGPT globals compatibility path. Compact/expand and source
disclosure are temporary UI state. Duplicate delivery preserves the current
presentation; loading the card again starts expanded. Actual height remains
subject to the host's presentation limits.

## Validation and deployment

```sh
uv run pytest tests/test_mcp.py tests/test_image_discovery.py \
  tests/test_library_auth.py tests/test_image_context.py tests/test_hosted.py -q
node --test tests/recipe_viewer.test.mjs tests/image_viewer.test.mjs
```

25 Python checks and 10 JavaScript checks pass. Coverage includes authenticated
MCP schema/resource discovery and rendering, rejection of missing book citations,
text fallback, source identifiers, escaped markup, untrusted message rejection,
error clearing, standard/compatibility delivery, theme changes, and compact state.
The Linux/amd64 deployment image also passes an isolated synthetic authenticated
MCP smoke test. No ingestion or OCR was run.

Deployed on September 14, 2026 to the existing `cookbook-agent` Machine
`2863795a042368`, image
`registry.fly.io/cookbook-agent@sha256:a07921f05ae25e604592f6d982f2d7c0ce09ba7733ad7508430a7eb81384a4c2`.
The verified configuration differs only in image. Health checks pass. The
ChatGPT Cookbook Library connection was refreshed and lists `show_recipe` and
its new UI resource. Private deployment context and rollback configuration are
under `~/cookbook-mcp-data/setup/recipe-card-20260914/`.

The production renderer is independent of the throwaway HTML studies; prototype
files are excluded from Docker build contexts.

The accepted study is archived on the separate
[prototype branch](https://github.com/rickono/cookbook-mcp/tree/prototype/everyday-recipe-b-20260914/src/cookbook),
linked from [the implementation ticket](https://github.com/rickono/cookbook-mcp/issues/10).

## Real ChatGPT acceptance

The final standard-only registration rendered one four-action original recipe
with ingredients beside the method, no readiness subtitles or photos, and a
brief response. Compact/expand works; source disclosure was exercised in the
initial deployment. Reload restores the recipe and starts expanded as intended.
The final example is
[Create recipe card](https://chatgpt.com/c/6aa7eece-13e8-83ea-bcf6-97e9cd6a1d8d).

Reload also creates an additional empty host wrapper above the correct card.
Removing the idle loading text and the legacy template alias did not eliminate
that wrapper. The exact replay cause remains unconfirmed; this limitation is
tracked in [the reload investigation](https://github.com/rickono/cookbook-mcp/issues/11).
The verified account had CSP off already, so these live checks do not establish
ChatGPT CSP enforcement. The declared policy remains empty and the card has no
external assets or connections.
