# Hosted zoom stall: follow-up investigation

Issue: [Investigate and bound the hosted high-resolution zoom stall](https://github.com/rickono/cookbook-mcp/issues/67).

The October 30 follow-up has not established the cause of the original outage.
The remaining causal acceptance item stays unchecked.

## Evidence audit

- Saved platform logs record health failing at 03:59:41 UTC on October 28,
  followed by the controlled restart at approximately 04:07–04:08 UTC.
- Those saved logs contain no OOM-kill record or captured blocking stack.
  Absence of that record does not establish absence of memory pressure.
- The saved attempted Machine-status capture contains CLI usage output rather
  than a usable process/configuration snapshot. It cannot establish the live
  process state during the outage.
- Earlier guarded replay of the incident page at the incident render edge
  completed successfully in approximately 1.6 seconds, with approximately
  210 MiB peak decoder RSS. At a deliberately smaller 192 MiB boundary it
  produced a recorded cgroup OOM kill. That establishes a decoder resource hazard,
  not the cause of a historical outage on the 1 GiB production Machine.
- The already-deployed containment bounds decoder resources and duration,
  refuses concurrent renders, and releases the shared asset-cache lock before
  decoding. This follow-up made no production changes.

## HTTP feedback loop

A new synthetic diagnostic exercises an authenticated `get_page` request through
the MCP HTTP app while its renderer is deliberately held pending. It separately
requests `/healthz` before releasing the renderer. The signal fails if health
waits for rendering or exceeds a 300 ms local response allowance.

Both the historical `2ecc3d4` handler/server and the deployed `02f618a` versions
returned health immediately while rendering was still pending. Both cases passed
in a single 0.83-second test run. Their pinned dependency manifests are identical.
The historical method is loaded against the current synthetic library fixture;
this is a targeted scheduling probe, not a reconstruction of the historical VM,
runtime cache, native search process, memory pressure or storage state.

This loop can detect HTTP health starvation, but did **not** reproduce the
reported incident. A waiting renderer alone is insufficient in this controlled
scenario. Neither these results nor the previous OOM experiment establish the
historical cause. No causal hypothesis is promoted to a finding.

The probe used synthetic page images and signing keys only: no PDF parsing,
source rendering, OCR, model inference or provider calls. Existing private replay
artifacts were inspected without reprocessing source books. The official sandbox
doctor passed; its resource ceilings were unchanged.

## What is needed to progress

A future health failure needs a contemporaneous bounded capture: per-process RSS
and state, wait channels and kernel stacks, VM memory/pressure counters, decoder
identity/lifetime and health timing. A small read-only watcher could collect these
without recording command arguments, environments, authorization headers, book
text or page images. Python user-space stacks would require a separately prepared
diagnostic hook or debugger; kernel stacks are not a substitute for them.

Do not deliberately replay the uncontained failure on the live service, enlarge
resource ceilings, or remove the deployed containment to obtain this evidence.
If a future capture cannot distinguish the remaining possibilities, preserve that
uncertainty rather than interpreting another timeout as proof of an OOM or lock.

Private evidence and the synthetic probe are under
`~/cookbook-mcp-data/poc/zoom-stall-67-followup-20261030/`. Original books,
transcriptions, page images, raw production logs and credentials remain outside
Git and GitHub.
