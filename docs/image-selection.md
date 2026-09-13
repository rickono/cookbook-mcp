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

## September 13 deployment and client results

Deployed `server.py` and `library.py` as a layer over the existing runtime:
`registry.fly.io/cookbook-agent@sha256:56b8b9c098d74dffc0ce690464f8eee2fa3f132da6d8772bc2781ece1bda23ab`.
The existing Machine's configuration differs only in image; environment,
startup, resources, services, volume, and restart policy are unchanged. Hosted
module hashes match local source. Health returns OK; anonymous MCP/readiness
requests return 401. The active publication and manifest remain those recorded
in [full EPUB publication](full-epub-publication.md).

The 25 focused Python tests and five JavaScript viewer tests pass, as do Ruff F
checks and formatting. The Linux/amd64 deployment image passes an isolated,
bounded import check. No OCR, PDF/DjVu ingestion, or book publication was needed.

The existing ChatGPT connection was refreshed to discover all nine tools:

- In the [inspection acceptance chat](https://chatgpt.com/c/6aa6dac1-e4dc-83ea-9cac-1df412030181),
  the tool-call panel confirms eight `inspect_image` calls for the ambiguous
  Ottolenghi Simple meat chapter, plus search, candidate listing, and source
  reading. The assistant could describe uncaptioned pixels and reject several
  unrelated dishes. The completed turn contained zero image viewers, confirmed
  by the rendered DOM and screenshot. An explicit viewer request subsequently
  displayed one shared table photo, with the chicken on the left. A subsequent
  no-match request about a blue-frosted cake among the inspected candidates
  returned a negative answer and added no viewer (the total stayed at one).
- In a fresh [natural photo request](https://chatgpt.com/c/6aa6db7c-8db8-83ea-b344-4ae9c18d326a),
  the prompt named the tomato salad and book without specifying tools. The
  observed sequence was resource discovery, `search_library`, `list_images`,
  `inspect_image`, `get_image`. Exactly one matching salad photo appeared,
  verified in the rendered page and screenshot.

One chicken follow-up initially received a ChatGPT copyright refusal without a
tool call. Clarifying that the request was to open the already-supported private
library viewer succeeded. This model behavior is distinct from candidate-card
clutter; the natural salad request required no clarification. The existing
developer connection showed its pre-existing CSP-off override throughout these
checks; no security setting or template/CSP code was changed. These are desktop
ChatGPT observations, not a promise about every MCP client or mobile renderer.

Private deployment configuration, rollback, module copies, and acceptance
metrics are under `~/cookbook-mcp-data/setup/image-selection-20260913/`.
