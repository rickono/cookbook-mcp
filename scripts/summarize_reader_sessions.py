"""Allowlisted numeric attribution from private Fly JSON or reader JSON records.

Reads stdin; never emits request IDs, revisions, payloads, arbitrary routes,
exception text, or input records. Raw captures stay outside Git.
"""

import json
import math
import statistics
import sys

ROUTES = frozenset(
    {
        "/reader",
        "/reader/session",
        "/reader/catalog",
        "/reader/search",
        "/reader/search/results",
        "/reader/read",
        "/reader/personal",
        "/reader/updates",
    }
)
STAGES = frozenset(
    {
        "session_read",
        "session_write",
        "token_verify",
        "renewal_lease",
        "renewal_settle",
        "renewal_wait",
        "provider_renew",
        "provider_revoke",
    }
)


def records(raw):
    decoder = json.JSONDecoder()
    while raw.strip():
        raw = raw.lstrip()
        row, end = decoder.raw_decode(raw)
        raw = raw[end:]
        if isinstance(row, dict) and "message" in row:
            try:
                row = json.loads(row["message"])
            except (ValueError, TypeError):
                continue
        if isinstance(row, dict) and row.get("event") == "reader_request":
            yield row


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def distribution(values):
    return (
        {
            "n": len(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }
        if values
        else None
    )


def summarize(raw):
    groups = {}
    for row in records(raw):
        route, status = row.get("route"), row.get("status")
        if (
            not isinstance(route, str)
            or route not in ROUTES
            or type(status) is not int
            or not 100 <= status <= 599
        ):
            continue
        groups.setdefault(route, []).append(row)
    result = {}
    for route, rows in sorted(groups.items()):
        successful = [r for r in rows if r["status"] == 200]
        stages = {}
        for name in sorted(STAGES):
            observed = [
                r["stages"][name]
                for r in successful
                if isinstance(r.get("stages"), dict)
                and isinstance(r["stages"].get(name), dict)
            ]
            if observed:
                stages[name] = {
                    field: distribution(
                        [v[field] for v in observed if numeric(v.get(field))]
                    )
                    for field in ("ms", "n", "conflicts")
                }
        result[route] = {
            "requests": len(rows),
            "statuses": {
                str(s): sum(r["status"] == s for r in rows)
                for s in sorted({r["status"] for r in rows})
            },
            "successful_wall_ms": distribution(
                [r["ms"] for r in successful if numeric(r.get("ms"))]
            ),
            "stages_observed_on_success": stages,
        }
    return result


if __name__ == "__main__":
    try:
        result = summarize(sys.stdin.read())
    except (ValueError, TypeError, RecursionError):
        raise SystemExit("Invalid diagnostic JSON; no input records emitted") from None
    print(json.dumps(result, sort_keys=True, indent=2))
