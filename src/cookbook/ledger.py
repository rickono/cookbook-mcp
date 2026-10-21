"""The correction ledger: accepted transcription corrections, in decision order.

scripts/triage_reports.py regenerates ``ledger.jsonl`` from its decisions. Each row is
one accepted correction, keyed by source digest, physical page, optional section and region,
``from_text`` and ``to_text``; it carries the reviewer, evidence hashes and votes. Rows bind
to a source by digest and page, never to the publication a report was filed against, so a
report against a retired publication still applies to the next build of the same source.

Standard library only, like ``scanned``: the build, the gate and the refresh command share it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .storage import IntegrityError, canonical, source_digest

FILE = "ledger.jsonl"
KEYS = (
    "id",
    "decided_at",
    "publication_id",
    "book_id",
    "source_id",
    "source_sha256",
    "physical_page",
    "section_id",
    "region",
    "kind",
    "from_text",
    "to_text",
    "state",
    "reviewer",
    "evidence",
)
STATE = "source_reviewed"
_HEX = re.compile(r"[0-9a-f]{64}")
_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class LedgerError(IntegrityError):
    """A correction ledger row that is malformed or out of decision order."""


def key(row):
    """What a correction claims; two rows with one key are the same correction."""
    region = row["region"]
    return (
        row["source_sha256"],
        row["physical_page"],
        row["section_id"],
        None if region is None else tuple(region),
        row["from_text"],
        row["to_text"],
    )


def order(row):
    """Decision order: decision time, then id (decision times have second resolution)."""
    return (row["decided_at"], row["id"])


def _check(row, n):
    w = f"ledger:{n}"
    if not isinstance(row, dict) or set(row) != set(KEYS):
        raise LedgerError(f"{w}: must have exactly {list(KEYS)}")
    for k in ("id", "publication_id", "source_id", "kind"):
        if not isinstance(row[k], str) or not row[k]:
            raise LedgerError(f"{w}.{k}: must be a non-empty string")
    if not isinstance(row["decided_at"], str) or not _TIME.fullmatch(row["decided_at"]):
        raise LedgerError(f"{w}.decided_at: must be YYYY-MM-DDTHH:MM:SSZ")
    sha = row["source_sha256"]
    if not isinstance(sha, str) or not _HEX.fullmatch(sha):
        raise LedgerError(f"{w}.source_sha256: must be a lowercase sha256 hex digest")
    if source_digest(row["source_id"]) != sha:
        raise LedgerError(f"{w}.source_id: does not name source_sha256")
    page = row["physical_page"]
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise LedgerError(f"{w}.physical_page: must be a positive integer")
    if row["section_id"] is not None and not isinstance(row["section_id"], str):
        raise LedgerError(f"{w}.section_id: must be a string or null")
    region = row["region"]
    if region is not None and (
        not isinstance(region, list)
        or len(region) != 4
        or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in region
        )
    ):
        raise LedgerError(f"{w}.region: must be null or [left, top, right, bottom]")
    for k in ("from_text", "to_text"):
        if not isinstance(row[k], str) or not row[k].strip():
            raise LedgerError(f"{w}.{k}: must be a non-empty string")
    if row["state"] != STATE:
        raise LedgerError(f"{w}.state: must be {STATE!r}")
    reviewer = row["reviewer"]
    if (
        not isinstance(reviewer, dict)
        or set(reviewer) != {"kind", "id"}
        or not all(isinstance(v, str) and v for v in reviewer.values())
    ):
        raise LedgerError(f"{w}.reviewer: must be {{kind, id}}")
    if not isinstance(row["evidence"], dict):
        raise LedgerError(f"{w}.evidence: must be an object")


def check(rows):
    """Validated rows in decision order; ids and correction keys must be unique."""
    if not isinstance(rows, list):
        raise LedgerError("ledger must be a list of rows")
    for n, row in enumerate(rows, 1):
        _check(row, n)
    if len({r["id"] for r in rows}) != len(rows):
        raise LedgerError("ledger repeats a correction id")
    if len({key(r) for r in rows}) != len(rows):
        raise LedgerError("ledger repeats a correction")
    return sorted(rows, key=order)


def parse(data: bytes):
    """Rows from ``ledger.jsonl`` bytes (one JSON object per line), in decision order."""
    rows = []
    for n, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as e:
            raise LedgerError(f"ledger:{n}: invalid JSON") from e
    return check(rows)


def read(path: Path):
    """The ledger triage wrote (``ledger.jsonl``); a missing file is an empty ledger."""
    path = Path(path)
    return parse(path.read_bytes()) if path.exists() else []


def for_source(rows, source_sha256):
    """The rows that bind to one source digest, in decision order."""
    return [r for r in check(rows) if r["source_sha256"] == source_sha256]


def dump(rows) -> bytes:
    """Canonical JSONL, as stored beside a scanned candidate in a build's inventory."""
    return b"".join(canonical(r) + b"\n" for r in check(rows))
