"""Summarize private browser samples without copying queries or source content."""

import argparse
import json
import statistics
from pathlib import Path

LABELS = [
    "Whole-library A",
    "Whole-library B",
    "No match",
    "Recipe filter",
    "Book scope",
]


def summarize(samples):
    if len(samples) != 50:
        raise ValueError("Expected five cases, five rounds, and two sides")
    rows = []
    for case, label in enumerate(LABELS):
        case_samples = [s for s in samples if s["case"] == case]
        row = {"case": label}
        for side in ("baseline", "candidate"):
            trials = [s for s in case_samples if s["side"] == side]
            if len(trials) != 5 or {s["round"] for s in trials} != set(range(5)):
                raise ValueError("Each case and side must have all five rounds")
            successful = [
                s
                for s in trials
                if s["finished"]
                and s["failedGroups"] == 0
                and any(
                    r["path"] == "/reader/search/results" and r.get("status") == 200
                    for r in s["requests"]
                )
            ]
            times = [s["ms"] for s in successful]
            requests = [r for s in trials for r in s["requests"]]
            row[side] = {
                "attempts": len(trials),
                "successful": len(successful),
                "median_ms": statistics.median(times) if times else None,
                "range_ms": [min(times), max(times)] if times else None,
                "failed_groups": sum(s["failedGroups"] or 0 for s in trials),
                "action_requests": sum(not r["monitor"] for r in requests),
                "action_http_errors": sum(
                    not r["monitor"]
                    and (bool(r.get("error")) or r.get("status", 0) >= 400)
                    for r in requests
                ),
                "monitor_requests": sum(r["monitor"] for r in requests),
                "monitor_http_errors": sum(
                    r["monitor"] and (bool(r.get("error")) or r.get("status", 0) >= 400)
                    for r in requests
                ),
            }
        row["identical_results"] = (
            all(s.get("resultHash") for s in case_samples)
            and len({s["resultHash"] for s in case_samples}) == 1
        )
        row["identical_dom"] = len({s["domHash"] for s in case_samples}) == 1
        rows.append(row)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurements", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            summarize(json.loads(args.measurements.read_text())["samples"]), indent=2
        )
    )
