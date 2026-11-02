"""Agent-reported suspected misreads: validated, content-addressed, append-only.

The serving agent compares library text with the original page (get_page with a region)
and reports a suspected misread here. A report is only a claim. It never changes the
library: an offline blind re-read decides it (scripts/triage_reports.py), and accepted
corrections enter a later publication.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import UTC, datetime

from .storage import Conflict, IntegrityError

VERSION = "transcription-report.v1"
KINDS = ("quantity", "missing_text", "other")
PREFIX = "reports"
MAX_QUOTED = 500
MAX_PROPOSED = 500
MAX_NOTE = 1000
_SPACE = re.compile(r"\s+")


def squash(text):
    """Whitespace-normalized text, used for matching and for the report identity."""
    return _SPACE.sub(" ", text).strip()


def check_region(region):
    """A normalized [left, top, right, bottom] page box, at least 2% on each side."""
    if region is None:
        return None
    if (
        not isinstance(region, (list, tuple))
        or len(region) != 4
        or not all(isinstance(v, (int, float)) for v in region)
    ):
        raise IntegrityError("invalid region")
    x0, y0, x1, y1 = (float(v) for v in region)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise IntegrityError("invalid region")
    if x1 - x0 < 0.02 or y1 - y0 < 0.02:
        raise IntegrityError("region too small")
    return [round(v, 4) for v in (x0, y0, x1, y1)]


def report_id(body):
    """Content address over what was claimed, not who or when: a repeat is the same report."""
    claim = {
        k: body[k]
        for k in (
            "publication_id",
            "book_id",
            "source_id",
            "physical_page",
            "section_id",
            "kind",
            "quoted_text",
            "proposed_text",
            "region",
        )
    }
    raw = json.dumps(claim, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class ReportSink:
    """Writes reports to a store that holds nothing else (a reports-only bucket)."""

    def __init__(self, store, *, max_per_hour=60, clock=time.monotonic):
        self.store = store
        self.max_per_hour = max_per_hour
        self.clock = clock
        self.lock = threading.Lock()
        self.recent = []

    def admit(self):
        # Bounds a looping client; the allowlist, not this, is the access boundary.
        with self.lock:
            now = self.clock()
            self.recent = [t for t in self.recent if now - t < 3600]
            if len(self.recent) >= self.max_per_hour:
                raise IntegrityError("report rate limit")
            self.recent.append(now)

    def submit(
        self,
        library,
        *,
        publication_id,
        book_id,
        source_id,
        physical_page,
        quoted_text,
        proposed_text,
        kind,
        section_id=None,
        note="",
        region=None,
    ):
        if kind not in KINDS:
            raise IntegrityError("invalid report kind")
        quoted, proposed, note = (
            squash(quoted_text),
            squash(proposed_text),
            note.strip(),
        )
        if not 0 < len(quoted) <= MAX_QUOTED or not 0 < len(proposed) <= MAX_PROPOSED:
            raise IntegrityError("invalid report text")
        if quoted == proposed or len(note) > MAX_NOTE:
            raise IntegrityError("invalid report text")
        region = check_region(region)
        page = library.page_context(
            publication_id, book_id, source_id, physical_page, section_id
        )
        # The quote anchors the claim to text the library actually serves.
        if not any(quoted in squash(t) for t in page["texts"]):
            raise IntegrityError("quoted text not found")
        body = {
            "version": VERSION,
            "publication_id": page["publication_id"],
            "book_id": book_id,
            "source_id": source_id,
            "source_sha256": page["source_sha256"],
            "format": page["format"],
            "physical_page": physical_page,
            "section_id": section_id,
            "kind": kind,
            "quoted_text": quoted,
            "proposed_text": proposed,
            "region": region,
        }
        rid = report_id(body)
        self.admit()
        record = {
            **body,
            "report_id": rid,
            "note": note,
            "reporter": {"kind": "agent"},
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        key = f"{PREFIX}/{body['publication_id']}/{rid}.json"
        data = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1).encode()
        try:
            self.store.put_bytes(key, data)  # conditional create; never overwrites
            status = "recorded"
        except Conflict:
            status = "already_recorded"
        return {
            "report_id": rid,
            "status": status,
            "verification": "pending",
            "message": "Recorded for offline blind re-reading. The library text is unchanged until a "
            "later publication; do not present the proposed reading as library text.",
        }


def list_reports(store, publication_id=None):
    """Every stored report (for the offline triage), oldest first."""
    prefix = PREFIX if publication_id is None else f"{PREFIX}/{publication_id}"
    out = []
    for key in store.list(prefix):
        if key.endswith(".json"):
            r = json.loads(store.read(key))
            if r.get("version") == VERSION and r["report_id"] == report_id(r):
                out.append(r)
    return sorted(out, key=lambda r: (r["created_at"], r["report_id"]))
