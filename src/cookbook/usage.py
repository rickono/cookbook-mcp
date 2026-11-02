"""Opt-in, content-free, best-effort retrieval telemetry, separate from serving state."""

import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

OPERATIONS = {
    "search",
    "read_section",
    "get_page",
    "get_image",
    "inspect_image",
    "get_artifact",
    "list_images",
    "get_book",
}
TOKEN = re.compile(r"[A-Za-z0-9_.:/-]{1,200}\Z")


def token(value):
    return value if isinstance(value, str) and TOKEN.fullmatch(value) else None


class UsageRecorder:
    def __init__(
        self, path, *, clock=time.time, max_bytes=100 * 1024**2, retention=90 * 86400
    ):
        self.path = Path(path)
        self.clock, self.max_bytes, self.retention = (
            clock,
            min(max_bytes, 100 * 1024**2),
            min(retention, 90 * 86400),
        )
        self.lost = 0
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA max_page_count=" + str(max(16, self.max_bytes // 4096)))
            db.execute(
                "CREATE TABLE IF NOT EXISTS info (key TEXT PRIMARY KEY, value TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, at REAL, operation TEXT, outcome TEXT, publication TEXT, source TEXT, book TEXT, target TEXT, continuation INTEGER, zoom INTEGER, duration_ms REAL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS events_at ON events(at)")
            db.execute("DELETE FROM events WHERE at < ?", (clock() - self.retention,))
            db.execute(
                "INSERT OR IGNORE INTO info VALUES ('started_at',?)", (str(clock()),)
            )
            db.execute(
                "INSERT OR REPLACE INTO info VALUES ('version','retrieval-events.v1')"
            )
        self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=0.01)

    def record(
        self,
        operation,
        kwargs,
        result=None,
        *,
        error=False,
        duration_ms=0,
        event_id=None,
    ):
        if operation not in OPERATIONS:
            return
        if not self.lock.acquire(blocking=False):
            self.lost += 1
            return
        try:
            now = self.clock()
            data = result[0] if isinstance(result, tuple) else result or {}
            citation = data.get("citation", {})
            publication = token(
                data.get("publication_id")
                or citation.get("publication_id")
                or kwargs.get("publication_id")
            )
            outcome = (
                "error"
                if error
                else "withheld"
                if operation == "read_section"
                and (
                    not data.get("text")
                    or any(
                        reason
                        in {
                            "approval_revoked",
                            "confirmed_substantive_error",
                            "superseded_transcription",
                        }
                        for reason in data.get("eligibility", {}).get("reasons", [])
                    )
                )
                else "success"
            )
            base = event_id or uuid.uuid4().hex
            rows = []
            targets = [
                (
                    token(citation.get("source_id") or kwargs.get("source_id")),
                    token(citation.get("book_id") or kwargs.get("book_id")),
                    token(
                        kwargs.get("section_id")
                        or kwargs.get("image_id")
                        or str(kwargs.get("physical_page", ""))
                        or kwargs.get("artifact_id")
                    ),
                )
            ]
            if operation == "search" and not error:
                # One appearance per returned edition, irrespective of alias/hit count.
                targets = sorted(
                    {
                        (token(r.get("citation", {}).get("source_id")), None, None)
                        for r in data.get("results", [])
                    },
                    key=str,
                )
                if not targets:
                    targets = [(None, None, None)]
            for i, (source, book, target) in enumerate(targets):
                rows.append(
                    (
                        f"{base}:{i}",
                        now,
                        operation,
                        outcome,
                        publication,
                        source,
                        book,
                        target,
                        int(bool(kwargs.get("offset"))),
                        int(bool(kwargs.get("region"))),
                        min(3600000, max(0, duration_ms)),
                    )
                )
            with closing(self.connect()) as db, db:
                db.execute("DELETE FROM events WHERE at < ?", (now - self.retention,))
                # Leave room for transaction/journal overhead, reusing SQLite free pages.
                while (
                    db.execute("SELECT count(*) FROM events").fetchone()[0]
                    and (
                        db.execute("PRAGMA page_count").fetchone()[0]
                        - db.execute("PRAGMA freelist_count").fetchone()[0]
                    )
                    * 4096
                    > self.max_bytes * 0.8
                ):
                    db.execute(
                        "DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY at,id LIMIT 1000)"
                    )
                db.executemany(
                    "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
                )
                db.execute(
                    "INSERT OR REPLACE INTO info VALUES ('known_lost',?)",
                    (str(self.lost),),
                )
                db.execute(
                    "INSERT OR REPLACE INTO info VALUES ('last_observed_at',?)",
                    (str(now),),
                )
        except (OSError, sqlite3.Error, ValueError, TypeError):
            self.lost += 1
        finally:
            self.lock.release()


def aggregate(paths, *, days=7, publication=None, now=None):
    from .dashboard.metadata import read_db

    now = time.time() if now is None else now
    start = max(now - 90 * 86400, now - days * 86400 if days else 0)
    events, collectors, errors = {}, [], []
    for path in paths:
        try:
            with read_db(path) as db:
                info = dict(db.execute("SELECT key,value FROM info"))
                if info.get("version") != "retrieval-events.v1":
                    raise ValueError("unsupported telemetry")
                first = db.execute("SELECT min(at) FROM events").fetchone()[0]
                collectors.append(
                    {
                        "started_at": float(info["started_at"]),
                        "retained_from": first,
                        "known_lost": int(info.get("known_lost", 0)),
                        "last_observed_at": info.get("last_observed_at"),
                        "coverage": "best effort; crash/restart loss unknown",
                    }
                )
                for row in db.execute(
                    "SELECT * FROM events WHERE at >= ? AND at <= ?", (start, now)
                ):
                    r = dict(row)
                    if not publication or r["publication"] == publication:
                        events.setdefault(r["id"], r)
        except (OSError, sqlite3.Error, ValueError, KeyError):
            errors.append("telemetry source unavailable or unsupported")
    totals, editions, daily, unique, calls = {}, {}, {}, set(), set()
    from datetime import UTC, datetime

    for r in events.values():
        metric = r["operation"] + ("_zoom" if r["zoom"] else "") + ":" + r["outcome"]
        # One invocation can produce several per-edition search appearance rows.
        invocation = r["id"].rsplit(":", 1)[0]
        first_call = invocation not in calls
        calls.add(invocation)
        if first_call:
            totals[metric] = totals.get(metric, 0) + 1
        if r["operation"] == "search" and r["source"]:
            totals["search_appearances"] = totals.get("search_appearances", 0) + 1
        if r["continuation"] and first_call:
            totals["continuation_calls"] = totals.get("continuation_calls", 0) + 1
        key = r["source"] or "unattributed"
        by = editions.setdefault(key, {})
        if r["operation"] != "search" or r["source"]:
            by[metric] = by.get(metric, 0) + 1
        day = datetime.fromtimestamp(r["at"], UTC).strftime("%Y-%m-%d")
        if first_call:
            daily[day] = daily.get(day, 0) + 1
        if r["target"] and r["outcome"] == "success":
            unique.add((r["publication"], r["source"], r["operation"], r["target"]))
    return {
        "status": "partial"
        if errors
        else "collecting"
        if collectors
        else "usage collection not started",
        "collectors": collectors,
        "errors": errors,
        "totals": totals,
        "editions": editions,
        "daily": daily,
        "unique_content_scopes": len(unique),
        "window_days": days,
        "publication": publication,
        "publications": sorted(
            {r["publication"] for r in events.values() if r["publication"]}
        ),
    }
