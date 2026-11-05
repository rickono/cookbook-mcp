"""Reports-only owner observations. No library, session or review authority."""

import asyncio
import hashlib
import json
import re
import time
from html import escape

from cryptography.fernet import InvalidToken
from starlette.responses import JSONResponse

from .reports import check_region
from .storage import Conflict, IntegrityError, canonical

PREFIX = "owner-observations/"


class OwnerReports:
    def __init__(self, store, *, max_per_hour=60, clock=time.time):
        self.store, self.max_per_hour, self.clock = store, max_per_hour, clock

    def submit(self, owner, reference, submission, payload):
        identity = hashlib.sha256(canonical([owner, submission])).hexdigest()
        key = PREFIX + "receipts/" + identity + ".json"
        binding = {"owner": owner, "reference": reference, **payload}
        fingerprint = hashlib.sha256(canonical(binding)).hexdigest()

        def previous():
            raw, _ = self.store.read_version(key)
            if raw is None:
                return None
            prior = json.loads(raw)
            if prior["fingerprint"] != fingerprint:
                return {"error": "submission_conflict"}, 409
            return prior["receipt"], 200

        prior = previous()
        if prior:
            return prior
        # Durable CAS admission shared across replicas; reservations survive ambiguous writes.
        hour = int(self.clock() // 3600)
        rate_key = (
            PREFIX
            + "limits/"
            + hashlib.sha256(owner.encode()).hexdigest()
            + "/"
            + str(hour)
        )
        for _ in range(5):
            raw, version = self.store.read_version(rate_key)
            ids = json.loads(raw) if raw else []
            if identity in ids:
                break
            if len(ids) >= self.max_per_hour:
                return {"error": "rate_limited"}, 429
            try:
                self.store.put_bytes(
                    rate_key, canonical([*ids, identity]), expected=version
                )
                break
            except Conflict:
                continue
        else:
            return {"error": "report_busy"}, 503
        receipt = {
            "status": "received",
            "receipt_id": identity,
            "verification": "unverified",
        }
        record = {
            "version": "owner-observation.v1",
            "reporter": {"kind": "owner", "subject": owner},
            **binding,
            "fingerprint": fingerprint,
            "receipt": receipt,
            "created_at": self.clock(),
        }
        try:
            self.store.put_bytes(key, canonical(record))
        except Conflict:
            return previous()
        return receipt, 200


def form(reader, data, loc, owner, csrf):
    citation = data["citation"]
    locator = citation.get("locator", {})
    pages = locator.get(
        "physical_pages",
        [locator["physical_page"]] if locator.get("physical_page") else [],
    )
    if (
        citation.get("format", "").upper() not in ("PDF", "DJVU")
        or not loc.get("section_id")
        or not pages
    ):
        return ""
    reference = {
        "owner": owner,
        "location": loc,
        "source_sha256": citation["source_sha256"],
        "physical_pages": pages,
        "transcription_version": citation.get("extraction", {}).get("version"),
        "version": "owner-source-reference.v1",
    }
    token = reader.cipher.encrypt(canonical(reference)).decode()
    return (
        "<details><summary>Report a suspected transcription problem</summary>"
        '<p class="fineprint">Receipt means received, not verified. Reporting does not change text or start review. '
        "You can report even when the original image is unavailable.</p>"
        '<form id="owner-report" method="post" action="/reader/reports"><input type="hidden" name="reference" value="'
        + escape(token)
        + '">'
        '<input type="hidden" name="csrf" value="' + escape(csrf) + '">'
        '<label for="report-description">Description (required, 1–1,000 characters)</label>'
        '<textarea id="report-description" name="description" required maxlength="1000"></textarea>'
        '<label for="report-proposal">Proposed text (optional)</label>'
        '<textarea id="report-proposal" name="proposal" maxlength="1000"></textarea>'
        '<label for="report-region">Region (optional: left, top, right, bottom; 0–1)</label>'
        '<input id="report-region" name="region">'
        '<button type="submit">Submit report</button><p id="report-status" role="status"></p></form>'
        '<script src="/reader/reports.js" defer></script></details>'
    )


async def intake(reader, request, owner, session):
    if request.headers.get("origin") != reader.config.origin:
        return JSONResponse({"error": "origin_denied"}, status_code=403)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            return JSONResponse({"error": "report_too_large"}, status_code=413)
    try:
        import secrets

        value = json.loads(body)
        if not isinstance(value, dict) or not secrets.compare_digest(
            value.get("csrf", ""), session.csrf
        ):
            return JSONResponse({"error": "csrf_denied"}, status_code=403)
        if set(value) - {
            "csrf",
            "reference",
            "submission_id",
            "description",
            "proposal",
            "region",
        }:
            raise ValueError()
        reference = json.loads(reader.cipher.decrypt(value["reference"].encode()))
        if (
            reference.get("owner") != owner
            or reference.get("version") != "owner-source-reference.v1"
        ):
            raise ValueError()
        submission = value["submission_id"]
        if not isinstance(submission, str) or not re.fullmatch(
            "[a-f0-9]{32}", submission
        ):
            raise ValueError()
        description, proposal = value["description"], value.get("proposal")
        if (
            not isinstance(description, str)
            or not 1 <= len(description.strip()) <= 1000
            or len(description) > 1000
        ):
            raise ValueError()
        if proposal is not None and (
            not isinstance(proposal, str) or len(proposal) > 1000
        ):
            raise ValueError()
        payload = {
            "description": description,
            "proposal": proposal,
            "region": check_region(value.get("region")),
        }
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        InvalidToken,
        IntegrityError,
    ):
        return JSONResponse({"error": "invalid_report"}, status_code=400)
    if reader.owner_reports is None:
        return JSONResponse({"error": "reporting_unavailable"}, status_code=503)
    try:
        async with asyncio.timeout(8):
            result, status = await asyncio.to_thread(
                reader.owner_reports.submit, owner, reference, submission, payload
            )
    except Exception:  # noqa: BLE001
        # A write may have committed: retry the identical submission, never claim failure is final.
        return JSONResponse({"error": "receipt_unconfirmed"}, status_code=503)
    return JSONResponse(
        result,
        status_code=status,
        headers={"Retry-After": "60"} if status == 429 else None,
    )
