# Local cookbook dashboard

The dashboard observes explicitly configured metadata. It never processes books,
changes membership, reviews text, retries work, publishes, or probes source content.
It works offline and keeps unsupported or failed observations unknown.

## Launch

From the repository:

```sh
PYTHONPATH=src uv run python -m cookbook.cli dashboard
```

This opens `http://127.0.0.1:8770/` and runs until interrupted. Default configuration
is `~/cookbook-mcp-data/dashboard/config.json`. Use `--config PATH`, `--port 8771`
or `--no-browser` as needed. An installed package also offers `cookbook-dashboard`.

For a disposable synthetic inventory:

```sh
PYTHONPATH=src uv run python -m cookbook.cli dashboard --demo
```

No Docker, OCR, source books or external frontend services are needed. The page
uses locally packaged styles and JavaScript. The server binds only to loopback,
rejects non-loopback hosts and cross-origin requests, escapes metadata, disables
browser caching and offers no arbitrary file-serving or library mutation routes.

## Private configuration

Store configuration, registry, status projections and snapshots outside Git. All
paths resolve relative to the configuration file. Input files must be outside the
dashboard storage directory. There is no recursive experiment discovery.

```json
{
  "version": "dashboard-config.v1",
  "storage": "state",
  "sources": [
    {"id": "intent", "kind": "registry", "path": "intended-books.json"},
    {"id": "catalog", "kind": "calibre", "path": "/private/catalog/metadata.db"},
    {"id": "candidate-A", "kind": "candidate", "path": "/private/run/candidate.json", "edition": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    {"id": "retained-index", "kind": "index", "path": "/private/build/index.sqlite", "publication": "synthetic-publication-A", "historical_at": "2030-01-01T00:00:00Z"},
    {"id": "build", "kind": "build_report", "path": "/private/build/build-report.json"},
    {"id": "status", "kind": "status", "path": "status.json"}
  ],
  "usage": [],
  "owner_queue_complete": false
}
```

`historical_at` marks retained evidence explicitly historical even after a fresh
file read. Reading a retained publication index does not establish that it is
currently serving. Without this flag an index still establishes only catalog
presence in its bound publication, never current access.

Supported readers:

- `registry`: authoritative intended-book registry, described below.
- `calibre`: read-only catalog UUID and book UUID/title discovery. Discovery has
  provisional identity without a trusted source hash. A known catalog UUID alone
  does not establish that current bytes match an earlier edition.
- `index`: read-only transaction over publication/book/source metadata and section
  counts. No section text, images, original paths or recipe content is selected.
  Optional publication binding must match. This is metadata-only inspection, not
  manifest/payload checksum validation or proof of content eligibility.
- `candidate`: only the scanned-candidate.v1 manifest. The manifest-byte digest
  binds declared page coverage to the candidate; payload files are never opened.
  Optional edition binding must match. Declared counts do not approve content.
- `build_report`: scanned-build-report.v1 declared page counts, correction stages
  and safe owner-queue identifiers. Embedded correction text is not projected.
- `status`: dashboard-status.v1, an explicitly prepared safe metadata projection
  for scoped review/access/processing facts, queue origins, blockers, correction
  stages, attempt history and worker heartbeats. Raw review/report stores contain
  content and are deliberately not dashboard inputs. Missing producers stay unknown.
- `remote`: optional metadata-only MCP observation, described below.

Each JSON input is limited to 16 MiB, catalog/index inventory to 10,000 records,
and configuration to 256 independently registered sources. SQLite opens in
`mode=ro` with `query_only` and a transaction; missing databases are never created.
An unsupported schema, binding mismatch or malformed input fails that observation
without discarding the other sources.

## Intended-book registry

```json
{
  "version": "intended-book-registry.v1",
  "records": [
    {
      "namespace": "synthetic:catalog-A",
      "record_id": "book-uuid-A",
      "title": "Synthetic pantry",
      "format": "PDF",
      "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "membership": "included",
      "evidence": "owner selection receipt A",
      "holds": [{"scope": "publication", "reason": "owner review pending"}],
      "missing": false
    }
  ]
}
```

Membership is included, excluded or undecided. The owner or an explicitly instructed
agent maintains this private registry outside dashboard refresh. A hold has its own
scope and reason and does not enforce a restriction. Missing sources do not remove
intended books. Trusted source hashes group aliases; absent hashes retain a
namespaced provisional identity. Opposing included/excluded claims remain a conflict.
The same integer in different namespaces never joins records.

## Safe status projection

```json
{
  "version": "dashboard-status.v1",
  "facts": [
    {
      "edition": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "dimension": "review",
      "state": "partial agent approval",
      "candidate": "candidate-A",
      "scope": "pages 1-3",
      "authority": "validated agent review policy",
      "evidence": "review-receipt-A"
    }
  ],
  "queue": [],
  "blockers": [],
  "history": [],
  "corrections": [],
  "heartbeats": []
}
```

Fact dimensions are processing, review, publication, access and eligibility. Facts
retain candidate/publication/scope/authority/evidence, rather than a global
complete flag. Queue entries identify `id` or `report_id`, `edition`, `origin`,
`outcome` and evidence. Copies deduplicate by report identity; contradictory
outcomes remain visible. Build correction identities remain separate from report
identities. Unattributed work cannot be assumed absent.

Blockers/history/corrections retain edition, scope, evidence, reason, event time,
candidate/publication and stage where applicable. Correction stages should distinguish
decided, local application and observed publication application. A heartbeat has
edition, run, worker, phase and numeric UTC epoch `at`. After 120 seconds it reads
“heartbeat overdue”; an unreadable or stale source makes activity unknown.

