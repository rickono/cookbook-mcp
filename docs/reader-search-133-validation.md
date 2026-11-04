# Reader search validation for issue 133

The serial session dependency is removed. The observed search medians were lower on every case, but broad overlapping ranges make the size of the latency gain inconclusive. Result-request latency also varied between sides, so the full median difference cannot be attributed to the removed request. These observations support the request-sequence change, not a production speedup percentage.

## Method

On November 3, 2026, a controlled authorized desktop browser ran the exact baseline and candidate search scripts against the same live backend and publication. The baseline script hash matched the live asset. The original private workload was recovered from its recorded browser invocation. Its queries and selected book remain private.

Five rounds alternated baseline and candidate, reversing side order each round. Each side ran all five cases. Timing starts immediately before requestSubmit and ends when the existing completion status and result DOM are updated. Script installation, catalog readiness, and candidate CSRF supply were outside the timer. The candidate received a real server-issued CSRF value in memory before installation, emulating the new HTML attribute. This is a live-backend client comparison, not a deployed-candidate or page-load test. The actual HTML handoff is verified by synthetic HTTP tests. No deployment, persistent browser storage, token export, source processing, rendering, OCR or inference occurred.

The unchanged session monitor remained active. The browser viewport was 1280 by 800 with no network throttling. Host load was about 5 on 10 cores before and after the run. Desktop and network noise remain possible. Two initial multi-action tool batches hit the browser tool time limit; those pilot samples were discarded and the tab was closed. The final run used one action per tool call and has no tool timeout. Tool-call overhead is outside the browser timer.

## Submit-to-results observations

Each cell is median seconds with observed minimum and maximum. Each side has five successful samples per case.

| Case | Baseline seconds | Candidate seconds | Action requests, baseline / candidate |
| --- | --- | --- | --- |
| Whole-library A | 2.54 (1.65 to 2.90) | 1.03 (0.89 to 1.71) | 10 / 5 |
| Whole-library B | 2.31 (2.12 to 3.05) | 1.40 (0.92 to 2.61) | 10 / 5 |
| No match | 2.17 (1.50 to 3.80) | 1.03 (0.89 to 2.00) | 10 / 5 |
| Recipe filter | 1.81 (1.33 to 4.08) | 0.73 (0.69 to 4.34) | 10 / 5 |
| Book scope | 1.91 (1.63 to 4.59) | 1.62 (1.31 to 3.15) | 10 / 5 |

All 50 searches completed. There were zero search HTTP errors and zero failed result groups. Full response digests and rendered-row digests matched across both sides and all repeats for each case. Digests cover result destinations, text, group coverage and publication binding; no result content is copied into this report.

The baseline issued 25 serial session GETs and 25 results POSTs. The candidate issued 25 results POSTs with no action session GET. Two passive monitor GETs overlapped the reported search windows, one on each side. Both eventually returned HTTP 503; neither search failed. Polls that were still in flight when a search ended were reconciled after completion and counted separately, rather than incorrectly excluding a successful search.

The removed baseline preflight had a median time to response headers of 0.81 seconds and a range of 0.58 to 3.09 seconds. Browser traces show the results POST starting only after that GET completes. The candidate POST starts directly. This serial network dependency is the measured limiter addressed by the change; server CPU, session PUTs and backend stages were not separately profiled in this run. Existing server-side research attributes substantial session time to remote storage, but this run does not assign the entire search latency to that storage.

## Additional checks

Both live result-group continuations succeeded independently with one POST each, preserving the original publication id and native content page or section offset. A deliberately stale CSRF value produced exactly one rejected POST, one session GET and one successful POST, with identical final results. The expected diagnostic 403 is separate from the 50 healthy-session timing samples.

The integrated branch passed 41 Node script tests from `reader_search`, `reader_session`, `reader_personal`, `owner_reports` and `reader_content`, plus 48 synthetic HTTP tests from `test_reader_search.py` and `test_reader_http.py`. They cover direct initial and repeated requests, changed scope and type, both cursors, malformed or failed recovery, bounded replay, expiry, idle lifetime, access-token renewal and refusal, exact Origin, CSRF and late-response clearing. Existing mutation modules are unchanged. Ruff, Node syntax and git diff checks passed.

## Reproduction and limits

Raw samples and the browser measurement script are retained privately outside Git. To regenerate the source-safe aggregates from that private JSON, run `python3 scripts/summarize_reader_search_trial.py MEASUREMENTS_JSON`. The summarizer requires all five cases, both sides and all five rounds, counts HTTP errors separately for action and monitor traffic, and checks digest equality only when digests are present. Unfinished requests require reconciliation before summarizing; a network failure without an HTTP status is counted as an error.

Council follow-up added five source-free regression cases for the summarizer, including missing digests, unfinished requests and separate monitor errors. They are part of the explicit serving-only release selection. Regenerating the private trial's aggregates after these fixes produced identical results.

A full deployed candidate journey, natural hosted expiry and renewal, device accessibility, browser paint, cold starts and production percentiles remain unverified. The seven-day and thirty-day session limits and the existing per-fetch deadlines are unchanged. The monitor 503s remain a separate reliability concern. No issue closure or release acceptance is implied.
