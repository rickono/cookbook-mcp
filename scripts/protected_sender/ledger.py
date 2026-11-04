"""Private, durable admission shared by every role/provider in one pilot."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

CEILING_MICROUSD = 250_000_000


@contextmanager
def transaction(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path, *, prior_spend, prior_liabilities, prior_attempts):
    """Explicit reconciliation inputs; never initialize a missing balance to zero."""
    if any(type(n) is not int or n < 0 for n in (prior_spend, prior_liabilities)):
        raise ValueError("Explicit reconciled integer microdollar balances required")
    if prior_spend + prior_liabilities > CEILING_MICROUSD:
        raise ValueError("Existing obligations exceed pilot ceiling")
    if any(not k or type(v) is not int or v < 0 for k, v in prior_attempts.items()):
        raise ValueError("Invalid reconciled attempt counters")
    Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation prevents a restart from resetting accounting.
    with Path(path).open("xb"):
        pass
    Path(path).chmod(0o600)
    with transaction(path) as db:
        db.execute(
            "CREATE TABLE pilot (spent INTEGER, liabilities INTEGER, blocked INTEGER)"
        )
        db.execute(
            "INSERT INTO pilot VALUES (?, ?, 0)", (prior_spend, prior_liabilities)
        )
        db.execute("CREATE TABLE attempts (scope TEXT PRIMARY KEY, used INTEGER)")
        db.executemany("INSERT INTO attempts VALUES (?, ?)", prior_attempts.items())
        db.execute(
            "CREATE TABLE requests (id TEXT PRIMARY KEY, identity TEXT, reservation INTEGER, actual INTEGER, state TEXT)"
        )


def reserve(path, request_id, identity, maximum_cost, scopes):
    """Commit liability and all edition/page/region counters before dispatch.

    Scope keys are canonical edition-hash/physical-page[/region] identities,
    never provider, role, packet, or crop IDs. A repeated context page occurs once
    in this dispatch's scope set and consumes another attempt on every dispatch.
    """
    if not Path(path).is_file():
        raise ValueError("Pilot ledger requires explicit reconciliation")
    if (
        not request_id
        or not identity
        or type(maximum_cost) is not int
        or maximum_cost <= 0
    ):
        raise ValueError("Invalid reservation identity/charge")
    if not scopes or any(
        type(cap) is not int or cap not in (3, 6) for cap in scopes.values()
    ):
        raise ValueError("Canonical region/page caps required")
    for key, cap in scopes.items():
        parts = key.split("/")
        if (
            len(parts) not in (2, 3)
            or len(parts[0]) != 64
            or any(c not in "0123456789abcdef" for c in parts[0])
            or not parts[1].isdigit()
            or str(int(parts[1])) != parts[1]
            or int(parts[1]) <= 0
            or cap != (6 if len(parts) == 2 else 3)
            or (len(parts) == 3 and not parts[2])
        ):
            raise ValueError("Noncanonical page/region counter")
        if len(parts) == 3 and "/".join(parts[:2]) not in scopes:
            raise ValueError(
                "Region reservation must also consume its physical page attempt"
            )
    with transaction(path) as db:
        if db.execute("SELECT 1 FROM requests WHERE id=?", (request_id,)).fetchone():
            raise ValueError("Request already admitted; reconcile, never resend")
        if db.execute(
            "SELECT 1 FROM requests WHERE identity=? AND state='uncertain'", (identity,)
        ).fetchone():
            raise ValueError("Same request has an uncertain liability; do not resend")
        spent, liabilities, blocked = db.execute("SELECT * FROM pilot").fetchone()
        if blocked:
            raise ValueError("Admission blocked pending charge investigation")
        if spent + liabilities + maximum_cost > CEILING_MICROUSD:
            raise ValueError("Pilot budget exhausted or liabilities unresolved")
        for key, cap in scopes.items():
            row = db.execute(
                "SELECT used FROM attempts WHERE scope=?", (key,)
            ).fetchone()
            used = row[0] if row else 0
            if used >= cap:
                raise ValueError("Shared attempt ceiling exhausted")
            db.execute(
                "INSERT INTO attempts VALUES (?, ?) ON CONFLICT(scope) DO UPDATE SET used=excluded.used",
                (key, used + 1),
            )
        db.execute("UPDATE pilot SET liabilities=liabilities+?", (maximum_cost,))
        db.execute(
            "INSERT INTO requests VALUES (?, ?, ?, NULL, 'uncertain')",
            (request_id, identity, maximum_cost),
        )


def settle(path, request_id, actual_cost):
    """Only verified billing/usage can release an uncertain charge reservation."""
    if type(actual_cost) is not int or actual_cost < 0:
        raise ValueError("Verified integer microdollar charge required")
    with transaction(path) as db:
        row = db.execute(
            "SELECT reservation, actual, state FROM requests WHERE id=?", (request_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown request")
        reservation, actual, state = row
        if state in {"settled", "investigation"}:
            if actual != actual_cost:
                raise ValueError("Conflicting settlement")
            if state == "investigation":
                raise ValueError("Verified overrun remains under investigation")
            return
        if actual_cost > reservation:
            # Preserve the larger obligation and close further admission; the
            # exception is raised after committing the accounting correction.
            db.execute(
                "UPDATE pilot SET liabilities=liabilities+?",
                (actual_cost - reservation,),
            )
            db.execute("UPDATE pilot SET blocked=1")
            db.execute(
                "UPDATE requests SET reservation=?, actual=?, state='investigation' WHERE id=?",
                (actual_cost, actual_cost, request_id),
            )
            overrun = True
        else:
            db.execute(
                "UPDATE pilot SET spent=spent+?, liabilities=liabilities-?",
                (actual_cost, reservation),
            )
            db.execute(
                "UPDATE requests SET actual=?, state='settled' WHERE id=?",
                (actual_cost, request_id),
            )
            overrun = False
    if overrun:
        raise ValueError(
            "Charge exceeded reservation; liability retained, investigate rates"
        )


def snapshot(path):
    with transaction(path) as db:
        spent, liabilities, blocked = db.execute("SELECT * FROM pilot").fetchone()
        return {
            "spent": spent,
            "liabilities": liabilities,
            "blocked": bool(blocked),
            "attempts": dict(db.execute("SELECT * FROM attempts")),
            "requests": [
                dict(zip(("id", "identity", "reservation", "actual", "state"), row))
                for row in db.execute("SELECT * FROM requests")
            ],
        }
