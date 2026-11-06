"""Synthetic HTTP counterexample against the current R2 SessionBook.

Explicit invocation only; known failure is not application release coverage.
Use --runxfail to see the defect fail. No provider/network/OCR is used.
"""

from datetime import UTC, datetime

import pytest
from test_reader_http import reader_env  # noqa: F401
from test_reader_session_races import change, record, world  # noqa: F401


@pytest.mark.xfail(strict=True, reason="Known settlement absolute-expiry gap")
def test_renewal_must_not_grant_after_absolute_expiry(world, monkeypatch, mint):  # noqa: F811
    client, _, reader, identity, clock = world
    entry = next(iter(record(reader)[1]["sessions"].values()))
    clock[0] = entry["created"] + 30 * 86400 - 1

    def recent_activity(owner):
        next(iter(owner["sessions"].values()))["seen"] = clock[0]

    change(reader, recent_activity)

    class AuthorityTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(clock[0], UTC)

    monkeypatch.setattr("jwt.api_jwt.datetime", AuthorityTime)

    async def renew(_):
        clock[0] += 2
        return {
            "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
            "refresh_token": "synthetic-new-refresh",
        }

    identity.renew = renew
    response = client.get("/reader/catalog")
    assert response.status_code == 401
