# Try the reader locally

Run from this checkout:

```sh
uv run python scripts/preview_reader.py
```

Open [the sample library](http://localhost:8766/reader/login). Sign-in is simulated
automatically. The actual reader opens original PDF and EPUB files by default and serves three invented books: The Weeknight Table,
A Small Seasonal Kitchen, and The Soup Notebook. Try searching for `lemon`, opening
a recipe, saving a bookmark, and inspecting an original. The soup
sample also offers unresolved content, a check region, and transcription reporting.
The longer supper passage exercises EPUB pagination and automatic continuation in the alternate text view. See [the original-book reader](original-book-reader.md) for source delivery and verification.

The process listens only on IPv4 loopback and accepts only `localhost:8766`.
It remains running until you press Ctrl+C. Bookmarks and reports are stored
separately under `~/cookbook-mcp-data/previews/reader-spec98`, outside Git. A restart
requires a fresh simulated sign-in; saved metadata stays available.

This is a development adapter around the production reader routes, with local
synthetic identity, publications, metadata stores and pre-created page images.
Section search is real SQLite retrieval. The richer Content index has no native
artifact/Typesense service in this preview and is truthfully unavailable.
No book parsing, ingestion, OCR or model inference runs.

For this synthetic loopback demo only, the adapter translates HTTP to the internal
HTTPS origin, maps cookies to separate HttpOnly demo-cookie names, and simulates
the external provider callback. It rejects foreign hosts, non-loopback clients and
foreign mutation Origins. It loads no production environment credentials and
changes no production authentication code or host certificate trust. Never deploy
this adapter or use it to serve private books. It demonstrates the interaction and
layout; it does not prove hosted TLS, real identity-provider behavior, native search,
cloud-storage durability, Mac-off operation, device accessibility or performance.

## UI polish

The reader uses a warm paper palette, serif reading typography, a shared library
header, a book shelf, and consistent search and bookmark layouts. Reading tools
sit beside the text on wider screens and follow it on narrow screens. Source and
account details are expandable; uncertainty and save/failure acknowledgements
remain explicit. Kitchen mode was removed at the owner's request.

Local Chrome checks exercised the catalog, search, a search-mounted recipe,
bookmark saving and search return, saved places, and decoded sample originals.
Reading reflow was checked at 390px and 320px; the 320px page had no horizontal
page overflow. These synthetic local checks do not establish hosted/device or
VoiceOver acceptance. A regression fixes body-declared reader enhancements being
lost when search adopts parsed reading nodes, so mounted bookmark/report forms
initialize rather than falling through to a normal form submission.
