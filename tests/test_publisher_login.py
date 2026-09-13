import asyncio
import base64
import hashlib
import socket
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from cookbook.publisher_login import (
    CALLBACK,
    LoginConfig,
    LoginError,
    LoginToken,
    _browser_login,
)
from cookbook.server import JWTVerifier


@pytest.fixture
def config():
    return LoginConfig(
        "https://issuer.example/",
        "https://service.example",
        "publisher",
        "user-1",
        "https://issuer.example/.well-known/jwks.json",
    )


def run_flow(config, keys, token, *, callbacks=None, status=200, extra=None):
    seen = {}

    async def run():
        loop = asyncio.get_running_loop()

        async def visit(url):
            query = parse_qs(urlsplit(url).query)
            seen["authorize"] = query
            good = {
                "state": query["state"][0],
                "iss": config.issuer,
                "code": "private-code",
            }
            async with httpx.AsyncClient(trust_env=False) as browser:
                for params, host in callbacks(good) if callbacks else []:
                    response = await browser.get(
                        CALLBACK + "?" + urlencode(params, doseq=True),
                        headers={"Host": host},
                    )
                    assert response.status_code == 400
                    assert "private-code" not in response.text
                response = await browser.get(CALLBACK + "?" + urlencode(good))
                assert response.status_code == 200
                assert response.headers["cache-control"] == "no-store"

        def open_browser(url):
            seen["visit"] = asyncio.run_coroutine_threadsafe(visit(url), loop)
            return True

        def exchange(request):
            assert str(request.url) == config.issuer + "oauth/token"
            form = parse_qs(request.content.decode())
            seen["exchange"] = form
            assert form["code"] == ["private-code"]
            expected = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(form["code_verifier"][0].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            assert seen["authorize"]["code_challenge"] == [expected]
            assert "client_secret" not in form
            return httpx.Response(
                status,
                json={"token_type": "Bearer", "access_token": token, **(extra or {})},
                headers={"Location": "https://elsewhere.example/"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
            try:
                return await _browser_login(
                    config,
                    timeout=5,
                    open_browser=open_browser,
                    client=client,
                    verifier=JWTVerifier(
                        issuer=config.issuer,
                        audience=config.audience,
                        subjects=[config.subject],
                        public_key=keys[1],
                    ),
                )
            finally:
                if "visit" in seen:
                    await asyncio.wrap_future(seen["visit"])

    return asyncio.run(run()), seen


def test_real_loopback_pkce_rejects_uncorrelated_requests(config, keys, mint, capsys):
    def bad_requests(good):
        return [
            ({**good, "state": "wrong"}, "127.0.0.1:8766"),
            ({**good, "state": [good["state"], good["state"]]}, "127.0.0.1:8766"),
            ({**good, "iss": "https://other.example/"}, "127.0.0.1:8766"),
            (good, "attacker.example"),
            ({**good, "code": ""}, "127.0.0.1:8766"),
        ]

    raw = mint(aud=config.audience, azp=config.client_id)
    token, seen = run_flow(config, keys, raw, callbacks=bad_requests)
    assert token.bearer() == raw
    assert seen["authorize"]["scope"] == ["library:read"]
    assert seen["authorize"]["connection"] == ["google-oauth2"]
    assert seen["authorize"]["code_challenge_method"] == ["S256"]
    assert "code_verifier" not in seen["authorize"]
    assert raw not in repr(token)
    assert raw not in capsys.readouterr().out
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 8766))


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "stranger"},
        {"aud": "other"},
        {"azp": "other"},
        {"scope": "library:read admin"},
        {"scope": ""},
        {"exp": 1},
    ],
)
def test_reject_wrong_identity_resource_client_scope_or_expiry(
    config, keys, mint, claims
):
    raw = mint(**{"aud": config.audience, "azp": config.client_id, **claims})
    with pytest.raises(LoginError, match="login_token_invalid"):
        run_flow(config, keys, raw)


@pytest.mark.parametrize(
    "status,extra",
    [
        (302, {}),
        (400, {}),
        (200, {"refresh_token": "forbidden"}),
        (200, {"token_type": "MAC"}),
    ],
)
def test_exchange_redirect_errors_and_unexpected_tokens(
    config, keys, mint, status, extra
):
    with pytest.raises(LoginError):
        run_flow(
            config,
            keys,
            mint(aud=config.audience, azp=config.client_id),
            status=status,
            extra=extra,
        )


def test_unavailable_port_timeout_and_browser_failure(config):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 8766))
        listener.listen()
        with pytest.raises(LoginError, match="port_unavailable"):
            asyncio.run(
                _browser_login(
                    config,
                    open_browser=lambda _: pytest.fail(
                        "browser opened with occupied port"
                    ),
                )
            )
    with pytest.raises(LoginError, match="login_timeout"):
        asyncio.run(_browser_login(config, timeout=0.05, open_browser=lambda _: True))
    with pytest.raises(LoginError, match="browser_unavailable"):
        asyncio.run(_browser_login(config, open_browser=lambda _: False))
    with pytest.raises(LoginError, match="login_expired"):
        LoginToken("secret", int(time.time()) - 1).bearer()


def test_cli_browser_login_pending_and_retry(tmp_path, monkeypatch, capsys, config):
    import json
    import sys
    from cookbook import cli, hosted, publisher_login

    pointer = {"publication_id": "a" * 32, "manifest_sha256": "b" * 64}
    path = tmp_path / "pointer.json"
    path.write_text(json.dumps(pointer))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cookbook",
            "wait-active",
            "--pointer",
            str(path),
            "--readiness-url",
            config.audience + "/readyz",
            "--browser-login",
        ],
    )
    monkeypatch.setenv("COOKBOOK_AUDIENCE", config.audience)
    monkeypatch.setattr(publisher_login.LoginConfig, "from_environment", lambda: config)

    def denied(_):
        raise LoginError("login_denied")

    monkeypatch.setattr(publisher_login, "browser_login", denied)
    with pytest.raises(SystemExit) as error:
        cli._main()
    assert error.value.code == 4
    monkeypatch.setattr(
        publisher_login,
        "browser_login",
        lambda _: LoginToken("memory-token", int(time.time()) + 100),
    )

    def acknowledge(actual, url, provider):
        assert provider() == "memory-token"
        assert actual == pointer
        return actual["publication_id"]

    monkeypatch.setattr(hosted, "wait_for_activation", acknowledge)
    cli._main()
    output = capsys.readouterr()
    assert '"status": "active"' in output.out
    assert "memory-token" not in output.out + output.err
    assert len(list(tmp_path.iterdir())) == 1
