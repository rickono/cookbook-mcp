# Protected original inspection

The default full-book PDF/EPUB reader is documented in [Reading original books](original-book-reader.md). This page describes the separate bounded page/image inspection and comparison tool.

Implements [Inspect original pages, images and check regions](https://github.com/rickono/cookbook-mcp/issues/102)
under #98. Session, shared Library and reading contracts remain those in
[hosted-reader.md](hosted-reader.md) and [reader-content.md](reader-content.md).
This is code and synthetic HTTP/DOM verification, not observed browser/device or
hosted acceptance. The separate high-resolution zoom investigation (#67) remains
unresolved by this slice.

`GET /reader/original?at=…` lists at most twenty associated originals, without
rendering them. `at` is the existing identifier-only reading envelope. Explicit
selection adds `page=<physical ordinal>` or `image=<retained image ID>`, with the
original-list `offset` retained. Each selection produces one protected `<img>`
pointing to `GET /reader/image` with the same identifiers. No source path, arbitrary
URL, browser-selected rectangle, edge size or publication fallback is accepted.
The ordinary reading action follows the latest successfully loaded text chunk.
Return links preserve that exact envelope and focus the text anchor.

Scanned sections retain their `physical_pages` order, including spreads. A page
locator names its physical ordinal. Printed labels remain unverified; the citation
is disclosed with the image. Check-region controls are an ordered, labelled list,
with returned normalized `[left, top, right, bottom]` geometry and independent
unresolved/crop-confirmed wording. Selecting a region forwards its stored box
unchanged to the shared Library renderer; changing the page refuses a foreign
region. Crop confirmation and applied corrections do not establish approval.
Current withdrawal withholds comparison text while permitting existing original
access; no text is copied from the page-render metadata into the browser response.

Legacy EPUB sections reuse `list_images` in retained order. Whole-book native
locations first validate the source, target, snapshot and occurrence using the
bounded native read, then list image rows associated with the returned source
documents. These are document associations, not recipe-photo matches. Missing
associations remain unavailable. Native images do not promise facsimile pagination,
original EPUB CSS, or transcription of text inside images.

Browser delivery admits only verified JPEG, PNG and WebP rasters, at most
3,000,000 encoded bytes and 16,000,000 pixels. Active/vector formats and invalid
images are refused; filenames/extensions do not set the MIME type. Scanned page
and crop responses use the existing fixed 1,600-pixel output edge. Crops retain the
existing 2,400-pixel intermediate render ceiling. There is no high-resolution size
picker. Linux renderer admission, exclusive nonqueued slot, subprocess limits,
15-second renderer deadline and cleanup remain unchanged. No OCR boundary or
resource ceiling was changed. A request/client timeout does not cancel a running
worker or prove resource isolation.

Every protected endpoint uses current reader authorization, exact HTTPS origin,
private no-store, nosniff, frame denial and no-referrer. CSP adds only same-origin
image delivery; source scripts and external resources stay prohibited. Runtime
storage caching remains the existing verified server cache. There is no browser
content persistence, download action, external image URL or service worker.

The selected original has an optional comparison toggle at 1,100 CSS pixels and
above. Toggling reveals the already delivered bounded text chunk; it makes no
additional image request. Narrow views have an explicit return to the same text
location. Image controls have persistent labels, normal 44-pixel primary targets
from the shared reader stylesheet, visible focus and status announcements. The
separate CSS/JS files allow #106 to layer kitchen presentation without changing the
selection/delivery contract.

Image loading settles on load/error or a thirty-second client deadline. Success
wording requires an image load with nonzero decoded dimensions. Failure removes the
image source, retains text and offers explicit retry, supported whole page and text
return. No automatic retry or increasing-size loop runs. The server request budget
is thirty seconds for pixels and ten seconds for metadata; failures are redacted
and preserve recovery links. Session checks clear the protected document when
access expires; already delivered pixels cannot be recalled.

Verification uses hand-authored synthetic publications, native artifacts, raster
fixtures and injected serving-render outcomes. `tests/test_reader_original.py`
covers HTTP delivery, auth/expiry, exact return, source/snapshot/region refusals,
physical order, crop geometry, busy recovery, withdrawn text with original access,
active-format refusal and privacy. `tests/reader_original.test.mjs` exercises
load/error/timeout/cached-image states and comparison with a simulated DOM. These
checks do **not** establish browser-visible rendering or an accessibility audit.

Remaining release proof under #98: observed supported image success through the
assembled application in Safari/Chromium and phone/tablet Safari, keyboard and
VoiceOver, 320px reflow and zoom/orientation, real hosted authorization/renewal with
the Mac off, Linux serving enforcement and the specified hosted performance/failure
budgets. Record versions and source-safe identifiers; keep private/raw evidence
outside Git. A refusal does not count as successful image delivery.

## Repeated page requests

The shared `Library.get_page` path retains verified JPEG bytes in a private,
process-local LRU. It retains at most 8 MiB and 32 entries, creates no raster disk
cache, and forgets its entries on restart. `raster_cache_bytes=0` disables reuse
for comparisons; the constructor rejects budgets above 8 MiB. Original-file cache
and renderer limits are unchanged.

Keys include the current manifest's original hash and size, the source hash,
format, physical page, normalized region, output and intermediate edges, and JPEG
quality. A changed source or setting requires a new render. The in-memory cache
cannot survive a renderer code or dependency update. Only completed, raster-checked
JPEGs enter the LRU. Oversized entries and failures are not retained.

Every request still validates its session, source selection and retained
publication, and applies current withdrawal policy. Metadata and transcription
are rebuilt, never cached with pixels. The current policy can withhold
transcription while still allowing original access. A retired publication or an
expired or revoked session cannot use a warm raster to obtain delivery. Hits still
pass browser raster admission and return `private, no-store`.

The existing exclusive nonqueued render slot owns the LRU as well as rendering.
Hits retain the same busy refusal when that slot is occupied. This intentionally
preserves contention behavior. No new queue, worker, browser storage or resource
ceiling is introduced.

Request diagnostics add closed stage names for source validation, original-cache
verification, rendering, encoding, fresh metadata, raster admission, response
construction, and raster hits or misses. They contain durations and counts, with
no cache keys, source identifiers, paths or content. Nested stage durations are
inclusive and must not be summed. `original_response` measures construction of
the response object; it does not measure network delivery or browser paint.

See [the raster reuse verification](reader-raster-verification.md) for the
repeatable synthetic profile and its evidence limits.
