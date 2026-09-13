"""Real HTTP S3 adapter exercise using only generated synthetic data."""

import socket
import subprocess
import time
import boto3
from botocore.config import Config
import httpx
import pytest
from cookbook.publication import publish, restore
from cookbook.storage import S3Store, Conflict, IntegrityError, digest_file
from conftest import fixture_build


def test_s3_conditional_upload_readback_restore(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        ["moto_server", "-H", "127.0.0.1", "-p", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url, timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("local synthetic S3 service failed to start")
        client = boto3.client(
            "s3",
            endpoint_url=url,
            aws_access_key_id="synthetic",
            aws_secret_access_key="synthetic",
            region_name="us-east-1",
            config=Config(retries={"max_attempts": 1}),
        )
        client.create_bucket(Bucket="synthetic-fixture")
        store = S3Store(client, "synthetic-fixture")
        m, inputs = fixture_build(tmp_path / "build")
        r = publish(
            store,
            m,
            inputs,
            expected_version=None,
            activate=lambda p: p["publication_id"],
        )
        restore(store, r, tmp_path / "restore")
        for e in m.files:
            assert digest_file(tmp_path / "restore" / e.path) == (e.sha256, e.size)
        raw, version = store.read_version("control/active.json")
        with pytest.raises(Conflict):
            store.put_bytes("control/active.json", b"bad")
        assert store.read("control/active.json") == raw
        with pytest.raises(Conflict):
            store.put_bytes("control/active.json", b"bad", expected='"stale"')
        client.put_object(Bucket=store.bucket, Key=m.files[0].key, Body=b"corrupted")
        with pytest.raises(IntegrityError):
            publish(
                store,
                m,
                inputs,
                expected_version=version,
                activate=lambda p: p["publication_id"],
            )
        assert store.read("control/active.json") == raw
    finally:
        proc.terminate()
        proc.wait(timeout=10)
