"""Durable administrative recovery admission; no source processing or approval.

Reservations commit before dispatch. Unfinished reservations remain charged forever;
restarting a worker never converts an interrupted dispatch into a free attempt.
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


def _now():
    return datetime.now(UTC).isoformat()


def _overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


class RecoveryLedger:
    """One shared SQLite file for all workers, candidates, tools and output runs.

    Bounds are original physical-page normalized coordinates, never candidate IDs.
    Overlapping/renamed/split regions inherit all connected accounting. The
    conservative overlap rule can share allowance between adjacent recovery scopes.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY, attempt TEXT NOT NULL,
                event TEXT NOT NULL, body TEXT NOT NULL)""")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def _append(self, db, attempt, event, body):
        db.execute(
            "INSERT INTO events(attempt,event,body) VALUES (?,?,?)",
            (
                attempt,
                event,
                json.dumps({**body, "timestamp": _now()}, allow_nan=False),
            ),
        )

    def _history(self, db):
        rows = db.execute(
            "SELECT attempt,event,body FROM events ORDER BY sequence"
        ).fetchall()
        attempts = {}
        for aid, event, raw in rows:
            body = json.loads(raw)
            if event == "dispatch":
                attempts[aid] = {"id": aid, **body, "events": []}
            else:
                attempts[aid]["events"].append({"event": event, **body})
        for attempt in attempts.values():
            attempt["dispatch_status"] = (
                "finished"
                if any(e["event"] == "outcome" for e in attempt["events"])
                else "unfinished"
            )
        return list(attempts.values())

    def _scope(self, attempts, source, page, box):
        same = [a for a in attempts if a["source"] == source and a["page"] == page]
        connected, boxes = [], [box]
        while True:
            added = [
                a
                for a in same
                if a not in connected and any(_overlaps(a["box"], b) for b in boxes)
            ]
            if not added:
                break
            connected.extend(added)
            boxes.extend(a["box"] for a in added)
        return same, connected

    def _terminal_attempts(self, attempts, source, page, book):
        # Persisted aliases/correspondence form a page-local lineage. A refusal
        # cannot be escaped by alternating catalogue aliases and source scans.
        sources, books = {source}, {book}
        connected = []
        while True:
            added = []
            for attempt in attempts:
                if attempt in connected or attempt["page"] != page:
                    continue
                identities = [
                    {"source": attempt["source"], "book": attempt["book"]}
                ] + [e for e in attempt["events"] if e["event"] == "terminal_alias"]
                if any(
                    i["source"] in sources or i["book"] in books for i in identities
                ):
                    added.append(attempt)
                    sources.update(i["source"] for i in identities)
                    books.update(i["book"] for i in identities)
            if not added:
                break
            connected.extend(added)
        return [
            a
            for a in connected
            if any(e.get("status") == "terminal_unavailable" for e in a["events"])
        ]

    def status(self, *, source, page, box, book):
        with self._connect() as db:
            attempts = self._history(db)
        same, connected = self._scope(attempts, source, page, box)
        terminal_attempts = self._terminal_attempts(attempts, source, page, book)
        return {
            "region_remaining": max(
                0, 2 - sum(a["route"] == "additional" for a in connected)
            ),
            "page_remaining": max(0, 6 - sum(a["route"] == "additional" for a in same)),
            "terminal": bool(terminal_attempts),
            "terminal_attempts": terminal_attempts,
            "attempts": same,
            "region_attempt_ids": [a["id"] for a in connected],
        }

    def admit(
        self, *, source, page, box, book, actor, tool, configuration, inputs, purpose
    ):
        if not (
            isinstance(source, str)
            and source
            and isinstance(book, str)
            and book
            and type(page) is int
            and page > 0
            and len(box) == 4
            and all(type(v) in (int, float) for v in box)
            and 0 <= box[0] < box[2] <= 1
            and 0 <= box[1] < box[3] <= 1
            and actor
            and tool
            and configuration
            and inputs
            and purpose
        ):
            raise ValueError("invalid recovery identity or provenance")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attempts = self._history(db)
            same, connected = self._scope(attempts, source, page, box)
            terminal = self._terminal_attempts(attempts, source, page, book)
            if terminal:
                self._append(
                    db,
                    terminal[0]["id"],
                    "terminal_alias",
                    {"source": source, "book": book, "page": page},
                )
                return None, "terminal_unavailable"
            route = "additional" if connected else "initial"
            if route == "additional" and (
                sum(a["route"] == "additional" for a in connected) >= 2
                or sum(a["route"] == "additional" for a in same) >= 6
            ):
                return None, "budget_exhausted"
            aid = uuid.uuid4().hex
            self._append(
                db,
                aid,
                "dispatch",
                {
                    "source": source,
                    "page": page,
                    "box": list(box),
                    "book": book,
                    "actor": actor,
                    "tool": tool,
                    "configuration": configuration,
                    "inputs": inputs,
                    "purpose": purpose,
                    "route": route,
                    "inherited_attempt_ids": [a["id"] for a in connected],
                },
            )
            return aid, None

    def record(self, attempt, event, **evidence):
        """Append stage evidence/outcome; never replace earlier dispatch or evidence."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM events WHERE attempt=?", (attempt,)
            ).fetchone():
                raise ValueError("unknown recovery attempt")
            self._append(db, attempt, event, evidence)
