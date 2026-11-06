# Follow-up on slow hosted session writes

Investigation for [Investigate session-storage overhead on protected reader requests](https://github.com/rickono/cookbook-mcp/issues/134), 2026-11-06. This follows the [initial attribution](reader-session-storage-research.md).

## Finding

No tested client change produced a repeatable improvement. The slow operation waits for the remote storage response. CPU, SDK retries, warm-connection setup, the conditional-write header, and streaming checksum encoding do not explain the observed delay by themselves.

A later run became faster for every client, including the unchanged production adapter. A concurrent deployment changed the Fly image and instance during this investigation. Therefore the slow-to-fast shift cannot be attributed to an experimental change, or solely to provider variability. It is not an optimization result.

Do not change session admission, cache authorization, remove `If-Match`, or deploy a replacement HTTP client from these results. The next investigation should target the storage service and network path while holding the deployment fixed. If a faster durable authority is needed, compare it against the complete admission and lifecycle workload before selecting it.

## Reproduction and profile

The existing transport probe reproduced slow conditional PUTs on the hosted machine. An outer assertion rejected a median at or above 1000 ms after cleanup, giving a repeatable failure signal for the slow state. A separate cProfile run found 29.08 seconds of aggregate self time in SSL socket reads across the full probe. This includes several operation types and is not a per-PUT time. Profiling results are excluded from the comparison tables.

The hosted machine reports one CPU. A load check during the first experiment returned 0.0, 0.0063 and 0.0. Botocore was version 1.43.93. Each comparison warmed its pools, rotated the starting variant across five rounds, verified byte-for-byte data and ETag readback, and retained operation status and retry counts. Encryption and object setup were outside the measured update. The encrypted body was small and synthetic. No real owner record was read or changed.

The source-safe probe is `scripts/probe_session_write_paths.py`. It creates keys only in its hard-coded research namespace. The unconditional-write variant is diagnostic and must never replace session CAS.

## First comparison

| Variant | Trials | PUT wall ms, median [range] | Process CPU ms, median | New SDK connections | SDK retries |
| --- | ---: | ---: | ---: | ---: | ---: |
| default_conditional | 5 | 1416.23 [1353.1–1418.93] | 2.89 | 0 | 0 |
| header_conditional | 5 | 1342.98 [1324.59–1457.84] | 2.35 | 0 | 0 |
| default_unconditional | 5 | 1412.32 [1364.49–1632.4] | 2.66 | 0 | 0 |
| default_create | 5 | 1098.84 [1051.58–1192.96] | 2.69 | 0 | 0 |

The default adapter sent an AWS chunked body with a streaming checksum. The checksum-header variant sent a content-length body and an explicit SHA-256 checksum instead. It preserved integrity verification and stale-write rejection. The observed ranges overlap; the checksum variant did not remove the large delay. Removing the conditional header likewise did not remove it. New-object creation was faster in this sample, but still exceeded one second. Creating a new object on every activity update is not an equivalent session operation and would require a different authority and reconciliation protocol.

The SDK connection hook saw no new connections during these timed updates. Both conditional and unconditional writes waited despite warmed pools. No SDK retry occurred. This narrows the delay to waiting on the remote response rather than reconnecting or replaying the request. It does not isolate transit from provider processing or prove which internal provider component waited.

## Direct HTTP and combined checksum comparison

A second comparison combined explicit checksum headers with removal of Expect, and added a directly signed HTTP/1.1 request through a warmed HTTPX client. Every request retained `If-Match` and a SHA-256 checksum. The first direct-client setup requests were rejected because the hand-built request lacked the S3 content-hash header. Those setup failures are excluded from successful latency samples. The corrected direct path includes the content hash before signing.

| Variant | Trials | PUT wall ms, median [range] | Process CPU ms, median | SDK retries |
| --- | ---: | ---: | ---: | ---: |
| default_conditional | 5 | 349.6 [316.41–361.15] | 2.71 | 0 |
| header_without_expect | 5 | 363.72 [302.61–393.39] | 2.2 | 0 |
| direct_signed_http | 5 | 334.77 [330.48–469.97] | 1.7 | 0 |

All three variants became faster together. Their spread does not establish a benefit from changing the SDK or encoding. Direct HTTP connection events are not covered by the SDK hook; that client was warmed explicitly. Direct HTTP does not perform SDK retries. Before this run, load averages were 0.0122, 0.0225 and 0.0.

The original unmodified `probe_session_transport.py` was then repeated independently, with five alternating trials per client. Its default PUT median was 333.52 ms [315.84–397.8]. This confirms that a faster state did not require the new probe or an experimental client change. It does not identify why the state changed.

A final smoke run of the checked-in probe passed the 1000 ms diagnostic threshold. The default adapter measured 292.64 ms [240.51–346.18], checksum-without-Expect 339.0 ms [309.29–420.49], and direct HTTP 353.36 ms [299.39–398.67], five trials each. Both experimental paths rejected every deliberately stale write and preserved current readback. Cleanup confirmed all three objects absent. These results again provide no client-change win. Focused lint, formatting, compilation and the two summary privacy checks passed.

## Deployment and provider evidence

Fly status before and after the investigation showed the same machine ID and San Jose region, but a different instance and image. The only visible machine-configuration field that changed was `image`; configured environment fields did not change. Image digest changed from `sha256:b5a6dedf0fd2f7ab68bc7d278da5c84d58fd2f89d9dbe2aff28fec40da59dfc0` to `sha256:dbeae1c5433fa4291b092e5af64e9d5c401907df277367dd6364017f95b093ff`. We did not initiate that deployment. These status snapshots cannot establish unchanged secret configuration or exclude other provider-side changes.

The later hosted `hosted.py`, `storage.py`, and `reader_sessions.py` module hashes match reviewed main at `9031857`. Thus the later probe still used the reviewed session and storage implementation. This does not equate the two complete images.

`GetBucketLocation` returned `WNAM`, while the service runs in `sjc`. That does not support a simple continent mismatch. A location constraint is not a measurement of physical storage placement or latency. Cloudflare documents location hints as best-effort placement inputs. [Data location](https://developers.cloudflare.com/r2/reference/data-location/).

Cloudflare describes a write as gateway handling, regional storage replication, then metadata commit before success is acknowledged. This is consistent with the measured response wait, but is not a trace proving that a particular replication or metadata step caused it. [How R2 works](https://developers.cloudflare.com/r2/how-r2-works/).

R2 also documents a limit of one concurrent write per second to the same object name. The first comparison spaced same-key updates by several other operations and observed no throttling or retries. That limit does not explain those isolated slow samples, but it is a separate reason to test realistic multi-tab activity before relying on one frequently rewritten owner object. [R2 limits](https://developers.cloudflare.com/r2/platform/limits/).

## Next experiment

First freeze the image and capture paired read/update latency, request IDs privately, connection reuse, and provider-edge diagnostics when the slow state recurs. A provider-side trace is needed to separate transit, metadata routing and storage commit. Compare from a second controlled request origin if available. Do not call the earlier slow period a permanent 1.4-second floor.

For a bounded infrastructure candidate, test R2 Local Uploads on an isolated synthetic bucket, with it disabled and enabled under the same pinned deployment. Cloudflare documents immediate consistency and durable local acceptance, followed by replication to the primary location. It can affect immediate read latency from other regions. Its benefit is unestablished here, especially because the reported service and bucket locations already align broadly. We did not establish whether it is enabled on the live bucket, change that setting, or create a new bucket. [Local Uploads](https://developers.cloudflare.com/r2/buckets/local-uploads/).

Any candidate must keep authoritative reads and conditional writes. R2 documents atomic condition evaluation and serialization of competing conditional writes. Confirm those properties through actual multi-client races, followed by device/all-device logout, renewal settlement, restart and exact expiry tests. [Consistency and conditional writes](https://developers.cloudflare.com/r2/reference/consistency/).

If a pinned, colocated R2 configuration still misses the user-visible budget, compare a colocated transactional session authority. That is a storage change with migration, backup and renewal-lease requirements. It is not a reason to return stale authorization or defer successful activity persistence. No alternative store or service has been benchmarked in this investigation.

## Reproduce safely

On the hosted machine, with only the existing private session-store environment available:

```sh
python scripts/probe_session_write_paths.py --live-synthetic-writes --max-update-ms 1000
python scripts/probe_session_write_paths.py --live-synthetic-writes --transport-comparison --max-update-ms 1000
```

The optional threshold exits with status 2 after cleanup when the default client's median meets or exceeds the supplied budget. It is a diagnostic threshold, not a release SLO. Raw capture and source-safe aggregate output stay outside Git. A separate SDK profiler run must not supply headline comparison numbers.

No application change or deployment was made. Synthetic objects were deleted and checked absent. A final namespace listing also confirmed no remaining synthetic objects from the exploratory failures or completed probes. No book content, production session, publication, resource ceiling, OCR, or inference was changed or used.
