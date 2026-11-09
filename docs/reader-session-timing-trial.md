# Reader session timing trial

2026-11-07. The local PostgreSQL implementation removes a substantial measured wait in this synthetic trial. This supports a nearby hosted database trial. It does not establish hosted PostgreSQL latency or a production speedup.

## Measured requests

Five alternating repetitions per store and journey, after one warmup each. Each response passed content assertions. All 80 reported HTTP responses returned 200, across 70 journey executions. The two-tab journey contains two simultaneous requests. No measured journey failed. Synthetic R2 object cleanup succeeded.

| Journey | Hosted R2 through SSH, median [min–max] ms | Local PostgreSQL, median [min–max] ms |
| --- | ---: | ---: |
| Session check | 385.79 [373.50–419.03] | 2.91 [0.89–4.73] |
| Open library | 2159.39 [1896.85–2380.52] | 4.38 [2.18–5.84] |
| Search results | 2114.70 [2021.36–2257.33] | 14.65 [13.22–18.84] |
| Open recipe text | 2078.82 [1915.96–2086.35] | 6.39 [4.13–9.99] |
| Original page | 2211.92 [1889.33–2396.05] | 4.00 [3.21–9.93] |
| Original image | 2103.06 [1958.06–2169.45] | 3.95 [2.90–5.76] |
| Two tabs, both complete | 3075.84 [2609.54–4545.78] | 2.72 [1.91–3.34] |

## Storage wait and relay overhead

The catalog median inside the R2 worker was 2,001.31 ms for GET plus conditional PUT, with a range of 1,737.21–2,216.41 ms. The additional relay time for that journey had a median of 157.53 ms. A no-op relay round trip had a median of 76.31 ms. These measurements separate the SSH transport from the R2 operation. Subtracting them is not a hosted end-to-end prediction.

The profile used separate requests. It briefly overlapped the initial two-tab batch, so a clean five-repetition two-tab run replaces that batch in the table. All 20 additional HTTP responses in the repeat succeeded. Other journeys finished before profiling began. A profiled R2 GET took 348.06 ms, of which 339.54 ms was SSL socket reading. A conditional PUT took 1,475.82 ms, of which 1,468.18 ms was SSL socket reading. Local serialization and encryption do not explain the remote wait. 5 definite conditional-write conflicts occurred in the measured two-tab journeys. Both requests ultimately succeeded in every repetition.

The PostgreSQL fixture confirms that one durable device row exists and its timestamp advances during the run. Existing adapter checks also establish timestamp-only updates, unchanged passive rows, and no R2 owner-record operations. The PostgreSQL pool is warm, uses logged tables, Read Committed, `fsync=on`, and `synchronous_commit=on`. R2 uses the existing hosted boto3 client configuration and warmed connections, with two independent worker channels for concurrent tabs.

## Scope and limitations

Both readers run on the Mac through Starlette TestClient. They use the same signed synthetic JWT, single-device session, encryption key, publication, library cache, and route handlers. OAuth correlation records and content remain local on both sides. No real provider renewal or browser rendering is measured. Search exercises the available synthetic section-search path, not the production semantic-search service. Originals use a synthetic EPUB image and perform no PDF ingestion, rasterization, OCR, or model inference.

The R2 adapter reaches the existing Fly machine in `sjc` through SSH. The worker maps virtual owner keys into a random `research/session-134/benchmark-*` namespace. No real owner object is accessed and no storage credential leaves the machine. Each worker reports the time inside the R2 operation as well as its relay round trip. The raw R2 request column includes the relay. The two-tab storage-stage sums overlap and must not be treated as wall-clock time.

The observed Fly image was `sha256:dbeae1c5433fa4291b092e5af64e9d5c401907df277367dd6364017f95b093ff` on machine `2863795a042368` before the final journeys and after completion. Startup image environment fields were null, so immutable provenance over the entire run is not established. The active hosted reader was not changed.

The Mac had ten logical CPUs and high load averages. Spotlight metadata processes were the largest CPU users at the initial check. Alternating execution reduces drift but does not turn these small samples into a capacity test. Five samples support a median and range; they do not establish p95. PostgreSQL has a local socket while a hosted database has network, connection, and service overhead. The test demonstrates room to improve and warrants testing placement. It cannot justify quoting the raw ratio as a production speedup.

## Reproduction

The command requires an authenticated Fly CLI connection and installed PostgreSQL binaries. It creates synthetic R2 objects, verifies their deletion, and removes the disposable database.

```sh
uv run --extra postgres python scripts/benchmark_reader_sessions.py --live-synthetic-writes --fly-app cookbook-agent --postgres-bin /Library/PostgreSQL/17/bin --output /tmp/reader-session-benchmark.json
```

Raw timing and profile records remain outside Git in `/tmp/reader-session-benchmark-final.json`, `/tmp/reader-session-benchmark.json`, `/tmp/reader-session-two-tabs.json`, and `/tmp/reader-session-profile.json`. The benchmark code and this summary are source-safe. No infrastructure was provisioned and no session migration occurred.

The clean two-tab repeat uses the same command with `--journeys two_tabs` and a separate output path.
