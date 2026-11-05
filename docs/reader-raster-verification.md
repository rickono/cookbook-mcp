# Original-page raster reuse verification

This verifies the change for [Reduce repeated original-page viewing latency in
the hosted reader](https://github.com/rickono/cookbook-mcp/issues/132). It does not
establish live deployment performance or close the reader release acceptance.

## Serving path

On November 5, 2026, a read-only Fly inspection found image digest
`sha256:b53cf83a6d6c5360893c27e6dfc6897c6653af394995e6484691abd8ae71b1c2`.
SHA-256 checks of deployed `reader_original.py`, `reader.py`, `library.py`, and
`rendering.py` matched those files in main at `a11d6a6`. Each image request used
source validation and candidate selection, original-file verification, the bounded
renderer, and JPEG encoding. No raster reuse existed. The implementation builds
on main at `0b5c435`, which also adds session request diagnostics.

The initial synthetic authenticated HTTP reproduction returned five decoded
images, invoked the renderer five times, and rehashed the original on all four
repeat views. Its assertion that the renderer ran once failed. The new regression
requires one render, no later original-cache access, fresh metadata, and raster
admission on every hit.

## Synthetic Linux profile

The opt-in trial uses generated PDF artwork and text, real `pdftoppm`, and the
assembled authenticated HTTP adapter with synthetic identity and local storage.
It enables and disables raster reuse on the same implementation, warms both
cases, then alternates five requests per case. Each timed request includes the
full in-process HTTP body. Each result is decoded afterward and checked against
an identical output hash. It is a comparison of warm reuse states, not two
versions of the whole application.

Run from the repository with a fresh private output directory:

```sh
python3 scripts/ocr_sandbox.py doctor
python3 scripts/ocr_sandbox.py run --output PRIVATE_NEW_DIRECTORY -- \
  env XDG_CACHE_HOME=/tmp python -m pytest -q -s -p no:cacheprovider \
  --basetemp=/output/tmp tests/reader_raster_trial.py
```

`XDG_CACHE_HOME` places Fontconfig's cache in the existing bounded temporary
filesystem. Four initial setup attempts were refused because Fontconfig had no
writable cache directory. They produced no successful image samples and are not
included below. The successful run had no request or decode errors. No renderer
limit or isolation guard was changed.

Observed on November 5, 2026, in the admitted Docker Desktop Linux VM with two
CPUs, a 2 GiB workload cgroup, zero swap, and the unchanged serving subprocess
limits:

| Warm state | Successful samples | Median body ms | Range ms | Image bytes |
| --- | ---: | ---: | ---: | ---: |
| Original cached, raster reuse disabled | 5 | 349.9 | 348.0–407.9 | 239,282 |
| Original cached, verified raster retained | 5 | 4.1 | 3.2–4.5 | 239,282 |

Median diagnostic stages, rounded to milliseconds:

| Stage | Reuse disabled | Raster hit |
| --- | ---: | ---: |
| Source validation and candidate selection | 2 | 2 |
| Original-cache verification and pinning | 1 | Not invoked |
| Bounded rendering | 329 | Not invoked |
| PNG conversion and JPEG encoding | 16 | Not invoked |
| Fresh metadata and withdrawal check | 1 | 0 |
| Delivery raster admission | 0 | 0 |
| Response construction | 0 | 0 |

The measured limiter is rendering. Render and encoding calls occurred inside the
timed requests. All five reuse samples recorded one hit and no rendering or
encoding stage. Zero milliseconds means below diagnostic rounding precision.
The first request with both caches cold took 463.5 ms. Initializing the second
case's raster with the original already cached took 342.4 ms. These are single
observations, separate from warm statistics.

The Mac was busy, with load average 68.28 across ten host cores before the trial.
Alternation limits drift bias, but this is a small synthetic workload on a shared
host. It does not represent source-book complexity, remote session or withdrawal
storage latency, Fly CPU scheduling, network transfer, browser painting,
production percentiles, or the issue's original elapsed-time baseline. No live
speedup is claimed. Raw output and generated artifacts remain outside Git.

## Correctness and release checks

`tests/test_reader_raster.py` covers source and setting separation, byte and entry
eviction, disabled reuse, failure admission, fresh withdrawal metadata, publication
retirement, session expiry and logout, delivery raster admission on hits, and busy
refusal with responsive health and text requests. Existing geometry and renderer
failure checks use an uncached region when they need to invoke the renderer.
The explicit serving-only release selection includes these regressions.

Live stage attribution, interleaved authenticated hosted image measurements and
device acceptance remain follow-up verification after a separately authorized
deployment. This PR does not deploy, change publications, or raise resource limits.
