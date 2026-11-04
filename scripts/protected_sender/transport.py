"""One bounded HTTPS transaction, isolated in a killable child process."""

import http.client
import json
import os
import ssl
import subprocess
import sys
import zlib
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from protocol import (
    MAX_BYTES,
    bounded_read,
    credential,
    digest,
    reject_ambient_overrides,
)


def read_response(response):
    length = response.getheader("Content-Length")
    if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
        raise ValueError("Response length exceeds bound")
    encoding = response.getheader("Content-Encoding", "identity").lower()
    if encoding not in {"identity", "gzip"}:
        raise ValueError("Unsupported content encoding")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    wire = 0
    result = bytearray()
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        wire += len(chunk)
        if wire > MAX_BYTES:
            raise ValueError("Received response exceeds bound")
        if decoder:
            chunk = decoder.decompress(chunk, MAX_BYTES - len(result) + 1)
            if decoder.unconsumed_tail or decoder.unused_data:
                raise ValueError("Expanded/multiple gzip response refused")
        result.extend(chunk)
        if len(result) > MAX_BYTES:
            raise ValueError("Decoded response exceeds bound")
    if decoder and not decoder.eof:
        raise ValueError("Incomplete gzip response")
    if length is not None and wire != int(length):
        raise ValueError("Incomplete response")
    return bytes(result)


def exchange(endpoint, body, secret, context):
    """No redirect, proxy, retry, endpoint override or TLS verification bypass."""
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError("Pinned HTTPS endpoint required")
    if len(body) > MAX_BYTES:
        raise ValueError("Request exceeds bound")
    with closing(
        http.client.HTTPSConnection(
            parsed.hostname, parsed.port or 443, timeout=240, context=context
        )
    ) as connection:
        connection.request(
            "POST",
            parsed.path,
            body=body,
            headers={
                "Authorization": "Bearer " + secret,
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Provider HTTP status rejected")
        return read_response(response)


def transaction(directory, endpoint, *, request_digest, seconds=240, synthetic=False):
    """Parent-enforced absolute deadline includes DNS, TLS, write, and read.

    The parent has already durably reserved attempts/charges. Every failure
    leaves that reservation uncertain. No exception output includes provider
    response text, credential bytes, or request content.
    """
    if not 0 < seconds <= 240:
        raise ValueError("Invalid absolute transaction deadline")
    if not synthetic:
        raise PermissionError(
            "Live dispatch disabled pending account and workload admission"
        )
    require_fixture_endpoint(endpoint)
    directory = Path(directory)
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                str(directory),
                endpoint,
                request_digest,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=seconds,
            check=False,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(
            "Absolute transaction deadline exceeded; liability retained"
        ) from None
    if result.returncode:
        raise ValueError("Transaction failed; liability retained")
    return bounded_read(directory / "response.json")


def require_fixture_endpoint(endpoint):
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "127.0.0.1"
        or parsed.path != "/fixture"
        or not parsed.port
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise PermissionError("Only loopback synthetic endpoint admitted")


def main():
    # This subprocess is exclusively a source-free fixture transport. Actual
    # provider sending cannot be enabled by passing a boolean or environment var.
    reject_ambient_overrides()
    directory = Path(sys.argv[1])
    endpoint = sys.argv[2]
    require_fixture_endpoint(endpoint)
    body = bounded_read(directory / "request.json")
    if digest(body) != sys.argv[3]:
        raise ValueError("Request changed after admission")
    context = ssl.create_default_context(cafile=str(directory / "ca.pem"))
    raw = exchange(
        endpoint,
        body,
        credential(directory / "secret"),
        context,
    )
    # Preserve exact provider bytes separately; metadata wrappers never enlarge it.
    with (directory / "response.json").open("xb") as stream:
        stream.write(raw)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("Response must be a JSON object")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, http.client.HTTPException, zlib.error):
        raise SystemExit(2) from None
