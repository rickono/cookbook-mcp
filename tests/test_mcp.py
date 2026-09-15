"""Official SDK client against an actual loopback Streamable HTTP server."""

import asyncio
import socket
import threading
import time
import httpx2
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from cookbook.server import JWTVerifier, create_app
from cookbook.publication import Runtime


def test_authenticated_official_client(published, keys, mint, manifest_loads):
    m, _, _, _, lib, _ = published
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/mcp"
    v = JWTVerifier(
        issuer="https://issuer.example/",
        audience=url,
        subjects=["user-1"],
        public_key=keys[1],
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(lib, v),
            host="127.0.0.1",
            port=port,
            log_level="critical",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started

        async def exercise():
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + mint(aud=url)}
            ) as http:
                async with streamable_http_client(url, http_client=http) as transport:
                    async with ClientSession(*transport) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        assert len(listed.tools) == 9
                        inspect_tool = next(
                            t for t in listed.tools if t.name == "inspect_image"
                        )
                        candidates_tool = next(
                            t for t in listed.tools if t.name == "list_images"
                        )
                        # Neither discovery nor inspection may attach a display template.
                        assert not inspect_tool.meta
                        assert not candidates_tool.meta
                        image_tool = next(
                            t for t in listed.tools if t.name == "get_image"
                        )
                        uri = image_tool.meta["ui"]["resourceUri"]
                        template = await session.read_resource(uri)
                        assert (
                            template.contents[0].mime_type
                            == "text/html;profile=mcp-app"
                        )
                        assert "ui/initialize" in template.contents[0].text
                        assert "<img" in template.contents[0].text
                        assert (
                            template.contents[0].meta["ui"]["csp"]["connectDomains"]
                            == []
                        )
                        result = await session.call_tool(
                            "search_library", {"query": "salt"}
                        )
                        assert not result.is_error
                        c = result.structured_content["results"][0]["citation"]
                        args = {
                            k: c[k] for k in ("publication_id", "book_id", "source_id")
                        }
                        read = await session.call_tool(
                            "read_section",
                            {**args, "section_id": c["section_id"], "limit": 50},
                        )
                        assert (
                            not read.is_error
                            and len(read.structured_content["text"]) == 50
                        )
                        candidates = await session.call_tool(
                            "list_images", {**args, "section_id": c["section_id"]}
                        )
                        assert not candidates.is_error
                        assert all(b.type == "text" for b in candidates.content)
                        assert not candidates.meta
                        assert (
                            candidates.structured_content["images"][0]["image_id"]
                            == "image-0"
                        )
                        # Probing repeatedly must not produce viewer payloads. Only
                        # the final explicit get_image call below may display a card.
                        for _ in range(3):
                            inspected = await session.call_tool(
                                "inspect_image", {**args, "image_id": "image-0"}
                            )
                            assert not inspected.is_error and not inspected.meta
                            block = next(
                                b for b in inspected.content if b.type == "image"
                            )
                            assert block.annotations.audience == ["assistant"]
                            assert inspected.structured_content["image_id"] == "image-0"
                        bad_inspection = await session.call_tool(
                            "inspect_image", {**args, "image_id": "../../metadata.db"}
                        )
                        assert bad_inspection.is_error and not bad_inspection.meta
                        assert all(b.type == "text" for b in bad_inspection.content)
                        image = await session.call_tool(
                            "get_image", {**args, "image_id": "image-0"}
                        )
                        assert not image.is_error and any(
                            block.type == "image" for block in image.content
                        )
                        image_block = next(
                            b for b in image.content if b.type == "image"
                        )
                        assert image.meta["cookbookImage"]["data"] == image_block.data
                        assert image.meta["cookbookImage"]["metadata"]["citation"][
                            "title"
                        ]
                        assert "cookbookImage" not in image.structured_content
                        bad = await session.call_tool(
                            "get_image", {**args, "image_id": "../../metadata.db"}
                        )
                        assert bad.is_error and "metadata.db" not in str(bad.content)
                        assert not bad.meta or "cookbookImage" not in bad.meta
                        info = await session.call_tool("get_publication_info", {})
                        assert (
                            info.structured_content["publication_id"]
                            == m.publication_id
                        )

                        # Compare every result block on cold and warm metadata paths.
                        calls = [
                            ("search_library", {"query": "salt"}),
                            ("search_library", {"query": "Beans", "mode": "catalog"}),
                            (
                                "get_book",
                                {
                                    "publication_id": m.publication_id,
                                    "book_id": args["book_id"],
                                },
                            ),
                            (
                                "read_section",
                                {**args, "section_id": c["section_id"], "limit": 50},
                            ),
                            (
                                "read_section",
                                {
                                    **args,
                                    "section_id": c["section_id"],
                                    "offset": read.structured_content["next_offset"],
                                    "limit": 50,
                                },
                            ),
                            ("list_images", {**args, "section_id": c["section_id"]}),
                            ("inspect_image", {**args, "image_id": "image-0"}),
                            ("get_image", {**args, "image_id": "image-0"}),
                            ("get_artifact", {**args, "artifact_id": c["section_id"]}),
                            ("get_artifact", {**args, "artifact_id": "original"}),
                            (
                                "get_publication_info",
                                {"publication_id": m.publication_id},
                            ),
                        ]
                        for name, arguments in calls:
                            lib.runtime = Runtime(lib.runtime.store, lib.runtime.root)
                            before = dict(manifest_loads)
                            cold = await session.call_tool(name, arguments)
                            assert not cold.is_error, (name, cold)
                            assert manifest_loads == {
                                k: v + 1 for k, v in before.items()
                            }
                            if name == "get_artifact":
                                data = cold.structured_content
                                if arguments["artifact_id"] == "original":
                                    assert (
                                        data["delivery"] == "not_available_in_local_poc"
                                    )
                                    assert all(
                                        block.type == "text" for block in cold.content
                                    )
                                else:
                                    assert len(data["text"]) == 12000
                                    assert data["next_offset"] == 12000
                            warm = await session.call_tool(name, arguments)
                            assert warm.model_dump() == cold.model_dump(), name
                            assert manifest_loads == {
                                k: v + 1 for k, v in before.items()
                            }
                        for pub in ("f" * 32, "../../private-manifest"):
                            for name in ("search_library", "get_publication_info"):
                                arguments = {"publication_id": pub}
                                if name == "search_library":
                                    arguments["query"] = "salt"
                                bad = await session.call_tool(name, arguments)
                                assert bad.is_error
                                assert pub not in str(bad.content)
                        denied = await http.post(
                            url, headers={"Authorization": ""}, json={}
                        )
                        assert denied.status_code == 401

        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(timeout=5)
