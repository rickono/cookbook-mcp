"""Assembled reader HTTP boundary; synthetic publication and identity only."""

import time
from datetime import UTC
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from cookbook.hosted import create_hosted_app
from cookbook.reader import Reader, ReaderConfig
from cookbook.server import JWTVerifier, create_app
from cookbook.storage import LocalStore


@pytest.fixture
def reader_env(published, keys, mint, tmp_path):
    clock = [time.time()]
    config = ReaderConfig(
        origin="https://reader.example",
        client_id="web-client",
        client_secret="synthetic-secret",
    )
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="http://127.0.0.1:8765/mcp",
        subjects=["user-1"],
        public_key=keys[1],
    )

    class Identity:
        tokens = None
        refused = False
        renewed_tokens = None

        async def exchange(self, code, verifier, nonce):
            assert code == "synthetic-code" and len(verifier) >= 43
            return self.tokens or {
                "access_token": mint(),
                "refresh_token": "synthetic-refresh",
            }

        async def renew(self, token):
            if self.refused:
                raise ValueError("provider private error")
            return self.renewed_tokens or {
                "access_token": mint(),
                "refresh_token": "rotated-refresh",
            }

        async def revoke(self, token):
            if self.refused:
                raise ValueError("provider private error")

    identity = Identity()
    store = LocalStore(tmp_path / "sessions")
    key = Fernet.generate_key()

    def app(*, search_engine=None, owner_reports=None, personal_state=None):
        reader = Reader(
            config,
            verifier,
            store,
            key,
            identity=identity,
            clock=lambda: clock[0],
            owner_reports=owner_reports,
            personal_state=personal_state,
        )
        return create_hosted_app(
            published[3], verifier, reader=reader, search_engine=search_engine
        )

    return app, identity, clock


def login(client):
    r = client.get("/reader/login", follow_redirects=False)
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == ["https://reader.example/reader/callback"]
    return client.get(
        "/reader/callback",
        params={
            "code": "synthetic-code",
            "state": q["state"][0],
            "iss": "https://issuer.example/",
        },
        follow_redirects=False,
    )


def test_sign_in_catalog_and_restart(reader_env):
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        entry = client.get("/reader/catalog")
        assert entry.status_code == 401
        assert '<script src="/reader/session.js"' not in entry.text
        r = login(client)
        assert r.status_code == 303
        cookie = r.headers["set-cookie"]
        for flag in ["__Host-reader=", "Secure", "HttpOnly", "SameSite=lax", "Path=/"]:
            assert flag in cookie
        assert "Domain=" not in cookie
        saved = client.cookies.get("__Host-reader")
        r = client.get("/reader/catalog")
        assert r.status_code == 200 and "Beans" in r.text
        assert '<script src="/reader/session.js"' in r.text
        assert "no-store" in r.headers["cache-control"]
        assert "default-src 'none'" in r.headers["content-security-policy"]
        assert "synthetic-refresh" not in r.text
    with TestClient(app(), base_url="https://reader.example") as restarted:
        restarted.cookies.set("__Host-reader", saved)
        assert "Beans" in restarted.get("/reader/catalog").text


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "stranger"},
        {"aud": "wrong"},
        {"iss": "https://wrong/"},
        {"scope": "other"},
        {"exp": 1},
    ],
)
def test_denied_identity_cannot_create_reader_session(reader_env, mint, claims):
    app, identity, _ = reader_env
    identity.tokens = {"access_token": mint(**claims)}
    with TestClient(app(), base_url="https://reader.example") as client:
        assert login(client).status_code == 401
        for path in ("/reader", "/reader/catalog", "/reader/session"):
            r = client.get(path)
            assert r.status_code == 401 and "Beans" not in r.text


