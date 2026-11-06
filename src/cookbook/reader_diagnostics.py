"""Bounded, closed request diagnostics; no payloads or exception text."""

import contextvars
import json
import os
import re
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "FAILURE_HEADER",
    "REQUEST_HEADER",
    "Category",
    "Failure",
    "Stage",
    "Trace",
    "Unavailable",
    "request",
    "stage",
]

REQUEST_HEADER = "X-Reader-Request"
FAILURE_HEADER = "X-Reader-Failure"


class Category(Enum):
    """Why a request did not get its normal answer. One value per 503 (I11)."""

    SESSION_CHANGED = (
        "session_changed"  # owner record CAS budget exhausted by competing changes
    )
    RENEWAL_PENDING = (
        "renewal_pending"  # deadline hit while waiting on another request's renewal
    )
    DEADLINE = "deadline"  # request deadline hit anywhere else (the stage tells where)
    SESSION_STORAGE = (
        "session_storage"  # owner or transaction record: store I/O or decrypt failure
    )
    IDENTITY = "identity"  # provider exchange, renew, revoke, or JWKS/verify raised
    PERSONAL_STATE = "personal_state"  # personal metadata (I12: diagnosed, never touched by the session path)
    CONTENT = "content"  # text or original delivery
    LIBRARY = "library"  # catalog, search, or publication resolve
    REPORTS = "reports"  # owner report intake
    INTERNAL = "internal"  # rendering or an unexpected error outside any narrower stage


class Stage(Enum):
    """Where time went and where a failure happened. Each stage names its own fault category.

    Adding a stage means choosing its fault category in the same line, so there is no
    separate stage-to-category map to keep in sync.
    """

    def __init__(self, label: str, fault: Category) -> None:
        self.label = label
        self.fault = fault

    REQUEST = (
        "request",
        Category.INTERNAL,
    )  # root: always open, so every failure has a stage
    # session lifecycle (reader_sessions.SessionBook)
    SESSION_READ = ("session_read", Category.SESSION_STORAGE)
    SESSION_WRITE = ("session_write", Category.SESSION_STORAGE)
    RENEWAL_LEASE = ("renewal_lease", Category.SESSION_STORAGE)
    RENEWAL_SETTLE = ("renewal_settle", Category.SESSION_STORAGE)
    RENEWAL_WAIT = ("renewal_wait", Category.SESSION_STORAGE)
    SESSION_CREATE = ("session_create", Category.SESSION_STORAGE)
    SESSION_END = ("session_end", Category.SESSION_STORAGE)
    # login transaction (reader.py)
    LOGIN_START = ("login_start", Category.SESSION_STORAGE)
    CALLBACK_TRANSACTION = ("callback_transaction", Category.SESSION_STORAGE)
    # identity provider and token verification
    TOKEN_VERIFY = ("token_verify", Category.IDENTITY)
    PROVIDER_RENEW = ("provider_renew", Category.IDENTITY)
    PROVIDER_REVOKE = ("provider_revoke", Category.IDENTITY)
    PROVIDER_EXCHANGE = ("provider_exchange", Category.IDENTITY)
    # route work (instrumented at call sites)
    PAGE_RENDER = ("page_render", Category.INTERNAL)
    LIBRARY_SEARCH = ("library_search", Category.LIBRARY)
    LIBRARY_RESOLVE = ("library_resolve", Category.LIBRARY)
    PERSONAL_STATE = ("personal_state", Category.PERSONAL_STATE)
    CONTENT_DELIVER = ("content_deliver", Category.CONTENT)
    ORIGINAL_DELIVER = ("original_deliver", Category.CONTENT)
    ORIGINAL_SOURCE = ("original_source", Category.CONTENT)
    ORIGINAL_CACHE = ("original_cache", Category.CONTENT)
    ORIGINAL_RENDER = ("original_render", Category.CONTENT)
    ORIGINAL_ENCODE = ("original_encode", Category.CONTENT)
    ORIGINAL_METADATA = ("original_metadata", Category.CONTENT)
    ORIGINAL_VALIDATE = ("original_validate", Category.CONTENT)
    ORIGINAL_RESPONSE = ("original_response", Category.CONTENT)
    RASTER_HIT = ("raster_hit", Category.CONTENT)
    RASTER_MISS = ("raster_miss", Category.CONTENT)
    REPORT_INTAKE = ("report_intake", Category.REPORTS)


