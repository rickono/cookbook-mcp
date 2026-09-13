import asyncio
import time
import pytest
from starlette.testclient import TestClient
from cookbook.server import JWTVerifier, create_app
from cookbook.storage import IntegrityError


def test_search_citations_filters_and_continuation(published):
    m, _, _, _, lib, _ = published
    results = lib.search("salt")["results"]
    assert len(results) == 1 and len(results[0]["aliases"]) == 2
    c = results[0]["citation"]
    assert c["publication_id"] == m.publication_id
    params = {k: c[k] for k in ("publication_id", "book_id", "source_id", "section_id")}
    first = lib.read_section(**params, limit=20)
    second = lib.read_section(**params, limit=20, offset=first["next_offset"])
    assert (
        first["text"] + second["text"] == lib.read_section(**params, limit=40)["text"]
    )
    assert len(lib.search("beans", book_ids=["book-0"])["results"][0]["aliases"]) == 1
    assert not lib.search("salt", format="PDF")["results"]
    assert not lib.search("salt", tag="excluded")["results"]
    with pytest.raises(IntegrityError):
        lib.read_section(m.publication_id, "hidden", "bad", "bad")
    with pytest.raises(IntegrityError):
        lib.search("salt", offset=2)
    with pytest.raises(IntegrityError):
        lib.get_image(m.publication_id, "book-0", c["source_id"], "../../metadata.db")
    data, binary = lib.get_image(m.publication_id, "book-0", c["source_id"], "image-0")
    assert binary.startswith(b"\xff\xd8")


@pytest.mark.parametrize(
    "change",
    [
        {"sub": "stranger"},
        {"aud": "other"},
        {"iss": "https://wrong/"},
        {"exp": 1},
        {"nbf": time.time() + 3600},
        {"iat": time.time() + 3600},
    ],
)
def test_invalid_claims(keys, mint, change):
    v = JWTVerifier(
        issuer="https://issuer.example/",
        audience="http://127.0.0.1:8765/mcp",
        subjects=["user-1"],
        public_key=keys[1],
    )
    assert asyncio.run(v.verify_token(mint(**change))) is None


def test_auth_every_http_operation(published, keys, mint):
    _, _, _, _, lib, _ = published
    v = JWTVerifier(
        issuer="https://issuer.example/",
        audience="http://127.0.0.1:8765/mcp",
        subjects=["user-1"],
        public_key=keys[1],
    )
    with TestClient(create_app(lib, v), base_url="http://127.0.0.1:8765") as client:
        for path in ["/mcp", "/readyz"]:
            for method in ["get", "post"]:
                r = getattr(client, method)(path)
                if path == "/readyz" and method == "post":
                    assert r.status_code == 405
                else:
                    assert r.status_code == 401
                    assert "resource_metadata" in r.headers["www-authenticate"]
        for method in ["tools/list", "tools/call", "resources/list"]:
            r = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": {
                        "name": "search_library",
                        "arguments": {"query": "salt"},
                    },
                },
            )
            assert r.status_code == 401 and "Beans" not in r.text
        for token in ["garbage", mint(sub="stranger"), mint(aud="wrong"), mint(exp=1)]:
            assert (
                client.post(
                    "/mcp", headers={"Authorization": "Bearer " + token}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/mcp", headers={"Authorization": "Bearer " + mint(scope="other")}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/readyz", headers={"Authorization": "Bearer " + mint()}
            ).status_code
            == 200
        )
        assert client.get("/healthz").json() == {"status": "ok"}
        assert (
            client.get("/.well-known/oauth-protected-resource/mcp").status_code == 200
        )
        assert client.get("/objects/anything").status_code == 404


def test_signature_algorithm_and_required_claims(keys, mint):
    import jwt

    v = JWTVerifier(
        issuer="https://issuer.example/",
        audience="http://127.0.0.1:8765/mcp",
        subjects=["user-1"],
        public_key=keys[1],
    )
    c = jwt.decode(mint(), options={"verify_signature": False})
    for token in [
        jwt.encode(c, "unrelated-secret-that-is-at-least-32-bytes", algorithm="HS256"),
        jwt.encode(c, None, algorithm="none"),
        mint()[:-10] + "AAAAAAAAAA",
    ]:
        assert asyncio.run(v.verify_token(token)) is None
    for claim in ["exp", "iss", "aud", "sub", "iat"]:
        bad = c.copy()
        del bad[claim]
        assert (
            asyncio.run(v.verify_token(jwt.encode(bad, keys[0], algorithm="RS256")))
            is None
        )


def test_corrupt_asset_cache_is_reverified(published):
    m, _, store, runtime, lib, _ = published
    citation = lib.search("salt")["results"][0]["citation"]
    args = (m.publication_id, citation["book_id"], citation["source_id"], "image-0")
    _, original = lib.get_image(*args)
    entry = next(e for e in m.files if e.path == "assets/image")
    (runtime.root / "cache" / entry.sha256).write_bytes(b"corrupted cached image")
    assert lib.get_image(*args)[1] == original
    assert (
        sum(p.stat().st_size for p in (runtime.root / "cache").iterdir())
        <= lib.cache_bytes
    )
    store.path(entry.key).write_bytes(b"corrupted remote image")
    (runtime.root / "cache" / entry.sha256).unlink()
    with pytest.raises(IntegrityError):
        lib.get_image(*args)
