"""Current substantive-error decisions, independent of immutable publications."""

import hashlib
import json

from .storage import Conflict, IntegrityError, canonical

KEY = "control/content-withdrawals.json"


def affected_decisions(history, candidate, scope, binding):
    """Freeze exact evidence approvals and their transitive required dependents."""
    affected = {
        e["id"]
        for e in history
        if e["action"] in {"approve", "review_portion"}
        and e["scope"] == scope["id"]
        and (e.get("scope_sha256") == binding or e["candidate_id"] == candidate["id"])
    }
    return dependent_decisions(history, affected)


def revoked_approvals(history, scope, relates_to):
    return dependent_decisions(
        history,
        {
            e["id"]
            for e in history
            if e["scope"] == scope
            and e["action"] in {"approve", "review_portion"}
            and (relates_to is None or e["id"] == relates_to)
        },
    )


def dependent_decisions(history, affected):
    while True:
        expanded = affected | {
            e["id"]
            for e in history
            if any(
                b["decision_id"] in affected for b in e.get("dependency_bindings", [])
            )
        }
        if expanded == affected:
            return sorted(affected)
        affected = expanded


def affected_pages(history, affected):
    return [
        {"source_sha256": sha, "physical_page": page}
        for sha, page in sorted(
            {
                (item["source_sha256"], item["physical_page"])
                for event in history
                if event["id"] in affected
                for item in event["evidence"]
            }
        )
    ]


def withdrawn_decisions(history):
    return {
        i
        for e in history
        if e["action"] == "confirm_error"
        for i in e["affected_decisions"]
    }


def current_withdrawals(store):
    raw, _ = store.read_version(KEY)
    events = json.loads(raw) if raw is not None else []
    for event in events:
        validate(event)
    return events


def validate(event):
    if (
        event.get("action") not in {"confirm_error", "revoke"}
        or event.get("actor", {}).get("kind") != "human"
        or (event.get("action") == "confirm_error" and not event.get("evidence"))
        or not isinstance(event.get("affected_decisions"), list)
        or event.get("id")
        != hashlib.sha256(
            canonical({k: v for k, v in event.items() if k != "id"})
        ).hexdigest()
    ):
        raise IntegrityError("invalid substantive-error decision")


def record_withdrawal(store, event):
    """Durably enforce a saved administrative decision; safe to retry after failure.

    Success means every reader using this object store checks the decision on its
    next request, including readers using a retained or cached publication.
    """
    validate(event)
    for _ in range(8):
        raw, version = store.read_version(KEY)
        events = json.loads(raw) if raw is not None else []
        for prior in events:
            validate(prior)
        if any(e["id"] == event["id"] for e in events):
            return event
        try:
            store.put_bytes(KEY, canonical(events + [event]), expected=version)
            return event
        except Conflict:
            continue
    raise Conflict("withdrawal not enforced; retry the recorded decision")
