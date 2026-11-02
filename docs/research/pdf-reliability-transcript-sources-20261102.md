# Retained transcript sources and edition alignment

Research for [Assess better transcript sources and edition-alignment limits](https://github.com/rickono/cookbook-mcp/issues/113), within [Make PDF transcription and assembly reliably source-faithful](https://github.com/rickono/cookbook-mcp/issues/110). Completed during the November 1 local session for the November 2 planning effort.

Retained page reads, frozen scanned candidates, embedded-text surveys, and source-selection receipts provide evidence to inspect before commissioning expensive rereads. This investigation establishes reference categories and their limits. It does not identify a verified superior transcript or establish whole-book fidelity. Detailed candidate metadata stays private. [P1–P6]

The owner confirmed that the first audit includes all currently published PDFs and known local candidates. Discovery includes retained outputs, embedded PDF text, matching local EPUB editions, and legitimate publisher or author sources. The destination is a specification and repair plan with measured acceptance criteria. This report supplies evidence prerequisites, not measured acceptance results. [Ticket](https://github.com/rickono/cookbook-mcp/issues/113)

## Retained evidence

Saved catalog and snapshot exports retain format metadata and source hashes. Later batch manifests, candidate manifests, and publication registries provide additional source-to-candidate references. They are historical receipts. This worker did not query the active service, establish the authoritative published estate, or infer activation from directory names. The estate investigation must reconcile these references against its published set. [P1, P3]

Saved page records retain image hashes, reader text and calls, final text, regions, crops, and corrections. They can distinguish a reading error from a later assembly error without repeating inference. Candidate manifests retain source identity, reader and assembler metadata, coverage, approval labels, and file references. Their presence does not prove that their text is correct or all referenced files remain intact. This pass inspected metadata and selected saved-record structure, not every response or candidate body. [P3, P4]

Saved surveys identify text layers with omissions and layout hazards. An embedded layer can contain substantial text while losing a quantity or the association between columns. Other retained receipts describe source selection, excluded scans, printed-page mappings, and missing scans. These are evidence of source limitations that clean text alone cannot resolve. No new source rendering or visual assessment occurred. [P2, P5]

The local catalog filename check found no PDF–EPUB pair within one catalog directory. A bounded title search found no convincing matching EPUB for the provisional PDF sources. Its loose matches were different works. This finding does not establish that an equivalent edition is absent from every snapshot, differently named record, or external catalog. Catalog IDs and title overlap remain discovery aids. [P1, private assessment]

## What each reference can establish

| Reference | Usable evidence | Evidence still required before reuse |
| --- | --- | --- |
| Retained page read from the same source | What the earlier reader returned, before assembly | Exact source and page binding, response validity, visible-source comparison, unresolved spans |
| Frozen scanned candidate | A reproducible assembly and its declared coverage | Candidate digest and file integrity, source identity, completeness and order review, retained uncertainty |
| Embedded PDF text or saved extraction | A search aid and alternate reading hypothesis | Visible-page agreement, quantities and units, column order, captions, tables, and omissions |
| Matching local EPUB | A potentially clearer representation of the same work | Edition, printing, language, volume, formulation, and explicit page-to-passage alignment |
| Publisher digital edition or author material | An authorized availability lead or bounded corroboration | Actual access terms, permitted use, edition alignment, and demonstrated coverage of the disputed content |
| Publisher errata | Evidence that printed source content differs across printings | Applicable printing and a separate record of the source-printed inconsistency |

These are proposed evidence requirements derived from the retained failures and the repository's source-binding contracts. They are not a new approval policy. The build currently prefers an available EPUB; that selection rule does not prove equivalence with a PDF. EPUB extraction follows the spine and retains document locators, while scanned-candidate validation binds the source hash and physical-page count. Those structural contracts do not establish content fidelity. [Build selection](https://github.com/rickono/cookbook-mcp/blob/0384b358d2f51e5ef2ad54c64e72f4291366adf0/src/cookbook/build.py#L109), [EPUB extraction](https://github.com/rickono/cookbook-mcp/blob/0384b358d2f51e5ef2ad54c64e72f4291366adf0/src/cookbook/extract.py#L63), [candidate validation](https://github.com/rickono/cookbook-mcp/blob/0384b358d2f51e5ef2ad54c64e72f4291366adf0/src/cookbook/scanned.py#L283)

## Legitimate external references

A bounded documentation search found a licensed fixed-layout digital edition offered by a commercial reading platform. Its listing supplies separate print and digital identifiers. That establishes an availability lead, not possession, export rights, an unrestricted EPUB, or equivalence to a local PDF. Candidate-specific metadata and its access prerequisites remain private. No purchase, registration, download, or extraction occurred. [Provider's own listing](https://www.vitalsource.com/en-uk/products/the-professional-chef-the-culinary-institute-of-v9781118558638)

Modernist Cuisine's publisher says it does not plan digital editions and that its former Inkling app is no longer sold or updated. An old app reference therefore does not establish a current obtainable transcript. Its official documentation describes printing-specific changes and explains how to identify printings. Even the same named edition can contain different authored text. [Publisher FAQ](https://modernistcuisine.com/contact/), [printing identification](https://modernistcuisine.com/mc/which-printing-do-you-have/), [official errata history](https://modernistcuisine.com/mc/to-err-is-human/)

Publisher errata can explain an apparent discrepancy without making it a transcription error. A faithful transcript preserves what the selected source prints. Any annotation about a later correction remains separate. Public availability also supplies no automatic permission to acquire, upload, or republish content. No general rights conclusion is made here.

## Alignment and remaining decisions

A usable alignment record needs the original source hash, candidate or extraction identity, exact reference version, and a mapping between physical pages and reference locations. Printed numbers alone fail for spreads, omitted scans, reordered pages, and inserted material. A matching recipe title alone cannot establish which historical passage, formulation, ingredient quantity, table column, or continuation belongs with it. [P2, P5, P6]

Inference: the least wasteful next step is to reconcile retained references with the authoritative estate, then inspect aligned evidence before selecting pages that need new reading. Reassembling retained text may address some failures, but this investigation did not execute or validate such a repair. References generated by the same reader or reused from the candidate are not independent missed-error controls. [P3, P4, P6]

The owner explicitly authorized one local alternate-provider Heston retry despite earlier blanket refusal language. Its saved receipt describes an unreviewed response, no candidate change, and no publication. This worker made no call. Older policy remains historical evidence; the general fallback policy remains a human decision. All Heston repair stays local. [Map notes](https://github.com/rickono/cookbook-mcp/issues/110), [P6]

Still open are acceptable alignment evidence for reuse, approval authority, general fallback limits, permitted external transport and access, and the independent reference set and measured thresholds for later comparison. Discovery scope is settled. No source parsing, OCR, paid inference, source acquisition, repair, correction-ledger change, upload, or service change was performed. Later source processing requires the unchanged resource-isolated launcher. [Resource boundary](https://github.com/rickono/cookbook-mcp/blob/0384b358d2f51e5ef2ad54c64e72f4291366adf0/docs/ocr-resource-isolation.md)

## Private primary evidence

The evidence pointer is `/Users/rick/cookbook-mcp-data/planning/pdf-reliability-wayfinder-20261102/transcripts/`.

- `assessment.private.md` identifies P1–P6, candidate-specific availability leads, rejected matches, and limitations.
- `candidate-sources.private.json` records provisional source metadata, retained candidate and registry references, local format filename metadata, receipt hashes, and current root-code hashes.
- `discover.py` records the metadata-only collection procedure. No book parser or live SQLite catalog was used. The assessment records the subsequent rejection of loose title matches.

The separate root checkout was read only. Its observed HEAD was `0384b358d2f51e5ef2ad54c64e72f4291366adf0`. The cited implementation files matched that revision. Current AGENTS.md, CONTEXT.md, and PDF-workflow guidance included uncommitted or untracked changes, whose hashes were retained privately. No dirty code was copied. No test or benchmark was needed for this documentation-only discovery.