def test_oauth_correlation_redirect_and_replay(reader_env):
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        assert (
            client.get("/reader/login?return=https://evil.example").status_code == 400
        )
        r = client.get("/reader/login", follow_redirects=False)
        q = parse_qs(urlsplit(r.headers["location"]).query)
        params = {
            "code": "synthetic-code",
            "state": q["state"][0],
            "iss": "https://issuer.example/",
        }
        assert (
            client.get(
                "/reader/callback", params={**params, "iss": "https://evil.example/"}
            ).status_code
            == 401
        )
        with TestClient(app(), base_url="https://reader.example") as other:
            assert other.get("/reader/callback", params=params).status_code == 401
        assert (
            client.get(
                "/reader/callback", params=params, follow_redirects=False
            ).status_code
            == 303
        )
        assert client.get("/reader/callback", params=params).status_code == 401


def test_logout_scopes_and_csrf_even_when_provider_refuses(reader_env):
    app, identity, _ = reader_env
    with (
        TestClient(app(), base_url="https://reader.example") as first,
        TestClient(app(), base_url="https://reader.example") as second,
    ):
        login(first)
        login(second)
        csrf = first.get("/reader/session").json()["csrf"]
        data = {"scope": "device", "csrf": csrf}
        assert first.post("/reader/logout", data=data).status_code == 403
        assert (
            first.post(
                "/reader/logout", data=data, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert (
            first.post(
                "/reader/logout",
                data={**data, "csrf": "bad"},
                headers={"Origin": "https://reader.example"},
            ).status_code
            == 403
        )
        identity.refused = True
        copied = first.cookies.get("__Host-reader")
        r = first.post(
            "/reader/logout",
            data=data,
            headers={"Origin": "https://reader.example"},
            follow_redirects=False,
        )
        assert r.status_code == 303 and r.headers["location"].startswith(
            "https://issuer.example/v2/logout?"
        )
        first.cookies.set("__Host-reader", copied)
        assert first.get("/reader/catalog").status_code == 401
        assert second.get("/reader/catalog").status_code == 200
        first.cookies.clear()
        login(first)
        csrf = first.get("/reader/session").json()["csrf"]
        assert (
            first.post(
                "/reader/logout",
                data={"scope": "all", "csrf": csrf},
                headers={"Origin": "https://reader.example"},
            ).status_code
            == 200
        )
        assert second.get("/reader/catalog").status_code == 401


@pytest.mark.parametrize("days", [7, 30])
def test_session_idle_and_absolute_limits(reader_env, days):
    app, _, clock = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        if days == 30:
            for _ in range(5):
                clock[0] += 5 * 86400
                assert client.get("/reader/catalog").status_code == 200
            clock[0] += 5 * 86400
        else:
            clock[0] += days * 86400
        assert client.get("/reader/catalog").status_code == 401


@pytest.mark.parametrize("refused", [False, True])
def test_renewal_and_refusal_via_public_session(reader_env, monkeypatch, mint, refused):
    from datetime import datetime

    app, identity, clock = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        clock[0] += 601

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(clock[0], UTC)

        monkeypatch.setattr("jwt.api_jwt.datetime", Later)
        identity.renewed_tokens = {
            "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
            "refresh_token": "rotated-refresh",
        }
        identity.refused = refused
        assert client.get("/reader/session").status_code == (401 if refused else 200)
        if not refused:
            assert client.get("/reader/catalog").status_code == 200


def test_hosted_reader_requires_complete_separate_storage_configuration(monkeypatch):
    from cookbook.hosted import reader_from_environment
    from cookbook.server import JWTVerifier

    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://reader.example/mcp",
        subjects=["owner"],
        public_key=b"synthetic",
    )
    monkeypatch.setenv("READER_ORIGIN", "https://reader.example")
    with pytest.raises(ValueError, match="incomplete reader"):
        reader_from_environment(verifier)


@pytest.mark.parametrize("valid_nonce", [True, False])
def test_confidential_exchange_pkce_and_oidc_nonce(
    published, keys, mint, tmp_path, monkeypatch, valid_nonce
):
    import base64
    import hashlib

    import httpx
    import jwt

    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="http://127.0.0.1:8765/mcp",
        subjects=["user-1"],
        public_key=keys[1],
    )
    config = ReaderConfig(
        "https://reader.example", "web-client", "synthetic-secret", oidc=True
    )
    authorization = {}

    def provider(request):
        body = parse_qs(request.content.decode())
        assert str(request.url) == "https://issuer.example/oauth/token"
        assert body["client_secret"] == ["synthetic-secret"]
        assert body["grant_type"] == ["authorization_code"]
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(body["code_verifier"][0].encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        assert authorization["code_challenge"] == [challenge]
        claims = {
            "iss": "https://issuer.example/",
            "aud": "web-client",
            "sub": "user-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "nonce": authorization["nonce"][0] if valid_nonce else "wrong",
        }
        return httpx.Response(
            200,
            json={
                "access_token": mint(),
                "id_token": jwt.encode(claims, keys[0], algorithm="RS256"),
                "refresh_token": "synthetic-refresh",
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "cookbook.reader.httpx.AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(provider), **kw),
    )
    reader = Reader(
        config, verifier, LocalStore(tmp_path / "sessions"), Fernet.generate_key()
    )
    with TestClient(
        create_app(published[4], verifier, reader=reader),
        base_url="https://reader.example",
    ) as client:
        r = client.get("/reader/login", follow_redirects=False)
        authorization.update(parse_qs(urlsplit(r.headers["location"]).query))
        r = client.get(
            "/reader/callback",
            params={
                "code": "synthetic-code",
                "state": authorization["state"][0],
                "iss": "https://issuer.example/",
            },
            follow_redirects=False,
        )
        assert r.status_code == (303 if valid_nonce else 401)
        assert client.get("/reader/catalog").status_code == (
            200 if valid_nonce else 401
        )


def test_passive_tabs_do_not_extend_idle_lifetime(reader_env):
    app, _, clock = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        for _ in range(6):
            clock[0] += 86400
            assert client.get("/reader/session").status_code == 200
        clock[0] += 86400
        assert client.get("/reader/session").status_code == 401


def test_session_storage_failure_is_redacted_and_never_serves_catalog(
    reader_env, monkeypatch
):
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)

        def failed(*args, **kwargs):
            raise OSError("synthetic-private-secret path")

        monkeypatch.setattr(LocalStore, "read_version", failed)
        r = client.get("/reader/catalog")
        assert r.status_code == 503
        assert "Beans" not in r.text and "synthetic-private-secret" not in r.text
        assert 'role="status"' in r.text and 'href="/reader/catalog"' in r.text
        assert "no-store" in r.headers["cache-control"]


def test_reader_cookie_does_not_authenticate_mcp_and_bearer_does_not_create_session(
    reader_env, mint
):
    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        assert (
            client.get(
                "/reader/catalog", headers={"Authorization": "Bearer " + mint()}
            ).status_code
            == 401
        )
        login(client)
        assert (
            client.post(
                "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            ).status_code
            == 401
        )


def test_catalog_uses_live_publications_paginates_and_escapes_source_markup(
    reader_env, published, tmp_path
):
    import sqlite3

    from conftest import fixture_build

    from cookbook.publication import publish
    from cookbook.storage import digest_file

    app, _, _ = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        manifest, inputs = fixture_build(tmp_path / "updated", count=22, repeats=1)
        with sqlite3.connect(inputs["runtime/index.sqlite"]) as db:
            db.execute(
                "update books set title=? where id='book-1'",
                ('<script src="https://evil.example/x">bad</script>',),
            )
        sha, size = digest_file(inputs["runtime/index.sqlite"])
        manifest = manifest.model_copy(
            update={
                "files": [
                    e.model_copy(update={"sha256": sha, "size": size})
                    if e.path == "runtime/index.sqlite"
                    else e
                    for e in manifest.files
                ]
            }
        )
        _, version = published[2].read_version("control/active.json")
        publish(
            published[2],
            manifest,
            inputs,
            expected_version=version,
            activate=published[3].activate,
        )
        r = client.get("/reader/catalog")
        assert r.status_code == 200 and "&lt;script" in r.text
        assert '<script src="https://evil.example' not in r.text
        from html.parser import HTMLParser

        class Links(HTMLParser):
            target = None

            def handle_starttag(self, tag, attrs):
                href = dict(attrs).get("href", "")
                if tag == "a" and href.startswith("/reader/catalog?"):
                    self.target = href

        links = Links()
        links.feed(r.text)
        assert links.target is not None
        assert client.get(links.target).status_code == 200
        assert "More books" not in client.get(links.target).text


@pytest.mark.parametrize(
    "renewed_claims",
    [
        {"sub": "stranger"},
        {"aud": "wrong"},
        {"iss": "https://wrong/"},
        {"scope": "other"},
        {"exp": 1},
    ],
)
def test_renewed_tokens_must_preserve_resource_authorization(
    reader_env, monkeypatch, mint, renewed_claims
):
    from datetime import UTC, datetime

    app, identity, clock = reader_env
    with TestClient(app(), base_url="https://reader.example") as client:
        login(client)
        clock[0] += 601

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(clock[0], UTC)

        monkeypatch.setattr("jwt.api_jwt.datetime", Later)
        identity.renewed_tokens = {
            "access_token": mint(
                **{"iat": int(clock[0]), "exp": int(clock[0]) + 600, **renewed_claims}
            )
        }
        assert client.get("/reader/session").status_code == 401
        assert client.get("/reader/catalog").status_code == 401


def test_hosted_configuration_preserves_library_and_report_authority(
    monkeypatch, keys, tmp_path
):
    from cookbook.hosted import reader_from_environment

    env = {
        "READER_ORIGIN": "https://reader.example",
        "READER_CLIENT_ID": "web-client",
        "READER_CLIENT_SECRET": "synthetic-secret",
        "READER_SESSION_KEY": Fernet.generate_key().decode(),
        "READER_S3_BUCKET": "sessions",
        "READER_AWS_ACCESS_KEY_ID": "session-key",
        "READER_AWS_SECRET_ACCESS_KEY": "synthetic-secret",
        "S3_BUCKET": "library",
        "AWS_ACCESS_KEY_ID": "read-only",
        "S3_ENDPOINT_URL": "https://storage.example",
        "REPORTS_S3_BUCKET": "reports",
        "REPORTS_AWS_ACCESS_KEY_ID": "report-key",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "cookbook.hosted.s3_store", lambda *args: LocalStore(tmp_path / "sessions")
    )
    verifier = JWTVerifier(
        issuer="https://issuer.example/",
        audience="https://reader.example/mcp",
        subjects=["user-1"],
        public_key=keys[1],
    )
    assert reader_from_environment(verifier) is not None
    for bucket in ("library", "reports"):
        monkeypatch.setenv("READER_S3_BUCKET", bucket)
        with pytest.raises(ValueError, match="separate"):
            reader_from_environment(verifier)
    monkeypatch.setenv("READER_S3_BUCKET", "sessions")
    monkeypatch.setenv("READER_ORIGIN", "https://evil.example")
    with pytest.raises(ValueError, match="same|share"):
        reader_from_environment(verifier)


@pytest.mark.parametrize("logout", [False, True])
def test_renewal_respects_other_device_activity_and_logout(
    reader_env, monkeypatch, mint, logout
):
    from datetime import UTC, datetime

    app, identity, clock = reader_env
    with (
        TestClient(app(), base_url="https://reader.example") as first,
        TestClient(app(), base_url="https://reader.example") as second,
    ):
        login(first)
        clock[0] += 601

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(clock[0], UTC)

        monkeypatch.setattr("jwt.api_jwt.datetime", Later)
        identity.tokens = {
            "access_token": mint(iat=int(clock[0]), exp=int(clock[0]) + 600),
            "refresh_token": "second-refresh",
        }
        login(second)
        identity.renewed_tokens = identity.tokens
        original = identity.renew
        csrf = second.get("/reader/session").json()["csrf"]

        async def renewal(token):
            if logout:
                assert (
                    second.post(
                        "/reader/logout",
                        data={"scope": "all", "csrf": csrf},
                        headers={"Origin": "https://reader.example"},
                    ).status_code
                    == 200
                )
            else:
                assert second.get("/reader/catalog").status_code == 200
            return await original(token)

        identity.renew = renewal
        assert first.get("/reader/catalog").status_code == (401 if logout else 200)
        assert second.get("/reader/catalog").status_code == (401 if logout else 200)
