"""Private cookbook build, publish, restore and service commands."""

import argparse
import json
import os
import sys
from pathlib import Path
from .publication import Manifest, Runtime, publish, restore
from .storage import LocalStore, IntegrityError, atomic_write, canonical, file_lock
from .ocr_limits import OcrIsolationError


def _main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("serve-hosted")
    sub.add_parser("supervise")
    sub.add_parser(
        "check-publisher-login", help="Verify browser sign-in without uploading"
    )
    remote = sub.add_parser(
        "publish-s3", help="Upload a reviewed build and await hosted activation"
    )
    remote.add_argument("--build", type=Path, required=True)
    remote.add_argument("--state-directory", type=Path, required=True)
    remote.add_argument("--readiness-url", required=True)
    remote_auth = remote.add_mutually_exclusive_group(required=True)
    remote_auth.add_argument("--token-file", type=Path)
    remote_auth.add_argument("--browser-login", action="store_true")
    ack = sub.add_parser(
        "wait-active",
        help="Resume authenticated activation acknowledgement without uploading",
    )
    ack.add_argument("--pointer", type=Path, required=True)
    ack.add_argument("--readiness-url", required=True)
    ack_auth = ack.add_mutually_exclusive_group(required=True)
    ack_auth.add_argument("--token-file", type=Path)
    ack_auth.add_argument("--browser-login", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--snapshot", type=Path, required=True)
    b.add_argument("--books", type=int, nargs="+", required=True)
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--ocr-cache", type=Path, required=True)
    b.add_argument(
        "--force-ocr-books",
        type=int,
        nargs="+",
        default=[],
        help="Ignore embedded text and OCR every page for selected PDF/DjVu Calibre IDs",
    )
    pub = sub.add_parser("publish-local")
    pub.add_argument("--build", type=Path, required=True)
    pub.add_argument("--store", type=Path, required=True)
    pub.add_argument("--runtime", type=Path, required=True)
    rec = sub.add_parser("restore-local")
    rec.add_argument("--store", type=Path, required=True)
    rec.add_argument("--destination", type=Path, required=True)
    rec.add_argument("--runtime-only", action="store_true")
    s = sub.add_parser("serve-local")
    s.add_argument("--store", type=Path, required=True)
    s.add_argument("--runtime", type=Path, required=True)
    s.add_argument("--public-key", type=Path, required=True)
    s.add_argument("--issuer", required=True)
    s.add_argument("--subject", required=True)
    s.add_argument("--port", type=int, default=8765)
    review = sub.add_parser("review-ocr")
    review.add_argument("--ocr-cache", type=Path, required=True)
    review.add_argument("--id", required=True)
    review.add_argument("--result-sha256", required=True)
    review.add_argument(
        "--decision", choices=["accept", "correct", "nontext"], required=True
    )
    review.add_argument("--text-file", type=Path)
    report = sub.add_parser("review-report")
    report.add_argument("--build", type=Path, required=True)
    report.add_argument("--ocr-cache", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    final = sub.add_parser("finalize-local")
    final.add_argument("--build", type=Path, required=True)
    final.add_argument("--ocr-cache", type=Path, required=True)
    final.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.command == "check-publisher-login":
        from .publisher_login import LoginConfig, browser_login

        token = browser_login(LoginConfig.from_environment())
        token.bearer()
        print(json.dumps({"status": "login_verified", "scope": "library:read"}))
        return
    if a.command == "serve-hosted":
        from .hosted import serve

        serve()
        return
    if a.command == "supervise":
        from .supervisor import main as supervise

        supervise()
        return
    if a.command in ("publish-s3", "wait-active"):
        from .hosted import https_url, store_from_environment, wait_for_activation

        https_url(a.readiness_url)
        # Restrict acknowledgement to the configured resource server, including origin.
        audience = https_url(os.environ["COOKBOOK_AUDIENCE"])
        from urllib.parse import urlsplit

        target, resource = urlsplit(a.readiness_url), urlsplit(audience)
        if (target.scheme, target.netloc, target.path) != (
            resource.scheme,
            resource.netloc,
            "/readyz",
        ):
            raise ValueError("readiness target must match the resource server")
        if a.token_file and a.token_file.stat().st_mode & 0o077:
            raise ValueError("token file must be owner-only")
        login_config = None
        if a.browser_login:
            from .publisher_login import LoginConfig, LoginError, browser_login

            login_config = LoginConfig.from_environment()

        def activate(pointer):
            if login_config:
                # Sign in after upload/readback, before starting the acknowledgement timer.
                try:
                    token = browser_login(login_config)
                except LoginError as error:
                    print(json.dumps({"error": str(error)}), file=sys.stderr)
                    return None
                provider = token.bearer
            else:
                provider = lambda: a.token_file.read_text().strip()
            return wait_for_activation(pointer, a.readiness_url, provider)

        if a.command == "wait-active":
            pointer = json.loads(a.pointer.read_bytes())
            mid = activate(pointer)
            print(
                json.dumps(
                    {"status": "active" if mid else "pending_activation", **pointer}
                )
            )
            if not mid:
                raise SystemExit(4)
            return
        store = store_from_environment()
        a.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with file_lock(a.state_directory / ".publisher.lock"):
            m = Manifest.model_validate_json((a.build / "manifest.json").read_bytes())
            inputs = {
                k: Path(v)
                for k, v in json.loads((a.build / "inputs.json").read_bytes()).items()
            }
            _, version = store.read_version("control/active.json")

            def record_and_wait(pointer):
                atomic_write(
                    a.state_directory / "pending-activation.json", canonical(pointer)
                )
                return activate(pointer)

            result = publish(
                store, m, inputs, expected_version=version, activate=record_and_wait
            )
            if result["status"] == "active":
                raw, history_version = store.read_version("control/successful.json")
                history = json.loads(raw) if raw else []
                pointer = {k: result[k] for k in ("publication_id", "manifest_sha256")}
                history = [pointer] + [
                    v for v in history if v["publication_id"] != m.publication_id
                ]
                store.put_bytes(
                    "control/successful.json",
                    canonical(history),
                    expected=history_version,
                )
            print(json.dumps(result))
            if result["status"] != "active":
                raise SystemExit(4)
        return
    if a.command == "review-ocr":
        from .ocr import decide

        result = decide(
            a.ocr_cache,
            a.id,
            a.result_sha256,
            a.decision,
            a.text_file.read_text() if a.text_file else None,
        )
        print(json.dumps({"review_id": a.id, "pending": result["pending"]}))
        return
    if a.command == "review-report":
        from .quality import read_report
        from .ocr import write_review_page

        count = write_review_page(a.ocr_cache, read_report(a.build)["items"], a.output)
        print(json.dumps({"pending_pages": count, "report": str(a.output)}))
        return
    if a.command == "finalize-local":
        from .quality import finalize

        m = finalize(a.build, a.ocr_cache, a.output)
        print(
            json.dumps(
                {"publication_id": m.publication_id, "status": "ready_to_publish"}
            )
        )
        return
    if a.command == "build":
        from .build import build_snapshot

        m, _, stats = build_snapshot(
            a.snapshot,
            a.books,
            a.output,
            a.ocr_cache,
            progress=lambda d: print(json.dumps(d), flush=True),
            force_ocr_ids=a.force_ocr_books,
        )
        from .quality import read_report
        from .ocr import write_review_page

        pending = read_report(a.output)["pending_ids"]
        if pending:
            write_review_page(
                a.ocr_cache,
                read_report(a.output)["items"],
                a.output / "ocr-review.html",
            )
        print(
            json.dumps(
                {
                    "publication_id": m.publication_id,
                    "stats": stats,
                    "pending_ocr_pages": len(pending),
                    "status": "review_required" if pending else "ready_to_publish",
                }
            )
        )
        if pending:
            raise SystemExit(3)
    elif a.command == "publish-local":
        store = LocalStore(a.store)
        runtime = Runtime(store, a.runtime)
        with file_lock(a.store / ".publisher.lock"):
            m = Manifest.model_validate_json((a.build / "manifest.json").read_bytes())
            inputs = {
                k: Path(v)
                for k, v in json.loads((a.build / "inputs.json").read_bytes()).items()
            }
            raw, version = store.read_version("control/active.json")
            # A retry of the same verified pointer can confirm activation without rebuilding.
            result = publish(
                store, m, inputs, expected_version=version, activate=runtime.activate
            )
            if result["status"] == "active":
                history_path = a.store / "control/successful.json"
                history = (
                    json.loads(history_path.read_bytes())
                    if history_path.exists()
                    else []
                )
                pointer = {k: result[k] for k in ("publication_id", "manifest_sha256")}
                history = [pointer] + [
                    v for v in history if v["publication_id"] != m.publication_id
                ]
                atomic_write(history_path, canonical(history))
            print(json.dumps(result))
    elif a.command == "restore-local":
        store = LocalStore(a.store)
        raw, _ = store.read_version("control/active.json")
        if not raw:
            raise IntegrityError("no active publication")
        m = restore(store, json.loads(raw), a.destination, runtime_only=a.runtime_only)
        print(json.dumps({"restored": m.publication_id}))
    else:
        import uvicorn
        from .library import Library
        from .server import JWTVerifier, create_app

        store = LocalStore(a.store)
        runtime = Runtime(store, a.runtime)
        runtime.recover()
        verifier = JWTVerifier(
            issuer=a.issuer,
            audience=f"http://127.0.0.1:{a.port}/mcp",
            subjects=[a.subject],
            public_key=a.public_key.read_text(),
        )
        uvicorn.run(
            create_app(Library(runtime), verifier),
            host="127.0.0.1",
            port=a.port,
            access_log=False,
            log_level="critical",
        )


def main():
    import logging
    import sys

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    try:
        _main()
    except Exception as error:
        from .ocr import ReviewRequired
        from .publisher_login import LoginError

        if isinstance(error, OcrIsolationError):
            print(
                json.dumps({"error": "ocr_isolation_required", "message": str(error)}),
                file=sys.stderr,
            )
            raise SystemExit(2) from None
        if isinstance(error, LoginError):
            print(json.dumps({"error": str(error)}), file=sys.stderr)
            raise SystemExit(1) from None

        if isinstance(error, ReviewRequired):
            print(
                json.dumps(
                    {
                        "error": "review_required",
                        "message": "Build is not eligible for publication under the current OCR policy. Rebuild or review and finalize it.",
                    }
                ),
                file=sys.stderr,
            )
            raise SystemExit(3) from None
        code = (
            "integrity_or_processing_failure"
            if isinstance(error, IntegrityError)
            else "operation_failed"
        )
        print(
            json.dumps(
                {
                    "error": code,
                    "message": "Operation did not complete; prior runtime state is preserved unless activation was already confirmed.",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
