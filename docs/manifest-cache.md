# Runtime manifest cache

Each `Runtime` owns an LRU of at most three validated manifests. Library and MCP
consumers keep using `Runtime.manifest(publication_id)`. Its returned metadata
supports the existing field reads and inventory iteration; the manifest, inventory,
and entries are immutable tuples. Publication building and JSON serialization
continue to use the original mutable Pydantic models.

Every lookup validates the ID and stats the local manifest. The cache fingerprint
contains device, inode, size, and nanosecond modification/change times. Removal,
quarantine, replacement, or edits force a reload or an unavailable-publication
error. A failed reload cannot fall back to old metadata, and repairs can load on
the next request. File-descriptor identity before/after reading and path identity
after parsing bind an entry to the file actually read. A changing file gets at
most two attempts. These checks detect local changes; they do not replace
cryptographic verification or promise protection against hostile host mutation.

A runtime-local lock serializes lookup, population and eviction, sharing one cold
load among concurrent callers. It is released before library queries, asset
verification/downloads, and rendering. It never acquires the activation lock.
Startup and activation still perform their independent manifest checksum, runtime
checksum, SQLite integrity, and publication-identity checks. Lifecycle operations
invalidate the affected metadata; they do not seed the cache from partially
verified state. Eviction affects memory only. Explicit retained-version requests
remain bound to that publication, including during activation and store outages.

## Synthetic benchmark, 2026-09-15

Reproduce from the checkout with the project's development environment active:

```sh
PYTHONPATH=src:tests python scripts/benchmark_manifest_cache.py \
  --output /absolute/private/manifest-cache-benchmark.json
```

The script builds three synthetic publications, each with 11,000 inventory entries
(1,661,086 JSON bytes) and a 270,336-byte valid SQLite index. It uses synthetic EPUB
section records and a generated JPEG; no source books, extraction, or OCR are
involved. It compares the prior lookup implementation with the new implementation
in the same environment, using 30 cold/warm pairs per operation. Cold means a new
Runtime; the disk image cache is already populated in both cases. Complete
operation response hashes match between implementations. Raw outputs stay outside
Git and GitHub.

Measured on macOS 26.4.1 ARM64, Python 3.12.11. Median server-processing times:

| Operation | Before cold | Before warm | After cold | After warm |
| --- | ---: | ---: | ---: | ---: |
| Catalog search | 13.74 ms | 14.56 ms | 21.99 ms | 0.30 ms |
| Full-text search | 24.92 ms | 24.76 ms | 37.42 ms | 11.58 ms |
| 50-character section read | 13.76 ms | 13.53 ms | 17.07 ms | 0.35 ms |
| Cached-image read | 45.58 ms | 45.05 ms | 17.73 ms | 0.32 ms |

For the 30 pairs, manifest validations fall from 60 to 30 for each search/read,
and from 120 to 30 for images. The authenticated MCP regression test separately
counts actual local manifest opens and validations: every cold operation loads
once; its warm counterpart performs neither operation. Eight simultaneous first
callers also share one load. There are no wall-clock pass/fail thresholds.

Creating the immutable representation adds cold-load work for single-lookup
operations. Warm requests avoid that work entirely. The full-text result still
includes SQLite/FTS and citation work, which this change does not optimize.

With all three manifests resident, `tracemalloc` reports 7,651,547 retained Python
bytes (7.30 MiB), versus 34,958 bytes after baseline lookups. Population peaks at
14,607,871 Python bytes (13.93 MiB). Retained allocations are about 0.71% of the
existing 1 GiB machine limit documented in `deploy/fly.trial.toml`. Whole-benchmark
process peak RSS is 125,763,584 bytes (119.94 MiB), including imports, synthetic
fixture construction, timing, and allocation measurement. This is a local sizing
observation, not a measurement of production Linux load or available headroom.
The bound limits manifest count, not bytes in an arbitrarily large publication.
These results make no promise about connector round trips or end-to-end latency.

## Verification

The targeted regression suite covers authenticated cold/warm MCP response equality,
source citations, pagination, book/TOC metadata, image discovery/inspection/delivery,
bounded section artifacts, original-file restrictions, publication info, warm-cache
authorization and invalid IDs. Focused Runtime tests cover immutable ownership,
independent instances, LRU eviction/reload without disk deletion, concurrent loads,
changes during reads and parsing, same-size replacement with preserved mtime,
corruption/removal/quarantine and repair, activation/failure/rollback, retained
reads, and independent startup verification/recovery. Existing hosted, publication,
asset verification, synthetic EPUB image, and local S3 tests remain active.

```sh
PYTHONPATH=src python -m pytest -q \
  tests/test_manifest_cache.py tests/test_publication.py tests/test_mcp.py \
  tests/test_library_auth.py tests/test_hosted.py tests/test_image_discovery.py \
  tests/test_image_context.py tests/test_s3.py
```

Result: **55 passed**, with one existing Starlette deprecation warning. Ruff F
checks, formatting checks, and `git diff --check` pass.

The environment's `bin` directory must be on `PATH` for the local `moto_server`
fixture. This selected suite does not invoke OCR. The complete extraction/OCR
suite requires the separate resource-isolated launcher described in
[the OCR policy](ocr-resource-isolation.md).
