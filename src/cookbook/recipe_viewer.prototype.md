# Recipe presentation prototype, round 4

The user found the stateless round-three design busy and unintuitive. The active
prototype now uses one compact card and one primary disclosure: **View recipe**.

Run:

```sh
python3 src/cookbook/recipe_viewer.prototype.py
```

Open <http://127.0.0.1:8766/recipe.prototype?recipe=simple> or select the EMP sample
using the small preview selector outside the card.

The simple recipe reads straight through: ingredients, a short “Before you cook”
prep section, and numbered method. The EMP recipe shows five main components that
expand in place, each with the same reading order. Supporting recipes sit under
one disclosure and open directly from ingredient links. Sources are available at
the end of each component, with one note explaining the condensed presentation.

Removed the tabs, focused modes, component selectors, variant bar, debug state,
repeated source badges, and workflow framing. No checkboxes, progress tracking,
persistence, or live LLM calls. Native disclosures reset on reload. Old variant
and panel query parameters are ignored by the current route.

Sample recipe content is synthetic. The normalized EMP recipe and source text
remain outside Git at:

`~/cookbook-mcp-data/prototypes/recipe-display/emp-recipe.json`

The loopback launcher serves only the prototype and that exact fixture. Override
the fixture path with `RECIPE_PROTOTYPE_EMP`; without it the simple example works.
The current implementation is not connected to the production MCP server.

Round-one historical variants remain at `/recipe-v1.prototype?variant=B`; they do
not represent the current design. Further design feedback is pending. Capture
the throwaway prototype and verdict when a direction is accepted, then implement
production behavior separately.
