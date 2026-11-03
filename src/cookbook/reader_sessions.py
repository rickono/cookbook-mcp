"""Sole owner of encrypted reader owner records and session lifecycle decisions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from .reader_diagnostics import Category, Stage, Unavailable, stage
from .storage import Conflict, canonical

__all__ = [
    "IDLE",
    "LIFETIME",
    "Access",
    "EndReason",
    "Grant",
    "LogoutScope",
    "NewSession",
    "ProviderTokens",
    "SessionBook",
    "SessionLimit",
    "SignIn",
]

IDLE = 7 * 86400
LIFETIME = 30 * 86400
SESSION_CAP = 100
LEASE_SECONDS = 10
WRITE_ATTEMPTS = 3
PROVIDER_TIMEOUT = 5
RENEWAL_POLL = (0.05, 0.1, 0.2, 0.4, 0.8)


class Access(Enum):
    PASSIVE = "passive"
    ACTIVE = "active"


class LogoutScope(Enum):
    DEVICE = "device"
    ALL = "all"


class EndReason(Enum):
    ABSENT = "absent"
    IDLE_EXPIRED = "idle_expired"
    LIFETIME_EXPIRED = "lifetime_expired"
    TOKEN_REJECTED = "token_rejected"
    RENEWAL_REFUSED = "renewal_refused"
    STALE_LEASE = "stale_lease"
    ENDED_DURING_RENEWAL = "ended_during_renewal"


@dataclass(frozen=True)
class ProviderTokens:
    access: str = field(repr=False)
    refresh: str | None = field(default=None, repr=False)

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> ProviderTokens:
        access, refresh = raw.get("access_token"), raw.get("refresh_token")
        if not isinstance(access, str) or not access:
            raise ValueError("invalid provider tokens")
        if refresh is not None and (not isinstance(refresh, str) or not refresh):
            raise ValueError("invalid provider tokens")
        return cls(access, refresh)


@dataclass(frozen=True)
class _Handle:
    subject: str
    key: str


@dataclass(frozen=True)
class Grant:
    subject: str
    csrf: str = field(repr=False)
    _handle: _Handle = field(repr=False, compare=False)


@dataclass(frozen=True)
class SignIn:
    reason: EndReason


@dataclass(frozen=True)
class NewSession:
    cookie: str = field(repr=False)


@dataclass(frozen=True)
class SessionLimit:
    pass


@dataclass(frozen=True)
class _Lease:
    refresh: str = field(repr=False)


class _Wait:
    pass


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _ended(entry, now):
    if now - min(entry["seen"], now) >= IDLE:
        return EndReason.IDLE_EXPIRED
    if now - entry["created"] >= LIFETIME:
        return EndReason.LIFETIME_EXPIRED
    return None


class SessionBook:
    def __init__(self, store, cipher, verifier, identity, clock: Callable[[], float]):
        self._store, self._cipher = store, cipher
        self._verifier, self._identity, self._clock = verifier, identity, clock

    async def _load(self, subject):
        with stage(Stage.SESSION_READ) as span:
            span.attempt()
            raw, version = await asyncio.to_thread(
                self._store.read_version, "reader/owners/" + _digest(subject)
            )
            owner = json.loads(self._cipher.decrypt(raw)) if raw else {"sessions": {}}
            for entry in owner["sessions"].values():
                if "renewing" not in entry:
                    entry.pop("lease", None)
            return owner, version

    async def _commit(self, subject, decide, at):
        """One bounded CAS loop. Decide again after definite conflict only.

        A final reread recognizes committed self-conflicts. Pending removals are
        retained until confirmation, so a committed-then-412 also revokes tokens.
        Ambiguous exceptions propagate without claiming the write succeeded.
        """
        proposed = self._clock()
        pending = set()
        for attempt in range(WRITE_ATTEMPTS + 1):
            owner, version = await self._load(subject)
            stored = {s.get("refresh") for s in owner["sessions"].values()}
            gone = pending - stored
            if gone:
                await self._revoke(gone)
                pending -= gone
            changed, outcome, removed = await decide(owner, proposed, self._clock())
            if not changed:
                return outcome
            with stage(
                Stage.RENEWAL_LEASE if isinstance(outcome, _Lease) else at
            ) as span:
                if attempt == WRITE_ATTEMPTS:
                    raise Unavailable(Category.SESSION_CHANGED)
                span.attempt()
                try:
                    await asyncio.to_thread(
                        self._store.put_bytes,
                        "reader/owners/" + _digest(subject),
                        self._cipher.encrypt(canonical(owner)),
                        expected=version,
                    )
                except Conflict:
                    span.conflict()
                    pending.update(removed)
                    continue
            # Do not revoke a value still referenced by a different device.
            stored = {s.get("refresh") for s in owner["sessions"].values()}
            await self._revoke((pending | set(removed)) - stored)
            return outcome
        raise AssertionError("unreachable")

    async def _revoke(self, tokens):
        async def attempt(token):
            if not token:
                return
            try:
                with stage(Stage.PROVIDER_REVOKE) as span:
                    span.attempt()
                    async with asyncio.timeout(PROVIDER_TIMEOUT):
                        await self._identity.revoke(token)
            except Exception:  # noqa: BLE001 - confirmed removal is independent of provider availability
                return

        await asyncio.gather(*(attempt(token) for token in tokens))

    async def begin(
        self, verified, tokens: ProviderTokens
    ) -> NewSession | SessionLimit:
        cookie = secrets.token_urlsafe(32)
        key = _digest(cookie)
        now = self._clock()
        entry = {
            "access": tokens.access,
            "refresh": tokens.refresh,
            "created": now,
            "seen": now,
            "csrf": secrets.token_urlsafe(32),
        }

        async def decide(owner, proposed, current):
            sessions = owner["sessions"]
            if key in sessions:
                return False, NewSession(cookie), ()
            live = {k: s for k, s in sessions.items() if not _ended(s, current)}
            if len(live) >= SESSION_CAP:
                return False, SessionLimit(), ()
            live[key] = entry
            owner["sessions"] = live
            return True, NewSession(cookie), ()

        return await self._commit(verified.subject, decide, Stage.SESSION_CREATE)

    async def end(self, grant: Grant, scope: LogoutScope) -> None:
        async def decide(owner, proposed, current):
            sessions = owner["sessions"]
            if scope is LogoutScope.ALL:
                removed = list(sessions.values())
                sessions.clear()
            else:
                entry = sessions.pop(grant._handle.key, None)
                removed = [entry] if entry else []
            return bool(removed), None, tuple(s.get("refresh") for s in removed)

        await self._commit(grant._handle.subject, decide, Stage.SESSION_END)

    async def authorize(self, cookie: str | None, access: Access) -> Grant | SignIn:
        if not isinstance(cookie, str) or len(cookie) != 43:
            return SignIn(EndReason.ABSENT)
        key = _digest(cookie)
        for subject in self._verifier.subjects:
            result = await self._authorize(subject, key, access)
            if result is not None:
                return result
        return SignIn(EndReason.ABSENT)

    async def _authorize(self, subject, key, access):
        nonce = secrets.token_urlsafe(32)
        verified = {}

        async def decide(owner, proposed, current):
            sessions = owner["sessions"]
            entry = sessions.get(key)
            if entry is None:
                return False, None, ()

            def remove(reason):
                del sessions[key]
                return True, SignIn(reason), (entry.get("refresh"),)

            if reason := _ended(entry, current):
                return remove(reason)
            if "renewing" in entry:
                if current - entry["renewing"] >= LEASE_SECONDS:
                    return remove(EndReason.STALE_LEASE)
                if entry.get("lease") == nonce:
                    return False, _Lease(entry["refresh"]), ()
                return False, _Wait(), ()
            raw = entry["access"]
            if raw not in verified:
                with stage(Stage.TOKEN_VERIFY) as span:
                    span.attempt()
                    token = await self._verifier.verify_token(raw)
                    expired = (
                        None
                        if token
                        else await self._verifier.verify_token(raw, allow_expired=True)
                    )
                valid = token or expired
                verified[raw] = (
                    bool(
                        valid
                        and valid.subject == subject
                        and "library:read" in valid.scopes
                    ),
                    bool(token),
                )
            allowed, live = verified[raw]
            if not allowed or (not live and not entry.get("refresh")):
                return remove(EndReason.TOKEN_REJECTED)
            if not live:
                entry.update(renewing=current, lease=nonce)
                return True, _Lease(entry["refresh"]), ()
            grant = Grant(subject, entry["csrf"], _Handle(subject, key))
            if access is Access.ACTIVE and proposed > entry["seen"]:
                entry["seen"] = proposed
                return True, grant, ()
            return False, grant, ()

        outcome = await self._commit(subject, decide, Stage.SESSION_WRITE)
        if isinstance(outcome, _Wait):
            with stage(Stage.RENEWAL_WAIT) as span:
                poll = 0
                while isinstance(outcome, _Wait):
                    span.attempt()
                    await asyncio.sleep(RENEWAL_POLL[min(poll, len(RENEWAL_POLL) - 1)])
                    poll += 1
                    outcome = await self._commit(subject, decide, Stage.SESSION_WRITE)
        if isinstance(outcome, _Lease):
            return await self._renew(subject, key, nonce, outcome.refresh, access)
        return outcome

    async def _renew(self, subject, key, nonce, refresh, access):
        tokens = None
        try:
            with stage(Stage.PROVIDER_RENEW) as span:
                span.attempt()
                async with asyncio.timeout(PROVIDER_TIMEOUT):
                    tokens = ProviderTokens.parse(await self._identity.renew(refresh))
            with stage(Stage.TOKEN_VERIFY) as span:
                span.attempt()
                token = await self._verifier.verify_token(tokens.access)
                if (
                    not token
                    or token.subject != subject
                    or "library:read" not in token.scopes
                ):
                    raise ValueError("authorization lost")
        except Exception:  # noqa: BLE001 - preserve redaction and original outcome

            async def drop(owner, proposed, current):
                entry = owner["sessions"].get(key)
                if entry is None or entry.get("lease") != nonce:
                    return False, SignIn(EndReason.ENDED_DURING_RENEWAL), ()
                del owner["sessions"][key]
                return True, SignIn(EndReason.RENEWAL_REFUSED), (entry.get("refresh"),)

            result = await self._commit(subject, drop, Stage.RENEWAL_SETTLE)
            if tokens:
                await self._revoke({tokens.refresh})
            return result

        async def settle(owner, proposed, current):
            entry = owner["sessions"].get(key)
            if entry is None:
                return False, SignIn(EndReason.ENDED_DURING_RENEWAL), ()
            grant = Grant(subject, entry["csrf"], _Handle(subject, key))
            # Recognize a committed settlement BEFORE comparing lease ownership.
            if "renewing" not in entry and entry["access"] == tokens.access:
                return False, grant, ()
            if "renewing" not in entry or entry.get("lease") != nonce:
                return False, SignIn(EndReason.ENDED_DURING_RENEWAL), ()
            entry.update(
                access=tokens.access, refresh=tokens.refresh or entry["refresh"]
            )
            entry.pop("renewing", None)
            entry.pop("lease", None)
            if access is Access.ACTIVE:
                entry["seen"] = max(entry["seen"], proposed)
            return True, grant, ()

        try:
            result = await self._commit(subject, settle, Stage.RENEWAL_SETTLE)
        except Exception:
            # A failed write may have committed. Revoke only when a fresh read
            # confirms that the new token is not stored by any device.
            try:
                owner, _ = await self._load(subject)
                if tokens.refresh not in {
                    s.get("refresh") for s in owner["sessions"].values()
                }:
                    await self._revoke({tokens.refresh})
            except Exception:  # noqa: BLE001, S110 - preserve redaction and original outcome
                pass
            raise
        if isinstance(result, SignIn):
            await self._revoke({tokens.refresh})
        return result
