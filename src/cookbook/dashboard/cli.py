"""Launch the local read-only cookbook dashboard."""

import argparse
import json
import os
import tempfile
import threading
import webbrowser
from pathlib import Path

from .runtime import Dashboard
from .web import create_app


def demo_config(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    a, b = "a" * 64, "b" * 64
    records = [
        {
            "namespace": "demo:catalog",
            "record_id": "17",
            "title": "The synthetic pantry",
            "membership": "included",
            "source_sha256": a,
            "format": "PDF",
        },
        {
            "namespace": "demo:alias",
            "record_id": "91",
            "title": "The synthetic pantry",
            "membership": "included",
            "source_sha256": a,
            "format": "PDF",
        },
        {
            "namespace": "demo:batch",
            "record_id": "17",
            "title": "Pending kitchen notebook",
            "membership": "included",
        },
        {
            "namespace": "demo:catalog",
            "record_id": "20",
            "title": "Held synthetic edition",
            "membership": "included",
            "source_sha256": b,
            "holds": [{"reason": "Owner review pending", "scope": "publication"}],
        },
        {
            "namespace": "demo:catalog",
            "record_id": "21",
            "title": "Undecided discovery",
            "membership": "undecided",
        },
    ]
    import time

    now = time.time()
    status = {
        "version": "dashboard-status.v1",
        "facts": [
            {
                "edition": "sha256:" + a,
                "dimension": "publication",
                "state": "catalog present",
                "publication": "demo-publication-A",
            },
            {
                "edition": "sha256:" + a,
                "dimension": "review",
                "state": "pending",
                "candidate": "demo-new-candidate",
                "scope": "whole candidate",
            },
            {"edition": "sha256:" + b, "dimension": "processing", "state": "pending"},
        ],
        "queue": [
            {
                "id": "report-1",
                "edition": "sha256:" + a,
                "origin": origin,
                "outcome": "human edge case",
            }
            for origin in ("triage", "build")
        ],
        "heartbeats": [
            {
                "id": "worker-1",
                "edition": "sha256:" + a,
                "run": "demo-run",
                "worker": "demo-worker",
                "phase": "waiting",
                "at": now - 180,
            }
        ],
        "blockers": [
            {
                "id": "unavailable-1",
                "edition": "sha256:" + a,
                "kind": "terminal refusal",
                "reason": "Synthetic unavailable scope",
                "scope": "page 2",
            }
        ],
    }
    (root / "registry.json").write_text(
        json.dumps({"version": "intended-book-registry.v1", "records": records})
    )
    (root / "status.json").write_text(json.dumps(status))
    config = {
        "version": "dashboard-config.v1",
        "storage": str(root / "state"),
        "sources": [
            {
                "id": "demo-registry",
                "kind": "registry",
                "path": str(root / "registry.json"),
            },
            {"id": "demo-status", "kind": "status", "path": str(root / "status.json")},
        ],
        "usage": [],
    }
    return config


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--config",
        type=Path,
        default=Path.home() / "cookbook-mcp-data/dashboard/config.json",
    )
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument(
        "--remote-login",
        action="store_true",
        help="Optional browser PKCE login, credentials kept in process memory",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Synthetic inventory in a temporary directory",
    )
    args = p.parse_args(argv)
    os.umask(0o077)
    dashboard = (
        Dashboard(demo_config(tempfile.mkdtemp(prefix="cookbook-dashboard-demo-")))
        if args.demo
        else Dashboard.from_file(args.config)
    )
    if args.remote_login:
        from ..publisher_login import LoginConfig, browser_login

        login_config = LoginConfig.from_environment()
        if any(
            s["kind"] == "remote" and s["endpoint"] != login_config.audience
            for s in dashboard.sources
        ):
            p.error("remote endpoint must match login audience")
        dashboard.bearer = browser_login(login_config).bearer
    import uvicorn

    url = f"http://127.0.0.1:{args.port}/"
    print("Cookbook dashboard: " + url, flush=True)
    print(
        "Synthetic demo" if args.demo else "Private configuration: " + str(args.config),
        flush=True,
    )
    if not args.no_browser:
        timer = threading.Timer(0.8, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    uvicorn.run(
        create_app(dashboard),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