class Unavailable(Exception):
    def __init__(self, category: Category):
        super().__init__(category.value)
        self.category = category


@dataclass(frozen=True)
class Failure:
    category: Category
    stage: Stage
    attempts: int
    request: str

    def header(self):
        return (
            f"{self.category.value}; stage={self.stage.label}; attempts={self.attempts}"
        )

    def reference(self):
        return f"Reference {self.category.value} · {self.stage.label} · {self.request}"


class Span:
    def __init__(self, values):
        self.values = values

    def attempt(self):
        self.values["n"] += 1

    def conflict(self):
        self.values["conflicts"] += 1


class Trace:
    def __init__(self, route, method):
        self.id = secrets.token_hex(8)
        self.route = route
        self.method = method if method in {"GET", "HEAD", "POST"} else "OTHER"
        self.started = time.monotonic()
        self.stages = {}
        self.failed = None
        self.failed_error = None
        self.waiting = False
        self.stack = []
        self.last = Stage.REQUEST
        self.failure = None
        self.reason = None

    def fail(self, error, *, deadline_expired):
        which = (
            self.failed
            if self.failed_error is error or deadline_expired and self.failed
            else self.last
        )
        category = (
            error.category
            if isinstance(error, Unavailable)
            else Category.RENEWAL_PENDING
            if deadline_expired and self.waiting
            else Category.DEADLINE
            if deadline_expired
            else which.fault
        )
        self.failure = Failure(
            category, which, self.stages.get(which.label, {}).get("n", 0), self.id
        )
        return self.failure

    def signed_out(self, reason):
        self.reason = reason.value

    def finish(self, response):
        response.headers[REQUEST_HEADER] = self.id
        if response.status_code == 503:
            if self.failure is None:
                self.fail(RuntimeError(), deadline_expired=False)
            response.headers[FAILURE_HEADER] = self.failure.header()
        revision = os.environ.get("FLY_IMAGE_REF", "")
        revision = (
            revision if re.fullmatch(r"(?:sha256:)?[0-9a-f]{40,64}", revision) else None
        )
        print(
            json.dumps(
                {
                    "event": "reader_request",
                    "request": self.id,
                    "route": self.route,
                    "method": self.method,
                    "status": response.status_code,
                    "revision": revision,
                    "ms": round((time.monotonic() - self.started) * 1000),
                    "stages": self.stages,
                    "sign_in_reason": self.reason,
                    "failure": (
                        {
                            "category": self.failure.category.value,
                            "stage": self.failure.stage.label,
                            "attempts": self.failure.attempts,
                        }
                        if self.failure
                        else None
                    ),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )


_current = contextvars.ContextVar("reader_trace", default=None)


@contextmanager
def request(route, method):
    trace = Trace(route, method)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


@contextmanager
def stage(which: Stage):
    trace = _current.get()
    values = {"ms": 0, "n": 0, "conflicts": 0}
    if trace:
        values = trace.stages.setdefault(which.label, values)
        trace.last = which
        trace.stack.append(which)
    started = time.monotonic()
    try:
        yield Span(values)
    except BaseException as error:
        if trace and trace.failed_error is not error:
            trace.failed_error = error
            trace.failed = which
            trace.waiting = Stage.RENEWAL_WAIT in trace.stack
        raise
    else:
        if trace:
            trace.last = which
    finally:
        if trace:
            trace.stack.pop()
        values["ms"] += round((time.monotonic() - started) * 1000)
