# Private browser library reader: implementation handoff

Status: planning specification selected under the owner's expedited decision authority, 2026-11-01. No production reader has been implemented or deployed by this map. Canonical decisions live in their resolution comments; this document is an index and implementation checklist, not another copy of those answers.

## Destination and decisions

The [personal browser library reader map](https://github.com/rickono/cookbook-mcp/issues/87) specifies a private hosted reader for books, keyword search, complete contextual reading and source inspection on desktop, phone and tablet, using the existing live published library and authorization boundary.

| Contract | Canonical decision |
| --- | --- |
| Factual library capability/continuation/image bounds | [Establish the library interfaces and source-reading limits available to a browser reader](https://github.com/rickono/cookbook-mcp/issues/88) |
| Factual hosted identity options and configuration gates | [Establish secure browser access options using the existing library identity](https://github.com/rickono/cookbook-mcp/issues/89) |
| Bookmarks and last reading locations | [Choose bookmarks, notes, and reading-progress scope](https://github.com/rickono/cookbook-mcp/issues/90) |
| Hosted reader versus local dashboard | [Choose how the hosted reader and local dashboard fit together](https://github.com/rickono/cookbook-mcp/issues/91) |
| Search scope, grouping, matching and coverage | [Choose browser search behavior and result coverage](https://github.com/rickono/cookbook-mcp/issues/92) |
| Source fidelity, reports and publication changes | [Choose source fidelity, uncertainty, and publication-update behavior](https://github.com/rickono/cookbook-mcp/issues/93) |
| Authentication, state, storage and report delivery | [Choose browser sessions, personal-state storage, and content caching boundaries](https://github.com/rickono/cookbook-mcp/issues/94) |
| Responsive interaction and selected prototype | [Choose the browser search and reading experience across screen sizes](https://github.com/rickono/cookbook-mcp/issues/95) |
| Release acceptance and verification evidence | [Agree the browser-reader acceptance criteria and implementation handoff](https://github.com/rickono/cookbook-mcp/issues/96) |

## Prototype asset

Open [library-reader.prototype.html](prototypes/library-reader.prototype.html) directly in a browser. It is a single offline file containing only invented material and in-memory simulated actions. Layouts are selected with `?variant=A`, `?variant=B` and `?variant=C`; the floating switcher and scenario selector belong only to the prototype.

Selection: A Focus is the default; borrow B's optional original/text comparison on wide screens and C's explicit large-type kitchen mode. The canonical interaction decision explains the responsive behavior and omissions. The prototype is primary planning evidence, not a tested backend, a complete visual system or a production implementation to promote wholesale. The owner delegated the selection; no owner device usability test has occurred.

## Implementation order

1. Recheck current source/deployment contracts against the two factual inventories. Configure the selected web client, same-origin hosted routes, protected server-side session store and existing owner authorization. Do not expose content until authorization checks pass. Keep the MCP and local dashboard boundaries intact.
2. Add a thin browser-facing adapter over existing catalog, keyword search, content/section reading, continuations and bounded source delivery. Reuse library selection, locators and withdrawal checks; do not build a second index, ingestion pipeline or source model. Establish actual browser image delivery and continuation/version error behavior.
3. Implement the selected responsive browse/search/read/source journeys, publication-update and old-link handling. Render source material safely and preserve uncertainty and incomplete-content states.
4. Add durable source-bound personal metadata and isolated owner-report intake. The existing agent-report contract cannot encode description-only owner observations; do not fabricate proposals or send incompatible records into legacy triage. Keep library access read-only and review execution outside the reader.
5. Prove the release checks in the acceptance decision, capture source-safe verification metadata and hand off deployment separately. Configuration and device checks are implementation work, not open product decisions on this map.

## Verification checklist

The acceptance ticket defines exact pass/fail criteria. Its evidence must include:

- Unauthorized/wrong-owner/wrong-scope/expired access; OAuth transaction checks, server-held credentials, CSRF, restart/refresh/renewal/logout lifecycle and absence of persistent content caches.
- Catalog, both search groups and independent continuations; query/result-position restoration; honest no-match/partial/failure states and supported filters.
- Complete section/chapter continuation, separate related-record navigation, source citations, physical versus printed pages, uncertainty and corrections, check regions and bounded image success/refusal paths.
- Open-view updates, unavailable old publications, current withdrawal and reliable versus unavailable saved-location matching without edition substitution.
- Two-device bookmark/resume behavior; description-only report receipt after confirmed durability; retry after ambiguous timeout; render failure independent of report submission; no source mutation or automatic review from a report.
- Desktop/tablet/phone layout, keyboard/screen-reader operation, text zoom, tables and orientation; measured feedback/search/reading/image completion or bounded failure using the acceptance workload.
- Existing MCP and dashboard regression checks appropriate to changed code, with no OCR-triggering tests outside the required isolation boundary.

Synthetic fixtures cover failure injection, hostile markup, unusual structures, version transitions and persistence races. An authorized hosted smoke check proves browser login and rendering; mock results cannot substitute for it. Keep books, source passages, images, private paths, credentials and raw incident evidence outside Git/GitHub. Before any PDF/DjVu ingestion, OCR, inference or scan experiment, follow `docs/ocr-resource-isolation.md` and `scripts/ocr_sandbox.py`; this handoff authorizes none of those operations.

## Scope boundary

Implementation and deployment follow separately. No new semantic ranking, AI answers, annotations, reading-history UI, completion tracking, offline content/downloads, source editing, processing/publication/review controls, shared accounts or dashboard content viewer. The separate zoom incident remains separate; a reader may show a truthful supported rendering refusal without claiming that incident is fixed.
