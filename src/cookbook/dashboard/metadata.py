"""Explicit, bounded metadata readers. Never open source content or payload inventories."""

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

MAX_METADATA = 16 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")
DIMENSIONS = ("processing", "review", "publication", "access", "eligibility")


def read_json(path):
    with Path(path).open("rb") as f:
        raw = f.read(MAX_METADATA + 1)
    if len(raw) > MAX_METADATA:
        raise ValueError("metadata size limit")
    return json.loads(raw), raw


@contextmanager
def read_db(path):
    db = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1
    )
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        yield db
    finally:
        db.close()


def require(value, condition):
    if not condition:
        raise ValueError("unsupported or inconsistent metadata")
    return value


def identity(record):
    sha = record.get("source_sha256")
    if sha:
        require(sha, isinstance(sha, str) and bool(SHA.fullmatch(sha)))
        return "sha256:" + sha
    return "provisional:" + json.dumps(
        [record["namespace"], str(record["record_id"])], separators=(",", ":")
    )


def coverage(c):
    total = c.get("pages_total", c.get("total"))
    counts = {k: c.get(k, 0) for k in ("transcribed", "blank", "failed")}
    require(c, all(type(v) is int and v >= 0 for v in counts.values()))
    require(c, total is None or (type(total) is int and total >= sum(counts.values())))
    return {
        "kind": "physical_pages",
        "total": total,
        **counts,
        "unaccounted": None if total is None else total - sum(counts.values()),
    }


def project_fact(row):
    # This is a safe projection contract, never arbitrary dictionaries in UI/storage.
    allowed = {
        "edition",
        "dimension",
        "state",
        "candidate",
        "publication",
        "scope",
        "authority",
        "evidence",
        "event_at",
        "reason",
        "next_step",
    }
    require(
        row, row.get("dimension") in DIMENSIONS and isinstance(row.get("state"), str)
    )
    return {k: str(v)[:1000] for k, v in row.items() if k in allowed and v is not None}


def read_source(source):
    kind, path = source["kind"], source["path"]
    if kind == "calibre":
        with read_db(path) as db:
            namespace = db.execute("SELECT uuid FROM library_id").fetchone()[0]
            records = []
            for r in db.execute("SELECT uuid,title FROM books ORDER BY id LIMIT 10001"):
                records.append(
                    {
                        "namespace": namespace,
                        "record_id": r["uuid"],
                        "title": r["title"],
                        "membership": "undecided",
                        "evidence": source["id"],
                    }
                )
            require(records, len(records) <= 10000)
            return {"records": records}
    if kind == "index":
        with read_db(path) as db:
            info = db.execute("SELECT publication_id FROM info").fetchall()
            require(info, len(info) == 1)
            pub = info[0][0]
            require(pub, not source.get("publication") or pub == source["publication"])
            records, facts = [], []
            for r in db.execute(
                "SELECT b.id,b.title,b.source_id,s.sha256,s.format FROM books b JOIN sources s ON s.id=b.source_id ORDER BY b.id LIMIT 10001"
            ):
                record = {
                    "namespace": source["id"],
                    "record_id": r["id"],
                    "title": r["title"],
                    "source_sha256": r["sha256"],
                    "format": r["format"],
                    "membership": "undecided",
                    "evidence": source["id"],
                }
                edition = identity(record)
                records.append(record)
                facts.append(
                    {
                        "edition": edition,
                        "dimension": "publication",
                        "state": "catalog present",
                        "publication": pub,
                        "book_id": r["id"],
                        "source_id": r["source_id"],
                        "evidence": source["id"],
                    }
                )
                sections = db.execute(
                    "SELECT count(*) FROM sections WHERE source_id=?", (r["source_id"],)
                ).fetchone()[0]
                facts.append(
                    {
                        "edition": edition,
                        "dimension": "processing",
                        "state": f"{sections} indexed sections",
                        "publication": pub,
                        "evidence": source["id"],
                    }
                )
            require(records, len(records) <= 10000)
        return {"records": records, "facts": facts, "publication": pub}
    data, raw = read_json(path)
    if kind == "registry":
        require(
            data,
            data.get("version") == "intended-book-registry.v1"
            and isinstance(data.get("records"), list),
        )
        records = []
        for r in data["records"]:
            require(
                r,
                isinstance(r.get("namespace"), str)
                and isinstance(r.get("record_id"), (str, int))
                and r.get("membership") in {"included", "excluded", "undecided"},
            )
            identity(r)
            records.append(
                {
                    k: r[k]
                    for k in (
                        "namespace",
                        "record_id",
                        "title",
                        "format",
                        "source_sha256",
                        "membership",
                        "evidence",
                        "holds",
                        "missing",
                    )
                    if k in r
                }
            )
        return {"records": records}
    if kind == "candidate":
        require(data, data.get("version") == "scanned-candidate.v1")
        sha = data["source"]["sha256"]
        require(sha, bool(SHA.fullmatch(sha)))
        require(sha, not source.get("edition") or source["edition"] == "sha256:" + sha)
        c = coverage(data["coverage"])
        require(c, c["total"] == data["source"]["physical_pages"])
        return {
            "coverage": [
                {
                    "edition": "sha256:" + sha,
                    "candidate": hashlib.sha256(raw).hexdigest(),
                    "coverage": c,
                    "unresolved": data["counts"]["unresolved"],
                    "evidence": source["id"],
                }
            ],
            "facts": [
                {
                    "edition": "sha256:" + sha,
                    "dimension": "review",
                    "state": "unapproved",
                    "candidate": hashlib.sha256(raw).hexdigest(),
                    "scope": "candidate manifest declaration only",
                    "evidence": source["id"],
                }
            ],
        }
    if kind == "build_report":
        require(data, data.get("version") == "scanned-build-report.v1")
        result = {"coverage": [], "corrections": [], "queue": []}
        for s in data["sources"]:
            sha = s["source_id"].split(":")[-1]
            require(sha, bool(SHA.fullmatch(sha)))
            edition = "sha256:" + sha
            result["coverage"].append(
                {
                    "edition": edition,
                    "publication": source.get("publication"),
                    "coverage": coverage(s["pages"]),
                    "unresolved": s["unresolved"],
                    "evidence": source["id"],
                }
            )
            result["corrections"].append(
                {
                    "edition": edition,
                    "stage": "local build",
                    "publication": source.get("publication"),
                    "counts": s["corrections"],
                    "evidence": source["id"],
                }
            )
        # Raw queue items can include correction text. Project identifiers only.
        for i, q in enumerate(data.get("owner_queue", [])):
            sha = str(q.get("source_id", "")).split(":")[-1]
            result["queue"].append(
                {
                    "id": str(
                        q.get("report_id", q.get("correction_id", q.get("id", i)))
                    ),
                    "edition": "sha256:" + sha if SHA.fullmatch(sha) else None,
                    "origin": "build",
                    "outcome": "human edge case",
                    "evidence": source["id"],
                }
            )
        return result
    if kind == "status":
        require(data, data.get("version") == "dashboard-status.v1")
        result = {"facts": [project_fact(f) for f in data.get("facts", [])]}
        for key in ("queue", "blockers", "history", "corrections", "heartbeats"):
            allowed = {
                "id",
                "report_id",
                "edition",
                "origin",
                "outcome",
                "kind",
                "reason",
                "scope",
                "evidence",
                "event_at",
                "candidate",
                "publication",
                "stage",
                "state",
                "next_step",
                "run",
                "worker",
                "phase",
                "at",
                "counts",
            }
            result[key] = [
                {k: v for k, v in r.items() if k in allowed} for r in data.get(key, [])
            ]
        return result
    raise ValueError("unsupported metadata reader")


