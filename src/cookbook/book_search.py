"""Owned loopback Typesense keyword engine; immutable per-publication indexes."""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .book_model import MODEL_PATH, connection
from .storage import IntegrityError, canonical

FIELDS = [
    {"name": "title", "type": "string"},
    {"name": "text", "type": "string"},
    {"name": "edition_id", "type": "string", "facet": True},
    {"name": "target_id", "type": "string", "facet": True},
    {"name": "kind", "type": "string", "facet": True},
    {"name": "state", "type": "string", "facet": True},
]


class BookSearch:
    def __init__(self, binary, root, port=8120, peer_port=8121):
        self.binary, self.root = Path(binary).resolve(), Path(root).resolve()
        self.port, self.peer_port = port, peer_port
        self.url = f"http://127.0.0.1:{port}"
        self.key = secrets.token_urlsafe(32)
        self.process = None
        self.log = None
        self.lock = threading.Lock()
        self.prepared = set()

    def start(self):
        if self.process:
            raise IntegrityError("search engine already owned")
        for port in (self.port, self.peer_port):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = self.root / "index"
        data.mkdir(exist_ok=True, mode=0o700)
        config = self.root / "typesense.ini"
        config.write_text(
            f"[server]\ndata-dir={data}\napi-key={self.key}\napi-address=127.0.0.1\napi-port={self.port}\npeering-address=127.0.0.1\npeering-port={self.peer_port}\nthread-pool-size=2\nnum-collections-parallel-load=1\nmax-indexing-concurrency=2\nenable-cors=false\nenable-access-logging=false\nenable-search-logging=false\nenable-search-analytics=false\nlog-slow-searches-time-ms=-1\n"
        )
        config.chmod(0o600)
        self.log = (self.root / "engine.log").open("ab")
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("TYPESENSE_", "AWS_", "S3_", "COOKBOOK_"))
        }
        try:
            self.process = subprocess.Popen(
                [str(self.binary), "--config", str(config)],
                stdout=self.log,
                stderr=self.log,
                env=env,
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise IntegrityError("search engine stopped")
                try:
                    if self.call("GET", "/health", timeout=1).get("ok"):
                        version = self.call("GET", "/debug")["version"]
                        if not version.startswith("30.2"):
                            raise IntegrityError("search engine version differs")
                        return
                except OSError:
                    pass
                time.sleep(0.1)
            raise IntegrityError("search engine startup timed out")
        except Exception:
            self.close()
            raise

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        if self.log:
            self.log.close()
            self.log = None

    def call(self, method, path, data=None, raw=False, timeout=10):
        if self.process is None or self.process.poll() is not None:
            raise IntegrityError("search engine unavailable")
        body = (
            data.encode()
            if isinstance(data, str)
            else canonical(data)
            if data is not None
            else None
        )
        request = Request(
            self.url + path,
            method=method,
            data=body,
            headers={
                "X-TYPESENSE-API-KEY": self.key,
                "Content-Type": "text/plain" if raw else "application/json",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            value = response.read(4 * 1024 * 1024 + 1)
        if len(value) > 4 * 1024 * 1024:
            raise IntegrityError("search response exceeds budget")
        return value.decode() if raw else json.loads(value)

    def collection(self, publication_id):
        if not re.fullmatch(r"[a-f0-9]{32}", publication_id):
            raise IntegrityError("invalid publication")
        return "cookbook_" + publication_id

    def prepare(self, manifest, directory):
        entry = next((e for e in manifest.files if e.path == MODEL_PATH), None)
        if entry is None:
            return
        name = self.collection(manifest.publication_id)
        with self.lock:
            if name in self.prepared:
                return
            path = directory / MODEL_PATH
            with connection(path) as db:
                count = db.execute("select count(*) from search_units").fetchone()[0]
                metadata = {
                    "model_sha256": entry.sha256,
                    "publication_id": manifest.publication_id,
                    "index_version": "keyword-v1",
                }
                try:
                    existing = self.call("GET", "/collections/" + name)
                except HTTPError as error:
                    if error.code != 404:
                        raise
                    existing = None
                if (
                    existing
                    and existing.get("metadata") == metadata
                    and existing["num_documents"] == count
                    and all(
                        not f.get("embed") and f["type"] != "float[]"
                        for f in existing["fields"]
                    )
                ):
                    self.prepared.add(name)
                    return
                if existing:
                    # This collection belongs solely to this exact immutable publication.
                    self.call("DELETE", "/collections/" + name)
                self.call(
                    "POST",
                    "/collections",
                    {"name": name, "fields": FIELDS, "metadata": metadata},
                )
                batch = []
                batch_bytes = 0

                def flush():
                    result = self.call(
                        "POST",
                        f"/collections/{name}/documents/import?action=create&dirty_values=reject",
                        "\n".join(batch),
                        raw=True,
                        timeout=60,
                    )
                    statuses = [json.loads(line) for line in result.splitlines()]
                    if len(statuses) != len(batch) or any(
                        not s.get("success") for s in statuses
                    ):
                        raise IntegrityError("search index import failed")
                    batch.clear()

                for row in db.execute("select * from search_units order by id"):
                    line = json.dumps(dict(row), ensure_ascii=False)
                    if batch and (
                        len(batch) >= 100 or batch_bytes + len(line.encode()) > 512000
                    ):
                        flush()
                        batch_bytes = 0
                    batch.append(line)
                    batch_bytes += len(line.encode())
                if batch:
                    flush()
                if self.call("GET", "/collections/" + name)["num_documents"] != count:
                    raise IntegrityError("search index is incomplete")
                self.prepared.add(name)

    def search(
        self, publication_id, query, book_ids, kinds, include_candidates, limit, page
    ):
        clauses = []
        if book_ids:
            clauses.append("edition_id:=[" + ",".join(book_ids) + "]")
        if kinds:
            clauses.append("kind:=[" + ",".join(kinds) + "]")
        if not include_candidates:
            clauses.append("state:!=candidate")
        params = {
            "q": query,
            "query_by": "title,text",
            "query_by_weights": "5,1",
            "num_typos": 2,
            "prefix": "false",
            "drop_tokens_threshold": 100,
            "typo_tokens_threshold": 100,
            "group_by": "target_id",
            "group_limit": 1,
            "per_page": limit,
            "page": page,
            "include_fields": "id",
            "highlight_fields": "text",
            "highlight_start_tag": "",
            "highlight_end_tag": "",
            "highlight_affix_num_tokens": 8,
            "search_cutoff_ms": 1500,
        }
        if clauses:
            params["filter_by"] = " && ".join(clauses)
        return self.call(
            "GET",
            "/collections/"
            + self.collection(publication_id)
            + "/documents/search?"
            + urlencode(params),
            timeout=5,
        )
