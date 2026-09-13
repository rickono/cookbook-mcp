"""Exercise cookbook tools against approved fixtures. Only metrics leave this process."""

import argparse
import asyncio
import base64
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import httpx2
import jwt
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from cookbook.server import JWTVerifier, create_app
from cookbook.publication import Runtime
from cookbook.storage import LocalStore, atomic_write, canonical
from cookbook.library import Library

p = argparse.ArgumentParser()
p.add_argument("--store", type=Path, required=True)
p.add_argument("--runtime", type=Path, required=True)
p.add_argument("--report", type=Path, required=True)
p.add_argument("--inspector", action="store_true")
p.add_argument("--expected-books", type=int, nargs="+", default=[5, 40])
a = p.parse_args()
runtime = Runtime(LocalStore(a.store), a.runtime)
pub = runtime.recover()
lib = Library(runtime)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public = key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
url = f"http://127.0.0.1:{port}/mcp"
issuer = "https://local-fixture.invalid/"
v = JWTVerifier(
    issuer=issuer, audience=url, subjects=["fixture-user"], public_key=public
)
server = uvicorn.Server(
    uvicorn.Config(
        create_app(lib, v),
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="critical",
    )
)
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
token = jwt.encode(
    {
        "iss": issuer,
        "aud": url,
        "sub": "fixture-user",
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "scope": "library:read",
    },
    key,
    algorithm="RS256",
)
report = {"publication_id": pub, "tool_calls": 0, "books": []}
try:
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started

    async def exercise():
        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + token}, timeout=120
        ) as http:
            async with streamable_http_client(url, http_client=http) as transport:
                async with ClientSession(*transport) as session:
                    await session.initialize()
                    assert len((await session.list_tools()).tools) == 9

                    async def call(name, args):
                        r = await session.call_tool(name, args)
                        assert not r.is_error, name
                        report["tool_calls"] += 1
                        return r

                    catalog = await call(
                        "search_library", {"query": "", "mode": "catalog", "limit": 20}
                    )
                    assert len(catalog.structured_content["results"]) == len(
                        set(a.expected_books)
                    )
                    for match in catalog.structured_content["results"]:
                        c = match["citation"]
                        args = {
                            k: c[k] for k in ("publication_id", "book_id", "source_id")
                        }
                        book = await call(
                            "get_book",
                            {
                                "publication_id": pub,
                                "book_id": c["book_id"],
                                "limit": 50,
                            },
                        )
                        sid = next(
                            t["section_id"]
                            for t in book.structured_content["toc"]
                            if t.get("section_id")
                        )
                        read = await call(
                            "read_section", {**args, "section_id": sid, "limit": 200}
                        )
                        assert (
                            read.structured_content["citation"]["source_sha256"]
                            == c["source_sha256"]
                        )
                        artifact = await call(
                            "get_artifact", {**args, "artifact_id": sid}
                        )
                        assert any(
                            block.type == "resource" for block in artifact.content
                        )
                        original = await call(
                            "get_artifact", {**args, "artifact_id": "original"}
                        )
                        assert (
                            original.structured_content["delivery"]
                            == "not_available_in_local_poc"
                        )
                        kind = c["format"]
                        pixels = 0
                        if kind in ("PDF", "DJVU"):
                            page = await call("get_page", {**args, "physical_page": 20})
                            assert (
                                page.structured_content["citation"]["locator"][
                                    "physical_page"
                                ]
                                == 20
                            )
                            binary = next(b for b in page.content if b.type == "image")
                            pixels = len(base64.b64decode(binary.data))
                            (
                                a.report.parent
                                / f"qa-{kind}-{book.structured_content['calibre_id']}.jpg"
                            ).write_bytes(base64.b64decode(binary.data))
                        else:
                            candidates = await call(
                                "list_images", {**args, "section_id": sid}
                            )
                            assert all(b.type == "text" for b in candidates.content)
                            assert not candidates.meta
                            with lib.db(pub) as db:
                                im = db.execute(
                                    "select id from images where source_id=? limit 1",
                                    (c["source_id"],),
                                ).fetchone()
                            inspected = await call(
                                "inspect_image", {**args, "image_id": im["id"]}
                            )
                            assert not inspected.meta
                            assert any(
                                b.type == "image"
                                and b.annotations.audience == ["assistant"]
                                for b in inspected.content
                            )
                            image = await call(
                                "get_image", {**args, "image_id": im["id"]}
                            )
                            assert any(b.type == "image" for b in image.content)
                        await call(
                            "search_library",
                            {
                                "query": "salt" if kind != "DJVU" else "wine",
                                "book_ids": [c["book_id"]],
                            },
                        )
                        report["books"].append(
                            {
                                "calibre_id": book.structured_content["calibre_id"],
                                "format": kind,
                                "page_response_image_bytes": pixels,
                            }
                        )
                    assert {b["calibre_id"] for b in report["books"]} == set(
                        a.expected_books
                    )
                    await call("get_publication_info", {})

    asyncio.run(exercise())
    if a.inspector:
        # Keep the short-lived local test token out of shell history and printed command text.
        run = subprocess.run(
            [
                "npx",
                "--yes",
                "@modelcontextprotocol/inspector@2.6.0",
                "--cli",
                url,
                "--transport",
                "http",
                "--method",
                "tools/list",
                "--header",
                "Authorization: Bearer " + token,
            ],
            capture_output=True,
            timeout=120,
        )
        report["inspector_exit_code"] = run.returncode
        report["inspector_listed_search_library"] = (
            "search_library" in run.stdout.decode(errors="replace")
        )
        if run.returncode:
            report["inspector_error"] = (
                "Inspector CLI failed; inspect synthetic reproduction."
            )
    atomic_write(a.report, canonical(report))
    print(json.dumps(report))
finally:
    server.should_exit = True
    thread.join(timeout=5)
