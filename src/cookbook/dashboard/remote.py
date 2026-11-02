"""Allowlisted metadata-only remote MCP observation with session-only bearer access."""

import asyncio
from urllib.parse import urlsplit

from .metadata import identity, require


async def _collect(endpoint, bearer):
    import httpx2 as httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    require(
        endpoint,
        urlsplit(endpoint).scheme == "https" and not urlsplit(endpoint).username,
    )
    async with (
        httpx.AsyncClient(
            headers={"Authorization": "Bearer " + bearer()},
            timeout=18,
            follow_redirects=False,
        ) as http,
        streamable_http_client(endpoint, http_client=http) as transport,
        ClientSession(*transport) as session,
    ):
        await session.initialize()
        info = await session.call_tool("get_publication_info", {})
        require(info, not info.is_error)
        pub = info.structured_content["publication_id"]
        records, facts, offset = [], [], 0
        while True:
            result = await session.call_tool(
                "search_library",
                {
                    "query": "",
                    "mode": "catalog",
                    "publication_id": pub,
                    "offset": offset,
                    "limit": 20,
                },
            )
            require(result, not result.is_error)
            data = result.structured_content
            require(data, data["publication_id"] == pub)
            for row in data["results"]:
                c = row["citation"]
                sha = c["source_id"].split(":")[-1]
                for alias in row.get("aliases", [c["book_id"]]):
                    r = {
                        "namespace": "remote",
                        "record_id": alias,
                        "title": c.get("title", c.get("book_title", alias)),
                        "source_sha256": sha,
                        "membership": "undecided",
                    }
                    records.append(r)
                    facts.append(
                        {
                            "edition": identity(r),
                            "dimension": "publication",
                            "state": "catalog present",
                            "publication": pub,
                            "book_id": c["book_id"],
                            "source_id": c["source_id"],
                            "evidence": "remote catalog; access unobserved",
                        }
                    )
            nxt = data.get("next_offset")
            if nxt is None:
                break
            require(nxt, type(nxt) is int and offset < nxt <= 10000)
            offset = nxt
        return {"records": records, "facts": facts, "publication": pub}


def collect_remote(source, bearer):
    if bearer is None:
        raise ValueError("remote sign-in required")
    return asyncio.run(
        asyncio.wait_for(_collect(source["endpoint"], bearer), timeout=19)
    )