`owner_queue_complete` defaults false. Set it true only when all required safe
backlog projections are configured, complete and authoritatively scoped. An
unreadable/stale configured source always makes the total unknown. Current blockers
and attempt history remain separate; terminal refusal supplies no retry control.

## Refresh, storage and freshness

Local readers start every 30 seconds, remote readers every five minutes. Manual
refresh coalesces in-flight work. Sources run independently with five-second local
and 20-second remote admission deadlines. At most one daemon read per source can
remain in flight; a timed-out read cannot multiply on later refreshes and its late
result never establishes a fresh observation. The deadline bounds observation
admission, not cancellation of an underlying OS filesystem syscall.

Local evidence becomes stale after 60 seconds, remote after ten minutes. A failed
read immediately makes current state unknown while retaining dated prior evidence.
Each snapshot is assembled under one lock; the stores need not have been read at
the same moment. On launch and wake, overdue readers refresh without replaying
missed intervals. The browser refreshes the view every 30 seconds while visible,
pauses while editing filters and requests refresh on returning to the page.

Dashboard-owned storage is limited to 100 MiB and change history to 30 days. Oldest
history is pruned first, current snapshot is replaced atomically, and failure leaves
the previous persisted snapshot intact with a visible storage error. These limits
never prune source records. Restart loads previous evidence as unknown until read
successfully. Observation history is retained locally; it is not activity history.

## Optional remote observation

Add a `remote` source with `endpoint` equal to the configured MCP audience and
launch with `--remote-login`. The existing publisher PKCE environment configuration
is used. JWT verification and browser login are existing code paths; credentials
stay in server memory and expire without persistence. Offline/local operation does
not require login or remote configuration.

The remote reader calls only `get_publication_info` and `search_library` in catalog
mode, pins every continuation to the observed publication and rejects changed
versions or invalid pagination. It does not call content tools, submit reports,
activate publications or infer restrictions from catalog presence. Current remote
restriction and report-backlog interfaces remain capability gaps and access stays
unknown. Expired/missing credentials fail only that observation. Reauthenticate by
restarting with `--remote-login`; no token is sent to the browser page.

## Optional retrieval producer

Set `COOKBOOK_USAGE_DB` in the **serving process**, pointing to a private writable
SQLite path. Restart that process using its normal operational workflow when you
choose to enable collection. Adding the same path to dashboard configuration's
`usage` list enables its read-only analytics consumer. The dashboard never creates
this producer database. A hosted producer's private event database is not reachable
from this Mac automatically; transport/export requires a separate supported source.
No production serving process is restarted or deployed by implementing this feature.

The existing MCP tool wrapper records completed operations, including errors.
Catalog enumeration is excluded to keep dashboard observation out of usage.
Search appearances count each returned edition once per response; search calls
count once even for multi-edition results. Nonempty section reads are successful
unless withheld by withdrawal/supersession evidence. Continuations and identical
repeated invocations are separate calls. Only identical event-ID deliveries
deduplicate. Page and region zoom, image inspection and image display are distinct.

Events retain only random event ID, UTC completion time, allowlisted operation,
outcome, bounded duration, opaque publication/source/book/target references and
continuation/zoom flags. No query, content, image bytes, region coordinates,
credentials, IP address or personal identity is retained. Original source identity
attributes aliases together without transferring activity to replacement bytes.
Unique scopes mean publication/source/operation/target, never humans or cooking.

The producer uses a 90-day retention window and a 100 MiB SQLite database, reusing
free pages and pruning oldest rows under pressure. Age pruning runs on producer
startup and each recorded call; an idle or stopped producer can retain expired rows
on disk until it next runs. Analytics excludes expired rows even in all-retained
views. Its short SQLite write-lock timeout is
10 ms. Contention drops telemetry rather than failing retrieval. Analytics labels
coverage best effort with collection start, retained-from, last successful producer
write and known in-process loss. Restart/crash loss is unknown; measured zeros
never backfill uncollected history. A restart can reset the in-process loss count.
All-retained totals are not lifetime totals. UTC daily, 24-hour, 7-day, 30-day and
all-retained windows are available with publication filtering.

## Validation and planning context

Focused tests use synthetic files and metadata-only SQLite databases through the
HTTP and authenticated MCP interfaces. They cover aliases and namespace collisions,
missing/conflicting evidence, scoped states, failures/staleness, owner work,
read-only access, escaping, Host/origin constraints, bounded readers/storage,
privacy, call/appearance semantics, retention and telemetry contention.

```sh
PYTHONPATH=src uv run pytest -q tests/test_dashboard.py tests/test_mcp.py tests/test_library_auth.py
```

These tests do not invoke OCR, ingestion, source rendering or model inference.
The existing VM/cgroup OCR admission boundary is unchanged.

Specification: [Implement the local read-only cookbook dashboard and retrieval analytics](https://github.com/rickono/cookbook-mcp/issues/86).
Decision index: [Specify the local read-only cookbook dashboard](https://github.com/rickono/cookbook-mcp/issues/78).

## Open published books in the reader

Set optional `reader_origin` to the exact public HTTPS origin, for example
`https://reader.example`. Current successful index/remote catalog observations
supply identifier-only links in inventory and book details. Stale or missing
publication evidence, unpublished entries and incomplete source identity produce
no link. The reader independently requires sign-in and checks current access.
No source content, private filesystem path, token or dashboard snapshot is sent.
