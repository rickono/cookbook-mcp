"""PROTOTYPE: run a frozen, private must-find pool through the live keyword trial.

No OCR, ingestion, model calls or generated fit grades. Case files, source
evidence, returned candidates and review notes must stay outside the checkout.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import statistics
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PRIVATE = Path.home() / "cookbook-mcp-data/poc/typesense-prototype-20261009/evaluation"
ALLOWANCES = (10, 25)
CONFIGS = [
    {"id": "sqlite-expanded", "label": "SQLite · expanded", "engine": "sqlite", "expanded": True},
    {"id": "sqlite-literal", "label": "SQLite · literal", "engine": "sqlite", "expanded": False},
    {"id": "ts-expanded", "label": "Typesense · expanded", "engine": "typesense", "expanded": True},
    {"id": "ts-literal", "label": "Typesense · literal", "engine": "typesense", "expanded": False},
    {"id": "ts-first-hit", "label": "Typesense · literal, first-hit recovery", "engine": "typesense", "expanded": False, "recovery_target": 1},
    {"id": "ts-all-terms", "label": "Typesense · literal, every term", "engine": "typesense", "expanded": False, "require_all": True},
    {"id": "ts-title-10", "label": "Typesense · literal, title weight 10", "engine": "typesense", "expanded": False, "title_weight": 10},
    {"id": "ts-no-typos", "label": "Typesense · literal, no typos", "engine": "typesense", "expanded": False, "typos": False},
]
DEFAULTS = {"title_weight": 5, "recovery_target": 100, "typos": True, "require_all": False}


def api(base, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = Request(base + path, data=body, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def private_path(path):
    root = Path(__file__).resolve().parents[2]
    path = path.resolve()
    if path.is_relative_to(root):
        raise ValueError("Keep evaluation inputs and output outside the checkout")
    return path


def summary(run):
    rows = []
    for allowance in ALLOWANCES:
        for config in CONFIGS:
            selected = [r for r in run["results"] if r["config_id"] == config["id"] and r["allowance"] == allowance]
            missing = sum(len(r["missing"]) for r in selected)
            total = sum(len(r["anchor_ranks"]) for r in selected)
            rows.append({
                "config_id": config["id"], "label": config["label"], "allowance": allowance,
                "anchor_occurrences": total, "missing": missing, "retained": total - missing,
                "known_coverage": round((total - missing) / total, 4),
                "checks_with_miss": sum(bool(r["missing"]) for r in selected),
                "checks": len(selected), "cutoff_checks": sum(r["cutoff"] for r in selected),
                "median_round_trip_ms": round(statistics.median(r["ms"] for r in selected), 2),
                "returned": sum(len(r["items"]) for r in selected),
            })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=PRIVATE / "cases.json")
    parser.add_argument("--output", type=Path, default=PRIVATE)
    parser.add_argument("--url", default="http://127.0.0.1:8772")
    args = parser.parse_args()
    address = urlsplit(args.url)
    if address.scheme != "http" or address.hostname not in ("127.0.0.1","localhost") or address.username or address.password or address.path not in ("", "/") or address.query or address.fragment:
        raise ValueError("Use the loopback-only keyword prototype")
    args.url = args.url.rstrip("/")
    cases_path, output = private_path(args.cases), private_path(args.output)
    source_bytes = cases_path.read_bytes()
    manifest = json.loads(source_bytes)
    state = api(args.url, "/api/state")
    if state["mode"] != "keyword" or state["snapshot"] != manifest["snapshot"]:
        raise ValueError("The frozen pool must match this keyword-only source snapshot")
    checked = set()
    for case in manifest["cases"]:
        if not case["anchors"] or len(case["anchors"]) > min(ALLOWANCES):
            raise ValueError("Each check needs a nonempty anchor set within the result allowance")
        if len({a["id"] for a in case["anchors"]}) != len(case["anchors"]):
            raise ValueError("Duplicate anchor within a check")
        for anchor in case["anchors"]:
            if case["book_id"] and anchor["book_id"] != case["book_id"]:
                raise ValueError("Anchor is outside the selected book")
            if anchor["id"] in checked:
                continue
            recipe = api(args.url, "/api/recipe?id=" + anchor["id"])
            if hashlib.sha256(recipe["text"].encode()).hexdigest() != anchor["source_sha256"]:
                raise ValueError("An anchor's source changed; re-audit before comparing")
            checked.add(anchor["id"])
    print(f"Frozen pool: {len(manifest['cases'])} checks, {len(checked)} unique source-verified anchors", flush=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    run = {
        "schema_version": 1, "created_at": now.isoformat(),
        "cases_sha256": hashlib.sha256(source_bytes).hexdigest(), "manifest": manifest,
        "snapshot": state["snapshot"], "candidates": state["candidates"], "books": len(state["books"]),
        "typesense_version": state["version"], "allowances": list(ALLOWANCES),
        "configs": CONFIGS, "defaults": DEFAULTS, "results": [],
        "limitations": [
            "Ten concrete diagnostic requests plus one book-scope control; not held out or representative of owner requests.",
            "The paired correct/typo requests and book control share anchors; occurrences are reported separately from unique recipes.",
            "Known-anchor coverage only; the independent pool is deliberately incomplete and cannot establish full recall.",
            "An unlisted returned recipe is unjudged, not automatically irrelevant.",
            "Source facts and agent review are separate from owner fit judgments. Boundaries, supporting work and images remain provisional.",
            "Sequential single-request timings are observations, not production benchmarks. No semantic retrieval was run.",
        ],
    }
    started = time.perf_counter()
    for case in manifest["cases"]:
        for allowance in ALLOWANCES:
            for config in CONFIGS:
                params = DEFAULTS | {k: v for k, v in config.items() if k not in ("id", "label", "engine")}
                params |= {"query": case["query"], "book_id": case["book_id"], "limit": allowance}
                response = api(args.url, "/api/search", params)
                result = response[config["engine"]]
                if case["book_id"] and any(p["book_id"] != case["book_id"] for p in result["items"]):
                    raise ValueError("Result outside the requested book")
                ranks = {p["id"]: i + 1 for i, p in enumerate(result["items"])}
                anchor_ranks = {a["id"]: ranks.get(a["id"]) for a in case["anchors"]}
                run["results"].append({
                    "case_id": case["id"], "config_id": config["id"], "engine": config["engine"],
                    "allowance": allowance, "request_params": params, "terms": response["terms"],
                    "engine_params": result.get("params", result.get("policy")),
                    "items": result["items"], "found": result["found"], "ms": result["ms"],
                    "cutoff": bool(result.get("cutoff", False)),
                    "anchor_ranks": anchor_ranks, "missing": [i for i, rank in anchor_ranks.items() if rank is None],
                })
        print(f"Compared {case['id']}", flush=True)
    run["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    run["summary"] = summary(run)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = "run-" + now.strftime("%Y%m%d-%H%M%S") + ".json"
    raw = json.dumps(run, ensure_ascii=False, indent=2)
    path = output / filename
    with path.open("x") as f:
        f.write(raw)
    path.chmod(0o600)
    tmp = output / "latest.tmp"
    tmp.write_text(raw)
    tmp.chmod(0o600)
    tmp.replace(output / "latest.json")
    print(f"Private evidence: {path}\nView: {args.url}/evaluation", flush=True)
    for row in run["summary"]:
        print(f"@{row['allowance']:2} {row['label']:44} misses {row['missing']:2}/{row['anchor_occurrences']} | checks with a miss {row['checks_with_miss']}/{row['checks']}")


if __name__ == "__main__":
    main()
