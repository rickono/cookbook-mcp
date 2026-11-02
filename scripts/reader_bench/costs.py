"""List-price cost and call time from the per-call records in a pages dir (or a label cache).

Every call record carries its reader label and token usage; prices come from prices.json.
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

import readers as rd

PRICES = json.loads((Path(__file__).parent / "prices.json").read_text())


def price_of(reader):
    backend, model, effort = rd.parse(reader)
    spec = f"{backend}:{model}" + (f"@{effort}" if effort else "")
    if spec not in PRICES:
        raise SystemExit(
            f"no list price for {spec}: add it to {Path(__file__).parent / 'prices.json'}"
        )
    return PRICES[spec]


def list_cost(reader, t):
    p = price_of(reader)
    if (
        "cache_creation_input_tokens" in t
    ):  # claude: input_tokens excludes cache reads and writes
        w, r, fresh = (
            t["cache_creation_input_tokens"],
            t["cache_read_input_tokens"],
            t["input_tokens"],
        )
        prompt = fresh + w + r
    else:  # codex: cached and written tokens are part of input_tokens
        r, w = t.get("cached_input_tokens", 0), t.get("cache_write_input_tokens", 0)
        fresh, prompt = t.get("input_tokens", 0) - r - w, t.get("input_tokens", 0)
    if prompt > p.get("max_prompt_tokens", float("inf")):
        raise SystemExit(f"{reader}: a {prompt}-token prompt is above the priced tier")
    return (
        fresh * p["input"]
        + w * p["cache_write"]
        + r * p["cache_read"]
        + t.get("output_tokens", 0) * p["output"]
    ) / 1e6


def calls_in(x, found):
    if isinstance(x, dict):
        if "model" in x and "errors" in x:
            found.append(x)
            return found
        for v in x.values():
            calls_in(v, found)
    elif isinstance(x, list):
        for v in x:
            calls_in(v, found)
    return found


def summarize(files):
    """files: page or label JSON files. Returns totals; `pages` counts files read."""
    ok, failed, seconds_per_page, n = [], 0, [], 0
    for f in files:
        d = json.loads(Path(f).read_text())
        n += 1
        if "seconds" in d:
            seconds_per_page.append(d["seconds"])
        for c in calls_in(d, []):
            if c.get("tokens"):
                ok.append(c)
            else:
                failed += 1
    cost = sum(list_cost(c["model"], c["tokens"]) for c in ok)
    s = sorted(c["seconds"] for c in ok)
    tokens = defaultdict(int)
    for c in ok:
        for k, v in c["tokens"].items():
            if isinstance(v, int):
                tokens[k] += v
    return {
        "files": n,
        "calls": len(ok),
        "failed_calls": failed,
        "retried_calls": sum(1 for c in ok if c["errors"]),
        "list_usd": round(cost, 4),
        "usd_per_1000_files": round(cost / max(1, n) * 1000, 2),
        "reported_usd": round(sum(c.get("cost_usd") or 0 for c in ok), 4),
        "call_seconds_median": statistics.median(s) if s else None,
        "call_seconds_p90": s[int(0.9 * len(s))] if s else None,
        "page_seconds_median": statistics.median(seconds_per_page)
        if seconds_per_page
        else None,
        "calls_per_file": round(len(ok) / max(1, n), 1),
        "tokens": dict(tokens),
    }