def assemble(observations, now):
    editions = {}

    def book(key):
        return editions.setdefault(
            key,
            {
                "id": key,
                "title": key,
                "aliases": [],
                "claims": [],
                "holds": [],
                "facts": [],
                "coverage": [],
                "queue": [],
                "blockers": [],
                "history": [],
                "corrections": [],
                "heartbeats": [],
                "provisional": key.startswith("provisional:"),
            },
        )

    for obs in observations:
        data = obs.get("data") or {}
        fresh = obs["status"] == "ok" and now - obs["observed_at"] <= (
            600 if obs.get("remote") else 60
        )
        stamp = {
            "source": obs["id"],
            "observed_at": obs.get("observed_at"),
            "current": fresh,
            "historical_at": obs.get("historical_at"),
        }
        if obs.get("historical_at"):
            stamp["current"] = False
        for r in data.get("records", []):
            b = book(identity(r))
            b["title"] = r.get("title") or b["title"]
            alias = {
                "namespace": r["namespace"],
                "record_id": r["record_id"],
                "format": r.get("format"),
                "missing": r.get("missing", False),
                **stamp,
            }
            if alias not in b["aliases"]:
                b["aliases"].append(alias)
            b["claims"].append(
                {
                    "membership": r.get("membership", "undecided"),
                    "evidence": r.get("evidence", obs["id"]),
                    **stamp,
                }
            )
            b["holds"].extend(
                {
                    "scope": h.get("scope", "unspecified"),
                    "reason": h.get("reason", "unspecified"),
                    **stamp,
                }
                for h in r.get("holds", [])
            )
        for key in (
            "facts",
            "coverage",
            "queue",
            "blockers",
            "history",
            "corrections",
            "heartbeats",
        ):
            for r in data.get(key, []):
                edition = r.get("edition")
                if edition:
                    book(edition)[key].append({**r, **stamp})
    for b in editions.values():
        claims = {c["membership"] for c in b["claims"]} - {"undecided"}
        b["membership"] = (
            next(iter(claims))
            if len(claims) == 1
            else "conflict"
            if claims
            else "undecided"
        )
        b["states"] = {}
        b["previous_states"] = {}
        for dim in DIMENSIONS:
            facts = [f for f in b["facts"] if f["dimension"] == dim and f["current"]]
            b["states"][dim] = (
                "; ".join(sorted({f["state"] for f in facts})) or "unknown"
            )
            b["previous_states"][dim] = sorted(
                {
                    f["state"]
                    for f in b["facts"]
                    if f["dimension"] == dim and not f["current"]
                }
            )
        groups = {}
        for q in b["queue"]:
            groups.setdefault(q.get("report_id", q["id"]), []).append(q)
        b["queue"] = [
            {
                "id": k,
                "origins": sorted({q["origin"] for q in v}),
                "outcomes": sorted({q["outcome"] for q in v}),
                "conflict": len({q["outcome"] for q in v}) > 1,
                "evidence": v,
            }
            for k, v in groups.items()
        ]
        for h in b["heartbeats"]:
            h["activity"] = (
                "unknown"
                if not h["current"]
                else "heartbeat overdue"
                if now - h["at"] > 120
                else "heartbeat observed"
            )
        b["attention"] = bool(
            b["holds"]
            or b["blockers"]
            or b["queue"]
            or b["membership"] == "conflict"
            or any(v == "unknown" for v in b["states"].values())
        )
    return sorted(editions.values(), key=lambda b: (b["title"].casefold(), b["id"]))
