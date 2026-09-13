"""Separate process watchdog; no provider dependencies or library credentials in probes."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

import httpx

from .telemetry import event


def healthy(url):
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
            response = client.get(url)
            return response.status_code == 200 and response.json() == {"status": "ok"}
    except (httpx.HTTPError, ValueError):
        return False


def terminate(child):
    if child.poll() is not None:
        # Render subprocesses may survive a crashed worker; clean up its process group.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        child.wait()
        return
    try:
        child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
    # A parent can exit before its descendants.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def supervise(
    command,
    health_url,
    stop,
    *,
    interval=30,
    startup_grace=300,
    failures=3,
    probe=healthy,
):
    child = None
    try:
        while not stop.is_set():
            child = subprocess.Popen(command, start_new_session=True)
            event("worker_started")
            started = time.monotonic()
            next_probe = started + interval
            misses = 0
            while not stop.wait(min(0.25, interval)):
                if child.poll() is not None:
                    event("worker_exited")
                    break
                now = time.monotonic()
                if now < next_probe:
                    continue
                next_probe = now + interval
                # Grace suppresses failed probes, but not crash detection.
                if probe(health_url):
                    misses = 0
                elif now - started >= startup_grace:
                    misses += 1
                if misses >= failures:
                    event("worker_liveness_failed")
                    break
            terminate(child)
            child = None
            # Bound crash-loop frequency; startup liveness grace is separate.
            stop.wait(min(1, interval))
    finally:
        if child is not None:
            terminate(child)


def main():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    port = int(os.environ.get("PORT", "8000"))
    supervise(
        [sys.executable, "-m", "cookbook.cli", "serve-hosted"],
        f"http://127.0.0.1:{port}/healthz",
        stop,
    )
