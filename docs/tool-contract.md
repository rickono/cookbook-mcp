# Proposed read-only MCP tool contract

Stage 1 proposal based on the verified Calibre snapshot. Tool names and field shapes below are for review, not implemented or approved final schemas. Response-size limits and artifact behavior must be established by the local and ChatGPT POCs before finalizing the API.

## User-facing behavior

Search returns a short list of source-grounded matches. Each result identifies its book, exact source format/version, section or physical page, and publication. Follow-up reading uses these returned IDs rather than reconstructing file paths from titles. Recipes are labeled as such only when source structure supports a bounded recipe; otherwise return the containing section and describe the structural limitation.

All catalog and content calls require OAuth and the allowed user identity. Tool exposure is restricted to the selected food/wine records even though the backup contains the complete library. Original backup databases and manifests are administrative restore artifacts, not MCP resources that could bypass the selection boundary.

The user approved reviewing new books during the single publish command and remembering inclusion choices outside Calibre. Group byte-identical admitted sources into one search result while retaining their corresponding Calibre record identities; editions with differing bytes and merely similar titles remain separate. Original records/files stay in the backup. Source-library deletion is a separate, currently unauthorized operation.

## Common identifiers and results

- `publication_id`: identifies one immutable published inventory. Follow-up tools require it; initial search may default to the active publication and must return the selected ID.
- `book_id`: stable opaque identity derived from library and book UUIDs; retain Calibre's numeric ID as a labeled compatibility field. Do not expose local absolute paths.
- `source_id`: identifies exact original-file bytes by content hash plus an explicit format. Shared bytes need not imply merging Calibre records.
- `section_id`, `page_id`, `image_id`, `artifact_id`: opaque identifiers resolved through the selected publication's inventory, never arbitrary filesystem paths or remote URLs.
- `citation`: book title, authors, source identity/format, publication ID, source locator, and section title or physical page ordinal. Verified printed page labels are separate fields.
- `extraction`: distinguish native source text from OCR text, identify the extraction/locator algorithm version, and report known coverage or structural limitations.

Every successful tool returns structured data plus concise model-readable text. Error results have stable machine-readable codes and safe summaries without passages, credentials, local paths, or upstream secrets. Unknown or disallowed identifiers must not disclose hidden catalog records. A pruned publication yields an explicit unavailable-publication result, never a silent substitution from a newer version.

## Tools

| Proposed tool | Inputs | Bounded result |
| --- | --- | --- |
| `search_library` | `query`, `mode` (catalog or full text), optional author/tag/format filters, optional `book_ids`, optional `publication_id`, page size and cursor | Matches with short snippets, relevance information, book/source IDs, section/page IDs, and citations. `book_ids` handles within-book search without a separate tool. |
| `get_book` | `publication_id`, `book_id`, optional `source_id`, TOC cursor/page size | Selected catalog metadata, available source formats, extraction coverage, and a paginated hierarchical TOC with usable section/page IDs. |
| `read_section` | `publication_id`, `book_id`, `source_id`, `section_id` or returned passage locator, bounded length and continuation cursor | Source-ordered text, associated image references, citation, and a continuation when the section exceeds the bound. Recipe boundaries are source-grounded rather than guessed. |
| `get_page` | `publication_id`, `book_id`, `source_id`, `page_id` or explicit physical page ordinal, bounded rendering request | One PDF/DjVu page: original page rendition, page text when available, OCR provenance, source identity, physical ordinal, and verified printed label if present. |
| `get_image` | `publication_id`, `book_id`, `source_id`, `image_id`, bounded rendition request | One image/diagram with its source location, nearby caption when attributable, and citation. Image bytes are delivered within the authenticated MCP interaction if ChatGPT supports the tested format. |
| `get_artifact` | `publication_id`, `book_id`, `source_id`, `artifact_id` | Metadata and, where demonstrated practical in ChatGPT, a selected original page/section artifact or original source file. Large-file delivery remains POC-gated. A service must not silently replace authentication with public or presigned URLs. |
| `get_publication_info` | optional `publication_id` | Authenticated publication ID, schema/locator versions, activation status, supported formats, and safe diagnostics. No complete backup inventory or excluded-book metadata. |

Pagination and continuations must stay pinned to a publication. The POC will determine whether stateless Streamable HTTP works for all selected output types; do not add session storage without evidence of need.

`get_image.caption` contains source-supplied text: an enclosing figure's caption,
falling back to the image's alt text. `recipe_context`, when available, separately
returns the title and section ID of a nearby structurally recognized recipe in
the EPUB's document order. This is navigation context, not a verified visual
description or an exact recipe-to-photo match. The viewer labels that distinction
and does not substitute the recipe from the user's search for the photo's source
context. Older publications without context remain readable.

## Citation rules already selected

EPUB locations use exact source identity, the package's real reading order, internal document path, anchor or deterministic text position, and a versioned locator algorithm. Store the source mapping with the publication so later extractor changes cannot silently reinterpret an older locator. These are service-resolvable positions, not promised EPUB CFI links.

PDF and DjVu pages use physical file ordinals starting at one. Preserve scan order and spreads. A spread is one physical source page unless an explicitly requested derived view is also returned with a mapping to that original page. Never invent printed page labels or treat OCR-recognized labels as verified without validation.

OCR text supports search and reading, but the original page remains available for checking uncertain words, fractions, units, and quantities. Book files and source metadata stay unchanged in Calibre.

## POC gates and unresolved choices

- Validate authenticated image blocks and page images in ChatGPT, separately from the MCP Inspector/client. Determine original PDF/EPUB artifact behavior experimentally; neither embedded binary resource support nor automatic protected-URL fetching is assumed.
- Test EPUB 2/3 TOCs, spine order, anchors, missing anchors, recipe boundary heuristics, nested sections, image captions, and continuation/citation round trips.
- Test PDF/DjVu page identity, image-only English scans, mixed text/image documents, OCR failures, and source-image verification.
- Verify unauthorized/expired/wrong-user/wrong-audience requests and arbitrary-ID/path attempts cannot reach any catalog, text, image, or artifact.
- Measure results at 100+ books with representative synthetic diversity or user-approved additions; do not infer rendering RAM from catalog size.
- Establish exact search semantics, preferred format when multiple formats exist, recipe labeling rules, and response bounds before final schema approval. New-book selection during publishing and byte-identical duplicate grouping are approved.

The schemas carry publication/source IDs now so the transport/content POC can change delivery details without discarding citation provenance. No upload or endpoint is required to review this document; testing actual ChatGPT behavior will require the separately approved hosted test subset.
