# OCR execution

Before running PDF/DjVu ingestion, OCR, model inference, scan experiments, or tests that invoke OCR,
read [docs/ocr-resource-isolation.md](docs/ocr-resource-isolation.md) and use
`scripts/ocr_sandbox.py`. Native OCR is disabled after a host memory-pressure
incident. Preserve this fail-closed admission check in project and private trial
entry points. A network sandbox, image-size cap, shell ulimit, or memory polling
does not replace the Linux VM and cgroup resource boundary.

Keep source books, experiment outputs, and incident evidence outside Git. Use
synthetic workloads for enforcement checks; the oversized trial is not a test
fixture. Change resource ceilings only after a separate review of host capacity.

## Planning context

Before creating, claiming, wiring, or resolving issue-tracker work, read
[the GitHub tracker conventions](docs/agents/issue-tracker.md).
When discussing cookbook concepts or planning a change to them, read
[the domain glossary](CONTEXT.md). Keep agreed terminology there; decision detail
belongs in its issue or, when warranted, an architectural decision record.
