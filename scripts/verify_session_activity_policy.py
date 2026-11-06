"""Executable policy examples for session redesign; not a production-store proof.

Checks a finite transition model with scaled time. Atomic authoritative
transitions are assumed. Real SQL/CAS races require integration tests separately.
No network, application configuration, OCR, or production session is used.
"""

import hashlib
import hmac
from dataclasses import dataclass, replace
from itertools import product

IDLE = 4
ABSOLUTE = 6
TOUCH_INTERVAL = 2


@dataclass(frozen=True)
class Session:
    seen: int = 0
    actual_activity: int = 0  # Test oracle, not additional persisted application data.
    generation: int = 0
    revoked: bool = False


@dataclass(frozen=True)
class World:
    now: int = 0
    generation: int = 0
    sessions: tuple[Session, Session] = (Session(), Session())
    touches: int = 0


def admitted(world, session):
    return (
        not session.revoked
        and session.generation == world.generation
        and world.now < session.seen + IDLE
        and world.now < ABSOLUTE
    )


def step(world, action):
    if action == "tick":
        return replace(world, now=world.now + 1)
    if action == "restart":
        return world  # All admission-critical state is durable.
    if action == "logout_all":
        return replace(world, generation=world.generation + 1)
    index = 1 if action.endswith("b") else 0
    session = world.sessions[index]
    values = list(world.sessions)
    if action.startswith("logout_"):
        values[index] = replace(session, revoked=True)
        return replace(world, sessions=tuple(values))
    allowed = admitted(world, session)
    if not allowed:
        return world
    # A passive request, including a background heartbeat, does not advance seen.
    if action.startswith("passive_"):
        return world
    due = world.now - session.seen >= TOUCH_INTERVAL
    if action.startswith("failed_") and due:
        return world  # A failed due touch is denied, never credited as activity.
    values[index] = replace(
        session,
        seen=world.now if due else session.seen,
        actual_activity=world.now,
    )
    return replace(world, sessions=tuple(values), touches=world.touches + int(due))


def invariants(world):
    for session in world.sessions:
        assert 0 <= session.actual_activity - session.seen < TOUCH_INTERVAL
        if admitted(world, session):
            assert not session.revoked
            assert session.generation == world.generation
            assert world.now < session.actual_activity + IDLE
            assert world.now < ABSOLUTE
        # Persisted expiry can be early by less than the touch interval, never late.
        assert (
            0 <= session.actual_activity + IDLE - (session.seen + IDLE) < TOUCH_INTERVAL
        )


def run():
    actions = (
        "tick",
        "restart",
        "logout_a",
        "logout_all",
        "passive_a",
        "passive_b",
        "active_a",
        "active_b",
        "failed_a",
    )
    states = {World()}
    transitions = 0
    for _ in range(8):
        following = set()
        for world, action in product(states, actions):
            result = step(world, action)
            transitions += 1
            invariants(result)
            if action in {"restart", "passive_a", "passive_b"}:
                assert result.touches == world.touches
                assert result.sessions == world.sessions
            if action == "logout_all":
                assert all(not admitted(result, s) for s in result.sessions)
            if action == "logout_a":
                assert not admitted(result, result.sessions[0])
                assert result.sessions[1] == world.sessions[1]
            following.add(result)
        states = following

    # Bursts at one clock instant require one due durable touch per device.
    world = World(now=TOUCH_INTERVAL)
    for _ in range(100):
        world = step(world, "active_a")
    assert world.touches == 1
    world = step(world, "restart")
    world = step(world, "active_b")
    assert world.touches == 2

    # An old successful grant reused from a positive TTL cache survives logout.
    before = World()
    cached_allowed = admitted(before, before.sessions[0])
    after = step(before, "logout_all")
    assert cached_allowed and not admitted(after, after.sessions[0])

    # Repeated lost deferred flushes can exceed the claimed coalescing bound.
    durable_seen = 0
    actual_after_repeated_crashes = TOUCH_INTERVAL + 1
    assert actual_after_repeated_crashes - durable_seen > TOUCH_INTERVAL

    from cryptography.fernet import Fernet

    cipher = Fernet(Fernet.generate_key())
    token = b"synthetic shared refresh token"
    first, second = cipher.encrypt(token), cipher.encrypt(token)
    assert first != second and cipher.decrypt(first) == cipher.decrypt(second)
    fingerprint_key = b"synthetic key kept outside the model store"

    def identity(value):
        return hmac.digest(fingerprint_key, value, hashlib.sha256)

    assert identity(cipher.decrypt(first)) == identity(cipher.decrypt(second))

    print(f"Policy model passed: {transitions} transitions; {len(states)} final states")
    print("Confirmed: encrypted ciphertext is unsuitable as shared-token identity.")
    print("Checked: fresh revocation, strict absolute expiry, conservative idle bound,")
    print(
        "passive traffic, durable restarts, per-device touches and due-touch failure."
    )
    print(
        "Counterexamples confirmed: positive grant cache; volatile deferred activity."
    )
    print(
        "Not proved: SQL isolation, real-store durability, token rotation, or latency."
    )


if __name__ == "__main__":
    run()
