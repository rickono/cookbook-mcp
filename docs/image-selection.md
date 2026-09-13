# Image selection without candidate cards

The reported ChatGPT workflow displayed every image examined while looking for
a recipe photo. EPUB sections can share the entire document's image list, and
`get_image` attached a viewer to each candidate request. The final reply could
identify the right photo, but rejected photos were already in the conversation.

## Current workflow

1. `list_images(publication_id, book_id, source_id, section_id, offset=0,
   limit=10)` returns captions and nearby recipe context without image bytes or
   viewer metadata. Results follow the stored document order, have a maximum of
   20 images per call, and use `next_offset` for continuation. This also reaches
   candidates beyond `read_section.image_ids`'s 50-ID cap.
2. `inspect_image(publication_id, book_id, source_id, image_id)` returns the
   existing bounded JPEG and source metadata without a UI template or widget
   payload. Its image block has the MCP audience hint `["assistant"]`.
3. `get_image` retains its existing arguments and viewer behavior. Its
   description now reserves it for the final supported selection. Calling it
   displays a card; it is not the exploration path.

Server instructions and `read_section` descriptions explain this sequence.
Nearness in an EPUB and a nearby recipe title remain contextual evidence, not
proof that an image depicts that recipe. Uncertain results should be explained
without showing guesses. Shared table photos should be identified as such.

The additional tools use the existing publication, book, source, and section
authorization boundaries and asset cache. No index rebuild or book upload is
required. Older publications without the `image_context` table remain readable.
All nine tools are read-only; image resources remain authenticated.

## Rendering contract and verification

OpenAI's [tool result reference](https://developers.openai.com/apps-sdk/reference#tool-results)
distinguishes model/component content from component-only `_meta`, and its
[tool metadata reference](https://developers.openai.com/apps-sdk/reference#_meta-fields-on-tool-descriptor)
describes the UI-template attachment. Those fields do not establish a universal
promise that raw images are hidden in every client. The assistant audience
annotation is a hint. A real ChatGPT visual check is required in addition to
transport tests; do not infer invisibility from omitted template metadata alone.

Synthetic coverage:

```sh
PYTHONPATH=src uv run python -m pytest -q \
  tests/test_image_discovery.py tests/test_mcp.py tests/test_library_auth.py \
  tests/test_image_context.py tests/test_hosted.py
node --test tests/image_viewer.test.mjs
```

These selections do not invoke OCR. Tests cover metadata-only pagination across
55 chapter images, old and new context schemas, invalid bounds and cross-source
identifiers, authenticated repeated inspection with no viewer payload, and the
existing final-display viewer. The transport test does not simulate ChatGPT's
renderer.

Client acceptance procedure: refresh the existing developer connection; inspect
several candidates for an ambiguous chapter without calling `get_image`; verify
the model can describe the pixels while no image cards appear. Then request the
supported selected photo and verify exactly one card. Repeat with a natural
recipe-photo request, and with a request where no candidate matches. Record the
actual tool calls and visible results, not just the assistant's claims.
