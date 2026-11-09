# Reading original books

The library opens books and search matches in `/reader/book-view?at=…`.
PDF.js renders PDF pages from the retained original PDF. EPUB.js renders the
retained EPUB with its publisher CSS, images, fonts, and supported layout.
Reflowable EPUBs adapt to the viewport; they do not promise PDF-like pagination.
Book scripts, forms, popups, and external resources remain disabled.

Formats without an original-book engine, including DjVu, continue to open in
the existing text reader. Retired original links use the same explicit,
source-bound current-publication recovery as text links.

The transcription remains available through **Text view** at `/reader/read`.
Its **Read original** link returns to the same source destination. Existing
original-page comparison and check-region inspection remain separate at
`/reader/original`; their renderer and resource limits are unchanged.

## Navigation

The reader uses the existing library's bounded contents and search results.
A PDF destination opens its first retained physical page. Printed page numbers
are not substituted for physical ordinals. An EPUB destination uses its retained
source document and anchor, or its native source XPath when no anchor exists.
The selected spine occurrence is preserved through rendering, including repeated
chapters and percent-encoded filenames. Anchors must be unique in both source
and rendered documents and, when a retained XPath exists, identify that source
node. Duplicate IDs report an unavailable location rather than choosing the
first matching recipe. Before using an anchorless XPath, the
reader verifies that the rendered body retains the source element and text tree.
If HTML parsing changes that structure, the jump reports an unavailable location
and offers Text view, even if the XPath happens to resolve to another node.
A missing document, anchor, node, or occurrence also reports an unavailable
location; the reader does not report a guessed chapter as a successful jump.

Contents jumps within the same publication and source reuse the open document.
PDF page controls and scrolling operate on original pages. EPUB page controls
use the EPUB engine's pagination. The existing search adapter retains its live
results and query when it mounts either reader. Original-reader contents clicks
are handled once and reuse the mounted engine. Lists beyond the first thirty
entries retain their explicit contents continuation. The original reader includes the existing bookmark and remember-location
controls. Successful mapped contents navigation updates its validated location
and saves the latest section/target; overlapping or unconfirmed writes retain
their original operation identity before the newest navigation is saved.
Saved-location metadata remains at its existing section/target granularity; turning original pages does not
establish exact-page resume or reading completion.

`GET /reader/book-info?at=…` supplies format, title, source identity, the bounded
contents page and the source jump. It does not return transcription text.
Native snapshot/target validation stays in the shared library reading path.

## Source delivery

`GET /reader/source?at=…` accepts the identifier envelope, never a source path or
arbitrary URL. Each request checks the current reader session, retained
publication and selected book/source. The existing verified original cache
supplies the file. PDF delivery supports single byte ranges, suffix ranges and
HEAD requests. Invalid ranges return 416. An open file descriptor keeps a
stream valid if another cache operation removes its directory entry.

Original bytes are delivered only to the authorized browser. They use
`private, no-store`, no-referrer and nosniff. The browser retains the open book
in memory; there is no IndexedDB, local-storage book cache, service worker or
new source download action. Delivering original bytes cannot prevent the owner
from saving bytes already received.

The browser EPUB path admits at most 50,000 ZIP entries, 256 MiB total expanded
size and 32 MiB per member, with distinct member names and the EPUB mimetype.
It refuses unsupported or malformed originals with a text-view recovery action.
These are admission bounds for this browser reader, not changes to OCR or server
renderer ceilings. No ingestion, OCR, inference or native PDF parsing runs in
this delivery path.

The pinned reader libraries and their licenses are bundled in
`src/cookbook/book_vendor/assets.zip`. `assets.json` records the exact permitted
member names and SHA-256 digests; `packages.json` records versions and npm
integrity values. Rebuild with `python3 scripts/vendor_book_readers.py`.
It verifies package integrity and produces a deterministic archive.

Only manifest-listed archive members can be served through the same-origin
public vendor route. No third-party CDN receives book requests. Git and Docker
include only the three vendor artifacts (plus ignore metadata where needed),
excluding local stray copies or loose package directories. The built wheel is
checked for the same restriction.

The reader CSP permits the same-origin worker, generated blob styles/images and
inline layout styles required by the engines. EPUB content is confined to an
iframe sandbox with `allow-same-origin` and without `allow-scripts`, forms,
popups or top navigation. Source scripts stay disabled; publisher CSS remains
inside the iframe. CSP blocks external styles, images, fonts and connections.
PDF scripting and dynamic evaluation are disabled. Expiry/unmount stops the
engines and removes their mounted view through the existing session lifecycle.

## Verification

Run the synthetic preview with `uv run python scripts/preview_reader.py`. It
writes invented PDF and EPUB files outside Git without ingestion or OCR.

With Playwright and Chrome available:

```sh
PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node scripts/verify_original_reader.mjs
```

The check covers original EPUB text and publisher CSS, the iframe sandbox,
contents jumps without another archive request, embedded image decoding,
hostile-book script/network isolation, PDF rendering and page controls, PDF
contents jumps, text fallback, search return, and desktop/390px/320px layouts.
`verify_reader_flow.mjs` still checks the alternate text reader.

`tests/test_reader_book.py` covers authenticated source bytes, HEAD/ranges,
source mismatches, expiry and vendor-directory confinement. The existing
reader search, originals, session, personal-state and text tests remain
applicable. These checks establish local Chromium behavior using invented
books. They do not establish Safari/device coverage, compatibility with every
publication, or hosted deployment acceptance. This change is not deployed.
