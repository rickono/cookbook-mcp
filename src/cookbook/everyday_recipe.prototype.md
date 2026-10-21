# Everyday recipe HTML study

## Accepted design

The user selected **B — Ingredients by action** on 2026-09-14. Ingredients
remain beside the action that uses them. Remove the small prerequisite subtitles
(such as “Once the beans are warm”); each method cell starts with its numbered
step title, followed by the instructions. Keep actual cooking conditions in the
instructions where they matter.

The active preview now always renders B and has no comparison switcher. Width,
theme, source information and compact/expanded controls remain available.
This accepts the visual direction only; ChatGPT integration is still pending.

## Exploration history

Question: how can A show ingredient dependencies and opportunities to prepare while cooking?
The user requested HTML design iteration before ChatGPT integration.

Run `python3 src/cookbook/recipe_viewer.prototype.py` and open
<http://127.0.0.1:8766/everyday-recipe.prototype?variant=B>.

- A — Recipe sheet: the existing ingredients-and-method baseline, unchanged.
- B — Ingredients by action: four aligned rows, each pairing the ingredients
  needed with its cooking action. Brief prerequisites label the transitions;
  prep actions are explicit in the method.
- C — Prep while you cook: grouped ingredients beside a method that brings
  garlic/miso preparation into mushroom browning and lemon/parsley preparation
  into bean simmering. A separate “before” note handles draining the beans;
  it is not claimed to be parallel work.

The former B (quantities embedded in prose) and C (ingredients-first disclosure)
have been removed from this comparison, including their special render paths.
All three now start expanded and use the same compact presentation.

A retains optional mise en place. B and C integrate prep into the method.
All variants retain source/sample information and a compact presentation. The same fixed synthetic recipe is used throughout.
There is no EMP content, nested preparation navigation, progress or persistence.

The preview places the widget in a sandboxed iframe (scripts only), with a
simulated tool label and surrounding conversation. Width and theme controls
belong to the preview, not the product. Resize messages grow the frame with its
content. This is a local preview protocol, not the MCP Apps bridge. No actual
ChatGPT renderer, host height limit, authorization or tool execution is simulated.

Browser checks covered A loading as the baseline; B's four aligned ingredient
rows and C's interleaved prep at chat and phone widths; dark mode; and C's compact
and expanded views. The iframe continues to resize without internal scrolling.
B and C keep ingredients and method beside one another at phone width; the
increased height is a visible design tradeoff, not a verified ChatGPT fit.

Ingredient uses and proposed overlap are manually authored for this synthetic
sample. There is no inferred universal scheduler, estimated parallel timeline,
readiness tracking or saved progress. B is the accepted visual direction. This is still prototype code, not an
accepted production implementation.

## Iteration workflow checked 2026-09-14

The official guide supports developer-mode testing through a public HTTPS MCP
endpoint or Secure MCP Tunnel. After server/tool/UI-resource changes it documents
restarting or deploying the server, refreshing the connection metadata and
starting a new conversation to retest. This is not documented as automatic
frontend hot reload. Availability depends on account/workspace policy.
[Connect and test](https://developers.openai.com/plugins/deploy/connect-chatgpt)

The inline UI guidance advises a self-contained card, avoiding deep navigation
and internal scrolling. Use local HTML for quick visual changes, then check the
chosen design inside actual ChatGPT rather than treating this preview as proof
of host behavior.
[UI guidance](https://developers.openai.com/plugins/concepts/ui-guidelines)

Production MCP registration is unchanged. Capture this throwaway prototype and
its verdict separately once the everyday design is accepted.

Selected-preview check: four ingredient/action rows remain, with no prerequisite subtitle elements or comparison controls.
