"""Local PostgreSQL trial of the reader lifecycle, behind the existing interface.

No environment selector or automatic migration: the hosted service keeps R2.
Pool work runs in threads; no JWT or provider await holds a SQL transaction.
"""

from __future__ import annotations

import asyncio
import contextvars
import hmac
import secrets

import httpx
from psycopg import IsolationLevel
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .reader_diagnostics import Category, Stage, Unavailable, stage
from .reader_sessions import (
    IDLE,
    LEASE_SECONDS,
    LIFETIME,
    PROVIDER_TIMEOUT,
    RENEWAL_POLL,
    SESSION_CAP,
    Access,
    EndReason,
    Grant,
    LogoutScope,
    NewSession,
    ProviderTokens,
    SessionLimit,
    SignIn,
    _digest,
    _ended,
    _Handle,
)


class _Retry:
    pass


class _Wait:
    pass


class _Fenced:
    pass


MAINTENANCE_SECONDS = 60


class PostgresSessionBook:
    """One durable row per device; exact touches, current primary admission.

    ``clock`` is a synthetic-test seam. Otherwise use primary clock_timestamp().
    Encryption key rotation starts a fresh epoch; it never admits old rows.
    """

    def __init__(
        self, conninfo, cipher, verifier, identity, encryption_key, *, clock=None
    ):
        self._cipher, self._verifier, self._identity = cipher, verifier, identity
        self._clock = clock
        self._cleanup_tasks = {}
        self._cleanup_pending = set()
        self._closing = False
        self._renewals = set()
        self._maintenance_task = None
        self._fingerprint_key = hmac.digest(
            encryption_key, b"reader-session-token-identity-v1", "sha256"
        )
        self._epoch = hmac.digest(
            encryption_key, b"reader-session-authority-v1", "sha256"
        ).hex()
        self._pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=8,
            timeout=2,
            open=True,
            configure=self._configure,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "connect_timeout": 2,
                "options": "-c statement_timeout=3000 -c lock_timeout=2000 -c synchronous_commit=on -c search_path=pg_catalog,public",
            },
        )

    @staticmethod
    def _configure(conn):
        conn.isolation_level = IsolationLevel.READ_COMMITTED
        state = conn.execute(
            "SELECT NOT pg_is_in_recovery() AS primary, current_setting('transaction_read_only') AS readonly"
        ).fetchone()
        if not state["primary"] or state["readonly"] != "off":
            raise ValueError("Session authority requires a writable primary")

    async def close(self):
        if self._maintenance_task:
            self._maintenance_task.cancel()
            await asyncio.gather(self._maintenance_task, return_exceptions=True)
            self._maintenance_task = None
        await self._drain_renewals()
        self._closing = True
        try:
            await self._drain_cleanup()
        finally:
            self._cleanup_pending.clear()
            await asyncio.to_thread(self._pool.close)

    async def start(self):
        await asyncio.to_thread(self._pool.wait, 3)
        if self._maintenance_task is None:

            async def maintain():
                while True:
                    await asyncio.sleep(MAINTENANCE_SECONDS)
                    try:
                        await self.maintain_once()
                    except Exception:  # noqa: BLE001, S112 - durable work remains pending for the next sweep
                        continue

            self._maintenance_task = asyncio.create_task(
                maintain(), context=contextvars.Context()
            )

    async def _drain_renewals(self):
        await asyncio.gather(*list(self._renewals), return_exceptions=True)

    async def maintain_once(self):
        def candidates(conn):
            now = self._time(conn)
            return conn.execute(
                "SELECT subject FROM reader_device_sessions WHERE epoch=%s "
                "AND (ended OR %s-seen >= %s OR %s-created >= %s) "
                "UNION SELECT subject FROM reader_session_retirements WHERE epoch=%s "
                "AND ((completed AND octet_length(token)>0) OR (NOT completed AND retry_at<=%s)) ORDER BY subject LIMIT 100",
                (self._epoch, now, IDLE, now, LIFETIME, self._epoch, now),
            ).fetchall()

        for candidate in await self._run(
            Stage.SESSION_READ, candidates, transaction=False
        ):
            subject = candidate["subject"]

            def sweep(conn, subject=subject):
                conn.execute(
                    "SELECT generation FROM reader_session_owners WHERE epoch=%s AND subject=%s FOR UPDATE",
                    (self._epoch, subject),
                )
                now = self._time(conn)
                entries = conn.execute(
                    "SELECT * FROM reader_device_sessions WHERE epoch=%s AND subject=%s AND NOT ended",
                    (self._epoch, subject),
                ).fetchall()
                for entry in entries:
                    if _ended(entry, now):
                        self._end_row(conn, entry)
                conn.execute(
                    "DELETE FROM reader_device_sessions WHERE epoch=%s AND subject=%s AND ended",
                    (self._epoch, subject),
                )
                conn.execute(
                    "UPDATE reader_session_retirements SET token=''::bytea WHERE epoch=%s AND subject=%s AND completed AND octet_length(token)>0",
                    (self._epoch, subject),
                )

            await self._run(Stage.SESSION_END, sweep)
            self._schedule_cleanup(subject)

    async def _drain_cleanup(self):
        await asyncio.gather(
            *list(self._cleanup_tasks.values()), return_exceptions=True
        )

    def _schedule_cleanup(self, subject):
        if self._closing:
            return
        self._cleanup_pending.add(subject)
        if subject in self._cleanup_tasks:
            return

        async def run():
            attempted = set()
            try:
                while subject in self._cleanup_pending:
                    self._cleanup_pending.remove(subject)
                    more = await self._cleanup(subject, attempted)
                    if self._closing:
                        break
                    if more:
                        self._cleanup_pending.add(subject)
            finally:
                self._cleanup_pending.discard(subject)
                self._cleanup_tasks.pop(subject, None)

        # Background work must not mutate the completed HTTP diagnostic trace.
        self._cleanup_tasks[subject] = asyncio.create_task(
            run(), context=contextvars.Context()
        )

    async def _run(self, at, operation, *, transaction=True):
        def run():
            with self._pool.connection() as conn:
                if transaction:
                    with conn.transaction():
                        return operation(conn)
                return operation(conn)

        with stage(at) as span:
            span.attempt()
            return await asyncio.to_thread(run)

    def _time(self, conn):
        if self._clock:
            return self._clock()
        return float(
            conn.execute(
                "SELECT extract(epoch FROM clock_timestamp()) AS now"
            ).fetchone()["now"]
        )

    def _identity_of(self, refresh):
        if refresh is None:
            return None
        return hmac.digest(
            self._fingerprint_key,
            (self._verifier.issuer + "\0" + refresh).encode(),
            "sha256",
        ).hex()

    def _encrypt(self, token):
        return self._cipher.encrypt(token.encode()) if token else None

    def _decrypt(self, value):
        return self._cipher.decrypt(value).decode() if value else None

    async def _load(self, key):
        def read(conn):
            row = conn.execute(
                "SELECT s.*, o.generation AS owner_generation, "
                "extract(epoch FROM clock_timestamp())::float8 AS now, NOT pg_is_in_recovery() AS primary "
                "FROM reader_device_sessions s JOIN reader_session_owners o "
                "USING (epoch, subject) WHERE s.epoch=%s AND s.key=%s",
                (self._epoch, key),
            ).fetchone()
            if row and not row["primary"]:
                raise Unavailable(Category.SESSION_STORAGE)
            if row and self._clock:
                row["now"] = self._clock()
            return row

        return await self._run(Stage.SESSION_READ, read, transaction=False)

    def _lock(self, conn, subject, key, *, exclusive=False):
        owner = conn.execute(
            "SELECT generation FROM reader_session_owners WHERE epoch=%s AND subject=%s "
            + ("FOR UPDATE" if exclusive else "FOR SHARE"),
            (self._epoch, subject),
        ).fetchone()
        if owner is None:
            return None
        row = conn.execute(
            "SELECT * FROM reader_device_sessions WHERE epoch=%s AND key=%s FOR UPDATE",
            (self._epoch, key),
        ).fetchone()
        if row:
            row.update(owner_generation=owner["generation"], now=self._time(conn))
        return row

    @staticmethod
    def _invalid(row):
        if not row or row["ended"] or row["generation"] != row["owner_generation"]:
            return EndReason.ABSENT
        return _ended(row, row["now"])

    @staticmethod
    def _grant(row):
        return Grant(row["subject"], row["csrf"], _Handle(row["subject"], row["key"]))

    def _retire(self, conn, subject, refresh_id, encrypted):
        """Caller holds owner FOR UPDATE, serializing begin and last-reference removal."""
        if not refresh_id:
            return
        conn.execute(
            "INSERT INTO reader_session_retirements(epoch,subject,refresh_id,token,completed) "
            "SELECT %s,%s,%s,%s,EXISTS(SELECT 1 FROM reader_session_exchanges "
            "WHERE epoch=%s AND subject=%s AND refresh_id=%s AND settled) WHERE NOT EXISTS "
            "(SELECT 1 FROM reader_device_sessions WHERE epoch=%s AND subject=%s "
            "AND refresh_id=%s AND NOT ended) ON CONFLICT DO NOTHING",
            (
                self._epoch,
                subject,
                refresh_id,
                encrypted,
                self._epoch,
                subject,
                refresh_id,
                self._epoch,
                subject,
                refresh_id,
            ),
        )

    def _end_row(self, conn, row):
        if row["lease"]:
            conn.execute(
                "UPDATE reader_session_exchanges SET failed=true WHERE epoch=%s AND subject=%s "
                "AND refresh_id=%s AND nonce=%s AND NOT settled",
                (self._epoch, row["subject"], row["refresh_id"], row["lease"]),
            )
        conn.execute(
            "UPDATE reader_device_sessions SET ended=true,lease=NULL,renewing=NULL "
            "WHERE epoch=%s AND key=%s",
            (self._epoch, row["key"]),
        )
        self._retire(conn, row["subject"], row["refresh_id"], row["refresh"])

    async def begin(self, verified, tokens: ProviderTokens):
        cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        subject, key = verified.subject, _digest(cookie)
        refresh_id = self._identity_of(tokens.refresh)
        encrypted_access, encrypted_refresh = (
            self._encrypt(tokens.access),
            self._encrypt(tokens.refresh),
        )

        def begin(conn):
            conn.execute(
                "INSERT INTO reader_session_owners(epoch,subject) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (self._epoch, subject),
            )
            owner = conn.execute(
                "SELECT generation FROM reader_session_owners WHERE epoch=%s AND subject=%s FOR UPDATE",
                (self._epoch, subject),
            ).fetchone()
            now = self._time(conn)
            rows = conn.execute(
                "SELECT * FROM reader_device_sessions WHERE epoch=%s AND subject=%s AND NOT ended",
                (self._epoch, subject),
            ).fetchall()
            live = 0
            for row in rows:
                if row["generation"] != owner["generation"] or _ended(row, now):
                    self._end_row(conn, row)
                else:
                    live += 1
            if live >= SESSION_CAP:
                return SessionLimit()
            if (
                refresh_id
                and conn.execute(
                    "SELECT 1 FROM reader_session_retirements WHERE epoch=%s AND subject=%s AND refresh_id=%s "
                    "UNION ALL SELECT 1 FROM reader_session_exchanges WHERE epoch=%s AND subject=%s AND refresh_id=%s",
                    (
                        self._epoch,
                        subject,
                        refresh_id,
                        self._epoch,
                        subject,
                        refresh_id,
                    ),
                ).fetchone()
            ):
                raise ValueError("retired credential cannot create a session")
            conn.execute(
                "INSERT INTO reader_device_sessions "
                "(epoch,key,subject,generation,created,seen,csrf,access,refresh,refresh_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self._epoch,
                    key,
                    subject,
                    owner["generation"],
                    now,
                    now,
                    csrf,
                    encrypted_access,
                    encrypted_refresh,
                    refresh_id,
                ),
            )
            return NewSession(cookie)

        result = await self._run(Stage.SESSION_CREATE, begin)
        self._schedule_cleanup(subject)
        return result

    async def end(self, grant: Grant, scope: LogoutScope):
        subject, key = grant._handle.subject, grant._handle.key

        def end(conn):
            row = self._lock(conn, subject, key, exclusive=True)
            if scope is LogoutScope.ALL:
                conn.execute(
                    "UPDATE reader_session_exchanges SET failed=true WHERE epoch=%s AND subject=%s AND NOT settled",
                    (self._epoch, subject),
                )
                conn.execute(
                    "UPDATE reader_session_owners SET generation=generation+1 WHERE epoch=%s AND subject=%s",
                    (self._epoch, subject),
                )
                removed = conn.execute(
                    "UPDATE reader_device_sessions SET ended=true,lease=NULL,renewing=NULL "
                    "WHERE epoch=%s AND subject=%s AND NOT ended RETURNING *",
                    (self._epoch, subject),
                ).fetchall()
                for entry in removed:
                    self._retire(conn, subject, entry["refresh_id"], entry["refresh"])
            elif row and not row["ended"]:
                self._end_row(conn, row)

        await self._run(Stage.SESSION_END, end)
        self._schedule_cleanup(subject)

    async def _drop(self, original, reason, *, nonce=None):
        def drop(conn):
            row = self._lock(conn, original["subject"], original["key"], exclusive=True)
            if not row or row["ended"]:
                return SignIn(EndReason.ENDED_DURING_RENEWAL if nonce else reason)
            if row["credential_version"] != original["credential_version"] or (
                nonce and row["lease"] != nonce
            ):
                return _Retry()
            if reason in {
                EndReason.IDLE_EXPIRED,
                EndReason.LIFETIME_EXPIRED,
            } and not self._invalid(row):
                return _Retry()
            self._end_row(conn, row)
            return SignIn(reason)

        result = await self._run(Stage.SESSION_END, drop)
        self._schedule_cleanup(original["subject"])
        return result

    async def authorize(self, cookie, access):
        if not isinstance(cookie, str) or len(cookie) != 43:
            return SignIn(EndReason.ABSENT)
        key, nonce = _digest(cookie), secrets.token_urlsafe(32)
        verified = {}
        poll = 0
        while True:
            row = await self._load(key)
            if not row or row["subject"] not in self._verifier.subjects:
                return SignIn(EndReason.ABSENT)
            if row["ended"] or row["generation"] != row["owner_generation"]:
                return SignIn(EndReason.ABSENT)
            if reason := self._invalid(row):
                result = await self._drop(row, reason)
                if isinstance(result, _Retry):
                    continue
                return result
            if row["lease"]:
                if row["now"] - row["renewing"] >= LEASE_SECONDS:
                    result = await self._drop(
                        row, EndReason.STALE_LEASE, nonce=row["lease"]
                    )
                    if isinstance(result, _Retry):
                        continue
                    return result
                with stage(Stage.RENEWAL_WAIT) as span:
                    span.attempt()
                    await asyncio.sleep(RENEWAL_POLL[min(poll, len(RENEWAL_POLL) - 1)])
                poll += 1
                continue
            raw = self._decrypt(row["access"])
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
                            and valid.subject == row["subject"]
                            and "library:read" in valid.scopes
                        ),
                        bool(token),
                    )
            allowed, live = verified[raw]
            if not allowed or (not live and not row["refresh"]):
                result = await self._drop(row, EndReason.TOKEN_REJECTED)
                if isinstance(result, _Retry):
                    continue
                return result
            if live and access is Access.PASSIVE:
                return self._grant(row)
            result = await self._admit(row, live, nonce, access)
            if isinstance(result, _Fenced):
                result = await self._drop(row, EndReason.RENEWAL_UNCONFIRMED)
            if isinstance(result, _Wait):
                with stage(Stage.RENEWAL_WAIT) as span:
                    span.attempt()
                    await asyncio.sleep(RENEWAL_POLL[min(poll, len(RENEWAL_POLL) - 1)])
                poll += 1
                continue
            if isinstance(result, _Retry):
                continue
            if result is None:
                task = asyncio.create_task(self._renew(row, nonce))
                self._renewals.add(task)

                def settled(done):
                    self._renewals.discard(done)
                    if not done.cancelled():
                        done.exception()

                task.add_done_callback(settled)
                return await asyncio.shield(task)
            return result

    async def _admit(self, original, live, nonce, access):
        def admit(conn):
            row = self._lock(
                conn, original["subject"], original["key"], exclusive=not live
            )
            if reason := self._invalid(row):
                return SignIn(reason)
            if row["credential_version"] != original["credential_version"]:
                return _Retry()
            if row["lease"]:
                return _Wait()
            if not live:
                existing = conn.execute(
                    "SELECT * FROM reader_session_exchanges WHERE epoch=%s AND subject=%s AND refresh_id=%s",
                    (self._epoch, row["subject"], row["refresh_id"]),
                ).fetchone()
                if existing:
                    if (
                        existing["settled"]
                        or existing["failed"]
                        or row["now"] - existing["started"] >= LEASE_SECONDS
                    ):
                        return _Fenced()
                    return _Wait()
                conn.execute(
                    "INSERT INTO reader_session_exchanges(epoch,subject,refresh_id,nonce,started) VALUES(%s,%s,%s,%s,%s)",
                    (self._epoch, row["subject"], row["refresh_id"], nonce, row["now"]),
                )
                conn.execute(
                    "UPDATE reader_device_sessions SET lease=%s,renewing=%s,admission=%s "
                    "WHERE epoch=%s AND key=%s",
                    (
                        nonce,
                        row["now"],
                        row["now"] if access is Access.ACTIVE else None,
                        self._epoch,
                        row["key"],
                    ),
                )
                return None
            if row["now"] > row["seen"]:
                conn.execute(
                    "UPDATE reader_device_sessions SET seen=%s WHERE epoch=%s AND key=%s",
                    (row["now"], self._epoch, row["key"]),
                )
            return self._grant(row)

        return await self._run(
            Stage.SESSION_WRITE if live else Stage.RENEWAL_LEASE, admit
        )

    async def _renew(self, original, nonce):
        tokens = None
        try:
            with stage(Stage.PROVIDER_RENEW) as span:
                span.attempt()
                async with asyncio.timeout(PROVIDER_TIMEOUT):
                    tokens = ProviderTokens.parse(
                        await self._identity.renew(self._decrypt(original["refresh"]))
                    )
            with stage(Stage.TOKEN_VERIFY) as span:
                span.attempt()
                token = await self._verifier.verify_token(tokens.access)
                if (
                    not token
                    or token.subject != original["subject"]
                    or "library:read" not in token.scopes
                ):
                    raise ValueError("authorization lost")
        except Exception as error:  # noqa: BLE001 - provider errors stay inside the session boundary
            reason = (
                EndReason.RENEWAL_UNCONFIRMED
                if isinstance(error, (TimeoutError, OSError, httpx.TransportError))
                else EndReason.RENEWAL_REFUSED
            )
            result = await self._drop(original, reason, nonce=nonce)
            if tokens and tokens.refresh:
                await self._discard(original, tokens.refresh)
            return (
                SignIn(EndReason.ENDED_DURING_RENEWAL)
                if isinstance(result, _Retry)
                else result
            )

        refresh = tokens.refresh or self._decrypt(original["refresh"])
        encrypted_access, encrypted_refresh = (
            self._encrypt(tokens.access),
            self._encrypt(refresh),
        )
        refresh_id = self._identity_of(refresh)

        def settle(conn):
            row = self._lock(conn, original["subject"], original["key"], exclusive=True)
            if row and row["settled"] == nonce and not self._invalid(row):
                return self._grant(row)
            if (
                not row
                or row["lease"] != nonce
                or row["credential_version"] != original["credential_version"]
            ):
                self._retire(conn, original["subject"], refresh_id, encrypted_refresh)
                return SignIn(EndReason.ENDED_DURING_RENEWAL)
            if reason := self._invalid(row):
                self._end_row(conn, row)
                self._retire(conn, row["subject"], refresh_id, encrypted_refresh)
                return SignIn(reason)
            if row["now"] - row["renewing"] >= LEASE_SECONDS:
                self._end_row(conn, row)
                self._retire(conn, row["subject"], refresh_id, encrypted_refresh)
                return SignIn(EndReason.STALE_LEASE)
            if conn.execute(
                "SELECT 1 FROM reader_session_retirements WHERE epoch=%s AND subject=%s AND refresh_id=%s",
                (self._epoch, row["subject"], refresh_id),
            ).fetchone():
                self._end_row(conn, row)
                return SignIn(EndReason.TOKEN_REJECTED)
            exchange = conn.execute(
                "SELECT * FROM reader_session_exchanges WHERE epoch=%s AND subject=%s AND refresh_id=%s",
                (self._epoch, row["subject"], row["refresh_id"]),
            ).fetchone()
            if not exchange or exchange["nonce"] != nonce or exchange["settled"]:
                self._end_row(conn, row)
                self._retire(conn, row["subject"], refresh_id, encrypted_refresh)
                return SignIn(EndReason.ENDED_DURING_RENEWAL)
            # All references share one rotating credential. Keep their creation,
            # CSRF and activity independent while replacing only credentials.
            conn.execute(
                "UPDATE reader_device_sessions SET access=%s,refresh=%s,refresh_id=%s,"
                "credential_version=credential_version+1 "
                "WHERE epoch=%s AND subject=%s AND refresh_id=%s AND NOT ended AND key<>%s",
                (
                    encrypted_access,
                    encrypted_refresh,
                    refresh_id,
                    self._epoch,
                    row["subject"],
                    row["refresh_id"],
                    row["key"],
                ),
            )
            if refresh_id == row["refresh_id"]:
                conn.execute(
                    "DELETE FROM reader_session_exchanges WHERE epoch=%s AND subject=%s AND refresh_id=%s",
                    (self._epoch, row["subject"], row["refresh_id"]),
                )
            else:
                conn.execute(
                    "UPDATE reader_session_exchanges SET settled=true WHERE epoch=%s AND subject=%s AND refresh_id=%s",
                    (self._epoch, row["subject"], row["refresh_id"]),
                )
            conn.execute(
                "UPDATE reader_device_sessions SET access=%s,refresh=%s,refresh_id=%s,"
                "credential_version=credential_version+1,lease=NULL,renewing=NULL,settled=%s,"
                "seen=greatest(seen,coalesce(admission,seen)),admission=NULL WHERE epoch=%s AND key=%s",
                (
                    encrypted_access,
                    encrypted_refresh,
                    refresh_id,
                    nonce,
                    self._epoch,
                    row["key"],
                ),
            )
            return self._grant(row)

        try:
            result = await self._run(Stage.RENEWAL_SETTLE, settle)
        except Exception:
            confirmed = await self._load(original["key"])
            if (
                confirmed
                and confirmed["settled"] == nonce
                and not self._invalid(confirmed)
            ):
                return self._grant(confirmed)
            await self._discard(original, refresh)
            raise
        self._schedule_cleanup(original["subject"])
        return result

    async def _discard(self, original, refresh):
        def discard(conn):
            self._lock(conn, original["subject"], original["key"], exclusive=True)
            self._retire(
                conn,
                original["subject"],
                self._identity_of(refresh),
                self._encrypt(refresh),
            )

        await self._run(Stage.RENEWAL_SETTLE, discard)
        self._schedule_cleanup(original["subject"])

    async def _cleanup(self, subject, attempted):
        """Durable retry work; a failure cannot undo confirmed local logout."""
        nonce = secrets.token_urlsafe(32)

        def claim(conn):
            conn.execute(
                "SELECT generation FROM reader_session_owners WHERE epoch=%s AND subject=%s FOR UPDATE",
                (self._epoch, subject),
            ).fetchone()
            now = self._time(conn)
            return conn.execute(
                "UPDATE reader_session_retirements SET claim=%s,retry_at=%s "
                "WHERE epoch=%s AND subject=%s AND refresh_id IN "
                "(SELECT refresh_id FROM reader_session_retirements WHERE epoch=%s AND subject=%s "
                "AND NOT completed AND retry_at<=%s AND refresh_id<>ALL(%s) "
                "ORDER BY refresh_id LIMIT 8) RETURNING *",
                (
                    nonce,
                    now + LEASE_SECONDS,
                    self._epoch,
                    subject,
                    self._epoch,
                    subject,
                    now,
                    list(attempted),
                ),
            ).fetchall()

        try:
            rows = await self._run(Stage.SESSION_END, claim)
            attempted.update(row["refresh_id"] for row in rows)

            async def revoke(row):
                try:
                    with stage(Stage.PROVIDER_REVOKE) as span:
                        span.attempt()
                        async with asyncio.timeout(PROVIDER_TIMEOUT):
                            await self._identity.revoke(self._decrypt(row["token"]))
                except Exception:  # noqa: BLE001 - retained for a subsequent cleanup attempt
                    return

                def completed(conn, row=row):
                    conn.execute(
                        "UPDATE reader_session_retirements SET completed=true WHERE epoch=%s "
                        "AND subject=%s AND refresh_id=%s AND claim=%s",
                        (self._epoch, subject, row["refresh_id"], nonce),
                    )

                await self._run(Stage.SESSION_END, completed)

            await asyncio.gather(*(revoke(row) for row in rows), return_exceptions=True)
            return len(rows) == 8
        except Exception:  # noqa: BLE001 - cleanup never changes the committed admission decision
            return
