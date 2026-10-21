"""Write the evaluation-leaf brief for one candidate book.

The body is the frozen evaluation protocol every graded cell used (the grok-4-6 template),
retargeted to this candidate; only the header and the candidate description change. The
bench-summary.json request is appended so `bench.py compare` can read the grade without
parsing an evaluator's free-form metrics.json.
"""

import json

from pipeline import EXP

TEMPLATE = EXP / "prompts/mc3b-eval-grok-4-6--medium-b6-r1.md"
BOOKS = {6: "Tu Casa Mi Casa", 79: "Mugaritz", 81: "The Family Meal"}
EVALUATOR = "codex/gpt-6.1-sol reasoningEffort=medium"
SUMMARY = (
    "Also write bench-summary.json in the evaluation directory, exactly this shape with integers "
    '(null only when not measured): {"fidelity": {"passed": n, "denominator": n, "excluded_ambiguous": n, '
    '"unknown": n, "disagreements": n}, "retrieval": {"probes": n, "hit_at_1": n, "hit_at_5": n, "mrr": x}, '
    '"structural": {"errors": n, "warnings": n, "unknowns": n}} where hit_at_1/hit_at_5 are probe counts, '
    "mrr a fraction, and the fidelity denominator excludes ambiguous and unknown items."
)


def prompt_path(cfg, book):
    return EXP / f"prompts/mc3b-eval-{cfg}-b{book}-r1.md"


def write(cfg, book, reader):
    tpl = TEMPLATE.read_text().splitlines()
    n = len(json.loads((EXP / f"inputs/books/{book}/images.json").read_text()))
    rep = (
        (EXP / f"runs/{cfg}/books/{book}/output/report.md")
        .read_text()
        .strip()
        .replace("\n", " ")
    )
    head = (
        f"Benchmark validation/evaluation leaf for EXACT {cfg} book{book} {BOOKS[book]} {n} physical pages. "
        f"Evaluator exact {EVALUATOR}; reader {reader}. Grade independently; do not read any other cell's "
        "candidate or evaluation. Disclose cross-provider/model evaluator and unblinded identity; frozen source "
        "reviewer Opus-medium fallible,not human truth. No new Claude work or delegation/generation. Same "
        "evaluation protocol as prior graded cells so results are comparable. Title relevance matching is "
        "case-insensitive (casefold both sides). Section-ID duplicates are a structural finding, not a "
        "retrieval blocker: still index every section record and report the duplicate."
    )
    body = (
        "\n".join(tpl[1:])
        .replace("grok-4-6--medium", cfg)
        .replace("books/6", f"books/{book}")
        .replace("references/6/", f"references/{book}/")
        .replace("6.manager-hashes.txt", f"{book}.manager-hashes.txt")
        .replace("inputs/books/6/", f"inputs/books/{book}/")
        .replace("1–233", f"1–{n}")
    )
    lines = body.splitlines()
    lines[1] = (
        f"This candidate is NOT an agent run: it is a scripted pipeline (no agent turns). Its report.md says: {rep} "
        "Pages whose transcription failed (e.g. provider output filter or empty replies) are ledgered "
        "inspected:true because the image was sent, and each has an unresolved.jsonl entry 'page transcription "
        "failed'; treat their content as omitted. Quantity reviews are guarded pdf_helper crops actually read by "
        "the reader. Token usage and list-price cost are recorded outside the candidate (parent reports them); "
        "record tokens/cost/elapsed as unknown here. Ledger evidence authoritative subject to validation."
    )
    lines = [
        l.replace(
            "Grok route currently 402 balance-exhausted so NO reader postreview/repair will follow: this is a "
            "firstpass-only grade",
            "No reader postreview/repair will follow: this is a firstpass-only grade",
        )
        for l in lines
    ]
    path = prompt_path(cfg, book)
    path.write_text(head + "\n" + "\n".join(lines) + "\n" + SUMMARY + "\n")
    return path
