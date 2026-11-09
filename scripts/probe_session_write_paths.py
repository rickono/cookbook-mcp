"""Opt-in synthetic hosted write-path diagnosis. Never accesses owner records."""

import argparse
import base64
import hashlib
import json
import os
import secrets
import statistics
import sys
import time


def run(transport=False, max_update_ms=None):
    import boto3
    import botocore
    import botocore.handlers
    import httpx
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.config import Config
    from botocore.credentials import Credentials
    from cryptography.fernet import Fernet

    from cookbook.hosted import s3_store
    from cookbook.storage import S3Store

    endpoint = os.environ.get("READER_S3_ENDPOINT_URL") or os.environ["S3_ENDPOINT_URL"]
    bucket = os.environ["READER_S3_BUCKET"]
    access = os.environ["READER_AWS_ACCESS_KEY_ID"]
    secret = os.environ["READER_AWS_SECRET_ACCESS_KEY"]
    load_before = os.getloadavg()
    default = s3_store(endpoint, bucket, access, secret)
    header = S3Store(
        boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name=default.client.meta.region_name,
            config=default.client.meta.config.merge(
                Config(request_checksum_calculation="when_required")
            ),
        ),
        bucket,
    )
    cipher = Fernet(Fernet.generate_key())
    if transport:
        header.client.meta.events.unregister(
            "before-call.s3", botocore.handlers.add_expect_header
        )
    direct = httpx.Client(timeout=20)
    clients = (
        {
            "default_conditional": default,
            "header_without_expect": header,
            "direct_signed_http": default,
        }
        if transport
        else {
            "default_conditional": default,
            "header_conditional": header,
            "default_unconditional": default,
            "default_create": default,
        }
    )
    keys = {name: "research/session-134/" + secrets.token_hex(24) for name in clients}
    created = set(keys.values())
    versions = {}
    rows = {name: [] for name in clients}
    headers = []
    metadata = []
    connections = []

    def before_send(request, **kwargs):
        h = {k.lower(): v for k, v in request.headers.items()}

        def contains(key, value):
            raw = h.get(key, b"")
            return value in (raw.decode() if isinstance(raw, bytes) else str(raw))

        headers.append(
            {
                "chunked": contains("transfer-encoding", "chunked"),
                "aws_chunked": contains("content-encoding", "aws-chunked"),
                "streaming_sha": contains("x-amz-content-sha256", "STREAMING"),
                "checksum_sha256": "x-amz-checksum-sha256" in h,
                "checksum_crc32": "x-amz-checksum-crc32" in h,
                "content_length": "content-length" in h,
            }
        )

    def after_call(parsed, **kwargs):
        meta = parsed.get("ResponseMetadata", {})
        metadata.append(
            {
                "status": meta.get("HTTPStatusCode"),
                "retries": meta.get("RetryAttempts", 0),
            }
        )

    for store in (default, header):
        store.client.meta.events.register("before-send.s3.PutObject", before_send)
        store.client.meta.events.register("after-call.s3.PutObject", after_call)

    from botocore.awsrequest import AWSHTTPSConnection

    original_connect = AWSHTTPSConnection.connect

    def connect(self):
        start = time.perf_counter()
        try:
            return original_connect(self)
        finally:
            connections.append((time.perf_counter() - start) * 1000)

    AWSHTTPSConnection.connect = connect

    def write(name, data, *, expected_status=200):
        store, key = clients[name], keys[name]
        if name == "direct_signed_http":
            request = AWSRequest(
                method="PUT",
                url=endpoint.rstrip("/") + "/" + bucket + "/" + key,
                data=data,
                headers={
                    "If-Match": versions[name],
                    "x-amz-content-sha256": hashlib.sha256(data).hexdigest(),
                    "x-amz-checksum-sha256": base64.b64encode(
                        hashlib.sha256(data).digest()
                    ).decode(),
                },
            )
            SigV4Auth(
                Credentials(access, secret), "s3", default.client.meta.region_name
            ).add_auth(request)
            response = direct.put(
                request.url, content=data, headers=dict(request.headers)
            )
            metadata.append({"status": response.status_code, "retries": 0})
            headers.append(
                {
                    "chunked": False,
                    "aws_chunked": False,
                    "streaming_sha": False,
                    "checksum_sha256": True,
                    "checksum_crc32": False,
                    "content_length": True,
                }
            )
            if response.status_code != expected_status:
                from xml.etree import ElementTree

                code = ElementTree.fromstring(response.content).findtext("Code")
                allowed = {
                    "SignatureDoesNotMatch",
                    "AccessDenied",
                    "InvalidArgument",
                    "BadDigest",
                    "InvalidRequest",
                    "NotImplemented",
                }
                print(
                    json.dumps(
                        {
                            "direct_status": response.status_code,
                            "error_code": code if code in allowed else "other",
                        }
                    )
                )
                raise RuntimeError("Direct request rejected")
            return response.headers.get("etag")
        if name in {"header_without_expect", "header_conditional"}:
            result = store.client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                IfMatch=versions[name],
                ChecksumSHA256=base64.b64encode(hashlib.sha256(data).digest()).decode(),
            )
            return result["ETag"]
        if name == "default_unconditional":
            return store.client.put_object(Bucket=bucket, Key=key, Body=data)["ETag"]
        return store.put_bytes(key, data, expected=versions.get(name))

    cleanup = 0
    try:
        for name, store in clients.items():
            data = cipher.encrypt(b"synthetic warmup")
            versions[name] = store.put_bytes(keys[name], data, expected=None)
            assert store.read_version(keys[name])[0] == data
            if name == "direct_signed_http":
                versions[name] = write(name, cipher.encrypt(b"direct pool warmup"))
        for lap in range(5):
            # Rotate starting order to distribute time drift across candidates.
            names = list(clients)
            names = names[lap % len(names) :] + names[: lap % len(names)]
            for name in names:
                store = clients[name]
                if name == "default_create":
                    keys[name] = "research/session-134/" + secrets.token_hex(24)
                    created.add(keys[name])
                    versions[name] = None
                data = cipher.encrypt(
                    json.dumps({"synthetic": True, "lap": lap}).encode()
                )
                old = versions[name]
                headers.clear()
                metadata.clear()
                connections.clear()
                wall, cpu = time.perf_counter(), time.process_time()
                versions[name] = write(name, data)
                measurement = {
                    "wall_ms": (time.perf_counter() - wall) * 1000,
                    "cpu_ms": (time.process_time() - cpu) * 1000,
                    "connect_calls": len(connections),
                    "connect_ms": sum(connections),
                    "sdk_retries": sum(m["retries"] for m in metadata),
                    "status": metadata[-1]["status"],
                    "headers": headers[-1],
                }
                assert measurement["status"] == 200
                assert store.read_version(keys[name]) == (data, versions[name])
                if name in {"header_without_expect", "header_conditional"}:
                    try:
                        store.client.put_object(
                            Bucket=bucket,
                            Key=keys[name],
                            Body=b"synthetic stale",
                            IfMatch=old,
                            ChecksumSHA256=base64.b64encode(
                                hashlib.sha256(b"synthetic stale").digest()
                            ).decode(),
                        )
                    except store.client.exceptions.ClientError as error:
                        assert (
                            error.response["ResponseMetadata"]["HTTPStatusCode"] == 412
                        )
                    else:
                        raise AssertionError("stale write accepted")
                    assert store.read_version(keys[name]) == (data, versions[name])
                if name == "direct_signed_http":
                    current = versions[name]
                    versions[name] = old
                    write(name, b"synthetic stale", expected_status=412)
                    versions[name] = current
                    assert store.read_version(keys[name]) == (data, current)
                rows[name].append(measurement)
    finally:
        AWSHTTPSConnection.connect = original_connect
        for key in created:
            try:
                default.delete(key)
                assert default.read_version(key) == (None, None)
            except Exception:  # noqa: BLE001 - private provider errors stay off stdout
                cleanup += 1
        default.client.close()
        header.client.close()
        direct.close()
        if sys.exc_info()[0] is not None:
            print(
                json.dumps(
                    {
                        "failed_probe_cleanup_failures": cleanup,
                        "objects_deleted": len(created),
                    }
                )
            )

    def dist(values):
        return {
            "median": round(statistics.median(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    result = {
        "version": botocore.__version__,
        "cpu_count": os.cpu_count(),
        "load_before": load_before,
        "load_after": os.getloadavg(),
        "cleanup_failures": cleanup,
        "objects_deleted": len(created),
        "results": {
            name: {
                "samples": len(values),
                "headers": values[0]["headers"],
                **{
                    k: dist([r[k] for r in values])
                    for k in (
                        "wall_ms",
                        "cpu_ms",
                        "connect_calls",
                        "connect_ms",
                        "sdk_retries",
                    )
                },
            }
            for name, values in rows.items()
        },
    }
    print(json.dumps(result, sort_keys=True))
    assert cleanup == 0
    if (
        max_update_ms is not None
        and result["results"]["default_conditional"]["wall_ms"]["median"]
        >= max_update_ms
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-synthetic-writes", required=True, action="store_true")
    parser.add_argument("--transport-comparison", action="store_true")
    parser.add_argument("--max-update-ms", type=float)
    args = parser.parse_args()
    if args.max_update_ms is not None and not 0 < args.max_update_ms < float("inf"):
        parser.error("--max-update-ms must be positive and finite")
    try:
        run(transport=args.transport_comparison, max_update_ms=args.max_update_ms)
    except Exception:  # noqa: BLE001 - suppress private provider error details
        raise SystemExit(
            "Write-path probe failed; private details suppressed"
        ) from None
