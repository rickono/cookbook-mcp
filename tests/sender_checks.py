"""Source-free tests run only by verify_review_sender.py in the sender VM job."""

import gzip
import http.server
import io
import json
import multiprocessing
import os
import shutil
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import ledger
import protocol
import transport
from guard import require_sender
from ocr_limits import OcrIsolationError, require_ocr_limits


def admit(path, number, queue):
    try:
        ledger.reserve(path, str(number), str(number), 1, {"a" * 64 + "/1": 6})
        queue.put(True)
    except ValueError:
        queue.put(False)


class SenderChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_actual_boundary(self):
        limits, remaining = require_sender()
        self.assertEqual(limits["memory"], 128 * 1024**2)
        self.assertEqual(limits["swap"], 0)
        self.assertEqual(limits["pids"], 12)
        self.assertEqual(limits["quota"] / limits["period"], 0.5)
        self.assertGreater(remaining, 0)
        with self.assertRaises(OcrIsolationError):
            require_ocr_limits()
        for module in ("pypdf", "PIL", "numpy", "torch", "paddle", "pytesseract"):
            self.assertIsNone(__import__("importlib.util").util.find_spec(module))
        for binary in ("pdftoppm", "tesseract", "ddjvu", "sh"):
            self.assertIsNone(shutil.which(binary))
        self.assertFalse(Path("/var/run/docker.sock").exists())
        self.assertFalse(Path("/work").exists())
        self.assertEqual(
            len(Path("/proc/net/route").read_text().strip().splitlines()), 1
        )
        with self.assertRaises(OSError):
            Path("/sender/worker.py").write_text("bad")
        with self.assertRaises(OSError):
            Path("/inputs/secret").write_text("bad")

    def ledger(self, spent=0, liabilities=0):
        path = self.directory / "pilot.sqlite"
        ledger.initialize(
            path, prior_spend=spent, prior_liabilities=liabilities, prior_attempts={}
        )
        return path

    def test_atomic_attempt_admission_across_processes(self):
        path = self.ledger()
        queue = multiprocessing.Queue()
        children = [
            multiprocessing.Process(target=admit, args=(path, n, queue))
            for n in range(8)
        ]
        # Stay beneath the synthetic 12-PID cap while two processes contend.
        answers = []
        for i in range(0, 8, 2):
            for child in children[i : i + 2]:
                child.start()
            for child in children[i : i + 2]:
                child.join(5)
                self.assertEqual(child.exitcode, 0)
            answers.extend(queue.get(timeout=2) for _ in range(2))
        queue.close()
        queue.join_thread()
        self.assertEqual(sum(answers), 6)
        state = ledger.snapshot(path)
        self.assertEqual(state["attempts"]["a" * 64 + "/1"], 6)
        self.assertEqual(state["liabilities"], 6)

    def test_budget_crash_resume_and_settlement(self):
        path = self.ledger(249_999_000, 500)
        scopes = {"a" * 64 + "/1": 6, "a" * 64 + "/1/whole": 3}
        ledger.reserve(path, "first", "semantic", 500, scopes)
        with self.assertRaises(ValueError):
            ledger.reserve(path, "next", "other", 1, scopes)
        with self.assertRaises(ValueError):
            ledger.reserve(path, "first", "semantic", 500, scopes)
        with self.assertRaises(ValueError):
            ledger.reserve(path, "new-id", "semantic", 500, scopes)
        state = ledger.snapshot(path)
        self.assertEqual(state["liabilities"], 1000)
        self.assertEqual(list(state["attempts"].values()), [1, 1])
        ledger.settle(path, "first", 100)
        ledger.settle(path, "first", 100)
        with self.assertRaises(ValueError):
            ledger.settle(path, "first", 101)
        self.assertEqual(ledger.snapshot(path)["liabilities"], 500)
        with self.assertRaises(FileExistsError):
            ledger.initialize(
                path, prior_spend=0, prior_liabilities=0, prior_attempts={}
            )

    def test_region_limit_and_atomic_rollback(self):
        path = self.ledger()
        with self.assertRaises(ValueError):
            ledger.reserve(
                path, "region-only", "region-only", 1, {"a" * 64 + "/1/whole": 3}
            )
        self.assertEqual(ledger.snapshot(path)["attempts"], {})
        scopes = {"a" * 64 + "/1": 6, "a" * 64 + "/1/whole": 3}
        for n in range(3):
            ledger.reserve(path, str(n), str(n), 1, scopes)
        with self.assertRaises(ValueError):
            ledger.reserve(path, "four", "four", 1, scopes)
        self.assertEqual(list(ledger.snapshot(path)["attempts"].values()), [3, 3])

    def test_unexpected_charges_block_admission(self):
        path = self.ledger()
        ledger.reserve(path, "first", "first", 1, {"a" * 64 + "/1": 6})
        with self.assertRaises(ValueError):
            ledger.settle(path, "first", 2)
        self.assertEqual(ledger.snapshot(path)["liabilities"], 2)
        with self.assertRaises(ValueError):
            ledger.reserve(path, "next", "next", 1, {"a" * 64 + "/2": 6})

    def packet(self):
        body = b'{"model":"synthetic"}'
        (self.directory / "request.json").write_bytes(body)
        (self.directory / "image.bin").write_bytes(
            b"synthetic image bytes; never decoded"
        )
        packet = {
            "version": 1,
            "provider": "decisions",
            "endpoint": protocol.ENDPOINTS["decisions"],
            "model": "synthetic",
            "purpose": "review",
            "source": "a" * 64,
            "candidate": "b" * 64,
            "corrections": "c" * 64,
            "scope": [{"page": 1, "regions": ["whole"]}],
            "complete": True,
            "request_sha256": protocol.digest(body),
            "assets": [
                {
                    "name": "image.bin",
                    "sha256": protocol.digest(
                        (self.directory / "image.bin").read_bytes()
                    ),
                    "width": 1000,
                    "height": 1000,
                    "transform": [1, 0, 0, 1, 0, 0],
                    "page": 1,
                }
            ],
            "request_id": "test",
            "maximum_cost": 1,
            "input_tokens": 1,
            "output_tokens": 1,
            "configuration": "synthetic",
            "questions_version": "1",
        }
        raw = json.dumps(packet).encode()
        (self.directory / "manifest.json").write_bytes(raw)
        return packet, protocol.digest(raw)

    def test_seal_bounds_scope_and_stale_evidence(self):
        packet, _ = self.packet()
        body = (self.directory / "request.json").read_bytes()

        def load():
            raw = json.dumps(packet).encode()
            (self.directory / "manifest.json").write_bytes(raw)
            return protocol.load_packet(self.directory, protocol.digest(raw))

        _, actual, scopes = load()
        self.assertEqual(actual, body)
        self.assertEqual(sorted(scopes.values()), [3, 6])
        for field, value in [
            ("endpoint", "https://example.com/"),
            ("complete", False),
            ("input_tokens", 20001),
        ]:
            previous = packet[field]
            packet[field] = value
            with self.assertRaises(ValueError):
                load()
            packet[field] = previous
        (self.directory / "image.bin").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            load()
        with self.assertRaises(ValueError):
            protocol.bounded_read(self.directory / "request.json", 1)
        with self.assertRaises(ValueError):
            protocol.load_packet(self.directory, "0" * 64)

    def test_proxy_and_credential_restrictions(self):
        for key in ("HTTPS_PROXY", "https_proxy", "OPENAI_BASE_URL", "SSL_CERT_FILE"):
            with (
                patch.dict(os.environ, {key: "forbidden"}),
                self.assertRaises(ValueError),
            ):
                protocol.reject_ambient_overrides()
        path = self.directory / "secret"
        path.write_text("synthetic-key")
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            protocol.credential(path)
        path.chmod(0o600)
        self.assertEqual(protocol.credential(path), "synthetic-key")
        link = self.directory / "link"
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            protocol.credential(link)

    def test_stream_bounds_and_decompression(self):
        class Response(io.BytesIO):
            def __init__(self, raw, headers):
                super().__init__(raw)
                self.headers = headers

            def getheader(self, key, default=None):
                return self.headers.get(key, default)

        self.assertEqual(
            transport.read_response(
                Response(gzip.compress(b"{}"), {"Content-Encoding": "gzip"})
            ),
            b"{}",
        )
        bomb = gzip.compress(b"x" * (protocol.MAX_BYTES + 1))
        for raw, headers in [
            (b"", {"Content-Length": str(protocol.MAX_BYTES + 1)}),
            (bomb, {"Content-Encoding": "gzip"}),
            (b"bad", {"Content-Length": "4"}),
            (b"bad", {"Content-Encoding": "br"}),
        ]:
            with self.assertRaises(ValueError):
                transport.read_response(Response(raw, headers))
        with self.assertRaises(ValueError):
            transport.exchange(
                "https://api.openai.com/v1/decisions",
                b"x" * (protocol.MAX_BYTES + 1),
                "synthetic",
                ssl.create_default_context(),
            )

    def test_live_dispatch_disabled(self):
        with self.assertRaises(PermissionError):
            transport.transaction(self.directory, protocol.ENDPOINTS["decisions"])
        import worker

        with self.assertRaises(PermissionError):
            worker.main()

    def test_https_and_absolute_deadline(self):
        directory = self.directory
        shutil.copy("/inputs/cert.pem", directory / "ca.pem")
        shutil.copy("/inputs/secret", directory / "secret")
        (directory / "secret").chmod(0o600)
        (directory / "request.json").write_bytes(b"{}")
        mode = ["normal"]

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.server.paths.append(self.path)
                if mode[0] == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://example.com/")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                if mode[0] == "slow":
                    time.sleep(1)
                try:
                    self.wfile.write(b"{}")
                except OSError:
                    pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        server.paths = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain("/inputs/cert.pem", "/inputs/key.pem")
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        endpoint = f"https://127.0.0.1:{server.server_port}/fixture"
        # Unknown CA must fail before any HTTP request is received.
        with self.assertRaises(ssl.SSLCertVerificationError):
            transport.exchange(
                endpoint, b"{}", "synthetic", ssl.create_default_context()
            )
        self.assertEqual(server.paths, [])
        self.assertEqual(
            transport.transaction(directory, endpoint, synthetic=True, seconds=3), b"{}"
        )
        (directory / "response.json").unlink()
        from worker import dispatch_synthetic

        path = self.ledger()
        packet, seal = self.packet()
        self.assertEqual(
            dispatch_synthetic(directory, seal, path, endpoint, seconds=3), b"{}"
        )
        with self.assertRaises(ValueError):
            dispatch_synthetic(directory, seal, path, endpoint, seconds=3)
        self.assertEqual(ledger.snapshot(path)["liabilities"], 1)
        packet["request_id"] = "renamed"
        renamed = json.dumps(packet).encode()
        (directory / "manifest.json").write_bytes(renamed)
        with self.assertRaises(ValueError):
            dispatch_synthetic(
                directory, protocol.digest(renamed), path, endpoint, seconds=3
            )
        ledger.settle(path, "test", 1)
        (directory / "response.json").unlink()
        mode[0] = "redirect"
        with self.assertRaises(ValueError):
            transport.transaction(directory, endpoint, synthetic=True, seconds=3)
        self.assertEqual(server.paths, ["/fixture", "/fixture", "/fixture"])
        mode[0] = "slow"
        packet["request_id"] = "slow"
        raw = json.dumps(packet).encode()
        (directory / "manifest.json").write_bytes(raw)
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            dispatch_synthetic(
                directory, protocol.digest(raw), path, endpoint, seconds=0.25
            )
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(ledger.snapshot(path)["liabilities"], 1)

    def test_reservation_survives_abrupt_process_exit(self):
        import subprocess
        import sys

        path = self.ledger()
        source = f"import ledger,os;ledger.reserve({str(path)!r},'crash','crash',1,{{'a'*64+'/1':6}});os._exit(9)"
        result = subprocess.run([sys.executable, "-c", source], check=False)
        self.assertEqual(result.returncode, 9)
        self.assertEqual(ledger.snapshot(path)["liabilities"], 1)
        with self.assertRaises(ValueError):
            ledger.reserve(path, "crash", "crash", 1, {"a" * 64 + "/1": 6})


if __name__ == "__main__":
    unittest.main(verbosity=2)
