# Private cookbook MCP

A private Python MCP service with SQLite FTS5, source-bound citations, and immutable publications. The full 58-EPUB catalog is now uploaded to private R2 storage and active on the existing Fly service. All remote file checksums, the hosted index, Google publisher sign-in, exact activation acknowledgement, and 293 authenticated hosted MCP calls have passed for the full catalog. Fifty-seven EPUBs have searchable text; the Alain Passard EPUB is image-only and awaits the separate OCR follow-up. PDF/DjVu ingestion remains deferred. The earlier two-book trial passed ChatGPT linking, cited reading, section artifacts, and the inline image viewer; original EPUB downloads through MCP remain unavailable. See [full EPUB publication status](docs/full-epub-publication.md), [hosted runtime](docs/hosted-runtime.md), and [OCR resource isolation](docs/ocr-resource-isolation.md).

## Local setup

Python 3.12+ and uv are required locally. OCR ingestion and OCR tests require the [resource-isolated launcher](docs/ocr-resource-isolation.md), which uses a capped local Linux VM and container. Native Mac OCR is disabled after a memory-pressure incident. The ingestion/test image includes Poppler, DjVuLibre and English Tesseract; the deployed runtime image remains separate.

```sh
uv sync --frozen
python3 scripts/ocr_sandbox.py doctor
# Prepare cookbook-ocr:safe as described in docs/ocr-resource-isolation.md, then:
python3 scripts/ocr_sandbox.py run --output "$HOME/cookbook-mcp-data/poc/tests-NEW" -- python -m pytest -q -p no:cacheprovider --basetemp=/tmp/pytest tests
uv run ruff check --select F src tests scripts
uv run ruff format --check src tests scripts
```

`uv.lock` pins dependencies, including MCP 2.2.0 and fontTools for PDF font decoding. The explicit `PYTHONPATH=src` below also avoids an observed editable-install path issue on this Mac. Docker installs the package without editable mode.

## One-command local fixture publication

From the repository root:

```sh
scripts/publish-fixture.sh /Users/rick/cookbook-mcp-data/poc/manual-run
```

This command verifies the existing approved snapshot, processes Calibre IDs 5 and 40, stores private derivatives outside Git, builds the index, publishes to a **local filesystem object store**, fully reads back and hashes every object, and confirms local runtime activation. Tu Casa Mi Casa (6), The Professional Chef (9), and The World Atlas of Wine (45) are excluded from this trial; their original snapshot and earlier OCR builds remain available. Required extraction/OCR failure stops before activation. It neither accesses the live Calibre database nor copies additional source books. Failed build directories are preserved for inspection.

The fixture backup contains the two selected record directories plus the snapshot catalog/preferences files. It is **not a complete 56-book library backup**: the copied catalog still references unselected records whose originals are intentionally absent in this POC. The MCP index exposes only the two selected books; administrative backup files have no tool/resource route. Full-library backup and selection review belong to the later authorized publisher workflow.

A build with flagged OCR pages exits with status 3 and leaves a private review report in its build directory. Review those pages, then use `finalize-local` to produce a new build without repeating extraction. See [the review commands](docs/ocr-review.md). Existing schema-1 builds, including `build-3`, remain readable/restorable but cannot be newly published under the approved review policy. Rebuild them before their next publication.

## Authenticated transport test

```sh
PYTHONPATH=src uv run python scripts/validate_fixture.py \
  --store /Users/rick/cookbook-mcp-data/poc/store \
  --runtime /Users/rick/cookbook-mcp-data/poc/runtime \
  --report /Users/rick/cookbook-mcp-data/poc/transport-report.json \
  --expected-books 5 40 --inspector
```

The script creates a short-lived RSA signing fixture in memory, binds only to loopback, checks the nine-tool listing and exercises applicable EPUB tools with the official MCP client, runs the pinned Inspector CLI, saves only metrics and private QA images, and stops the server. It creates no OAuth authorization server. Auth0/Google/ChatGPT login remains an end-to-end deployment gate.

Photo lookup now separates `list_images` (captions/context), `inspect_image`
(candidate pixels without the viewer), and `get_image` (final displayed photo).
See [image selection and client verification](docs/image-selection.md).

For a persistent local test server, `cookbook serve-local --help` describes the required public verification key, issuer, subject, store and runtime arguments. A private key or bearer token never belongs in Git. There is no static-key authentication mode and no public asset URL fallback.

## Restore and rollback tests

```sh
PYTHONPATH=src uv run python -m cookbook.cli restore-local \
  --store /Users/rick/cookbook-mcp-data/poc/store \
  --destination /Users/rick/cookbook-mcp-data/poc/restored-copy
```

The destination must not exist. A complete restore verifies every manifest entry and reconstructs its logical tree. Runtime recovery restores only the index and lazily verifies content into a bounded cache. `Runtime.activate(pointer)` verifies/stages a chosen known pointer before switching, and is also the local rollback primitive. Administrative restore paths never become MCP resources.

The S3 adapter is exercised over HTTP against loopback Moto using **synthetic data only**. A gated `publish-s3` CLI and authenticated acknowledgement are implemented; Mac browser PKCE login is implemented and live-verified; the EPUB trial upload and authenticated hosted acknowledgement have passed. Actual R2 permissions and conditional writes have passed synthetic provider tests. Multipart files above 5 GB remain unimplemented. The adapter refuses originals above 5 GB until multipart behavior is implemented and verified.

## Container and sizing

```sh
docker build -t cookbook-mcp:poc .
```

The build context includes only code and dependency manifests. The image runs as an unprivileged user. `scripts/benchmark.py` is designed for a Docker run with `--memory 1g --memory-swap 1g --cpus 1 --network none`, a read-only object-store bind mount, and a fresh writable runtime mount. The default command runs the independent supervisor and hosted worker. HTTPS proxy settings, 60-second publication polling, and watchdog defaults are prepared in the [trial deployment artifact](deploy/fly.trial.toml); the approved existing-Machine cutover is complete.

## Design seams

- `extract.py`: EPUB spine/TOC/locators, conservative recipe structure, PDF/DjVu physical pages and bounded renders.
- `ocr.py` / `quality.py`: corrected OCR copies, confidence triage, digest-bound human review, publication gate and new-build finalization.
- `build.py`: snapshot validation, selected index, complete per-fixture inventory.
- `storage.py`: streaming local/S3 storage, create-only writes and pointer preconditions.
- `publication.py`: manifests, full verification, staged restore, atomic local activation, dry-run retention plans.
- `library.py`: source-bound read-only queries and serialized bounded asset cache/rendering.
- `server.py`: JWT resource-server checks, protected Streamable HTTP and embedded content.
- `hosted.py` / `supervisor.py`: remote polling, authenticated activation acknowledgement and independent process recovery.

No cleanup of real snapshots, failed builds or publication objects is enabled. Retention deletion is tested only in disposable synthetic stores. Do not deploy this POC as production before resolving the report's deployment gates.
