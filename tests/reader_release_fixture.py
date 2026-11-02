"""Synthetic assembled production app for local HTTPS browser verification only.

No new routes, authentication bypass, ingestion, model or rendering subprocess.
Run with uvicorn --factory and a temporary local TLS certificate. The synthetic
issuer is this origin: its /authorize 404 intentionally exposes the OAuth state
in the address bar; navigate to /reader/callback with that state, code=synthetic,
and iss=<origin>/ to simulate the external provider response.
"""

import os
import tempfile
import time
from pathlib import Path

import jwt
from conftest import fixture_build
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa

from cookbook.hosted import create_hosted_app
from cookbook.owner_reports import OwnerReports
from cookbook.publication import Runtime, publish
from cookbook.reader import Reader, ReaderConfig
from cookbook.reader_personal import PersonalState
from cookbook.server import JWTVerifier
from cookbook.storage import LocalStore


def app():
    origin = os.environ.get("SYNTHETIC_READER_ORIGIN", "https://127.0.0.1:9443")
    root = Path(tempfile.mkdtemp(prefix="reader-release-"))
    manifest, inputs = fixture_build(root / "build", section_count=3)
    store = LocalStore(root / "library")
    runtime = Runtime(store, root / "runtime")
    publish(store, manifest, inputs, expected_version=None, activate=runtime.activate)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = JWTVerifier(
        issuer=origin + "/",
        audience=origin,
        subjects=["synthetic-owner"],
        public_key=private.public_key(),
    )

    class Identity:
        async def exchange(self, code, verifier, nonce):
            if code != "synthetic":
                raise ValueError("synthetic code required")
            return await self.renew(None)

        async def renew(self, token):
            now = int(time.time())
            return {
                "access_token": jwt.encode(
                    {
                        "iss": origin + "/",
                        "aud": origin,
                        "sub": "synthetic-owner",
                        "iat": now,
                        "exp": now + 600,
                        "scope": "library:read",
                    },
                    private,
                    algorithm="RS256",
                ),
                "refresh_token": "synthetic",
            }

        async def revoke(self, token):
            pass

    reader = Reader(
        ReaderConfig(origin=origin, client_id="synthetic", client_secret="synthetic"),
        verifier,
        LocalStore(root / "sessions"),
        Fernet.generate_key(),
        identity=Identity(),
        owner_reports=OwnerReports(LocalStore(root / "reports")),
        personal_state=PersonalState(LocalStore(root / "personal")),
    )
    return create_hosted_app(runtime, verifier, reader=reader)
