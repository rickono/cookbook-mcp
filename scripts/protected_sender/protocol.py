"""Sealed, purpose-bound request admission. No source parsers or image decoding."""

import hashlib
import json
import os
import stat
from pathlib import Path

MAX_BYTES = 16 * 1024**2
ENDPOINTS = {
    "decisions": "https://api.openai.com/v1/decisions",
    "responses": "https://api.openai.com/v1/responses",
    "jev": "https://api.typesafe.ai/v1/systemone",
}
PURPOSES = {"screening", "reference", "review", "audit"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded_read(path, cap=MAX_BYTES):
    if Path(path).is_symlink() or not Path(path).is_file():
        raise ValueError("Regular non-symlink file required")
    with Path(path).open("rb") as stream:
        raw = stream.read(cap + 1)
    if len(raw) > cap:
        raise ValueError("File exceeds admission bound")
    return raw


def reject_ambient_overrides():
    for key in os.environ:
        name = key.upper()
        if name.endswith("_PROXY") or name in {
            "ALL_PROXY",
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
            "TYPESAFE_BASE_URL",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
        }:
            raise ValueError("Ambient endpoint/proxy/TLS override refused")


def credential(path):
    info = Path(path).lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_mode & 0o077
        or info.st_uid != os.getuid()
    ):
        raise ValueError("Credential must be an owner-only regular file")
    raw = bounded_read(path, 4096).strip()
    if not raw or any(c < 33 or c > 126 for c in raw):
        raise ValueError("Invalid credential bytes")
    return raw.decode("ascii")


def load_packet(directory, expected_seal):
    directory = Path(directory)
    raw_manifest = bounded_read(directory / "manifest.json", 128 * 1024)
    if digest(raw_manifest) != expected_seal:
        raise ValueError("Frozen manifest identity changed")
    packet = json.loads(raw_manifest)
    required = {
        "version",
        "provider",
        "endpoint",
        "model",
        "purpose",
        "source",
        "candidate",
        "corrections",
        "scope",
        "complete",
        "request_sha256",
        "assets",
        "request_id",
        "maximum_cost",
        "input_tokens",
        "output_tokens",
        "configuration",
        "questions_version",
    }
    if set(packet) != required or packet["version"] != 1:
        raise ValueError("Unsupported packet schema")
    if packet["endpoint"] != ENDPOINTS.get(packet["provider"]):
        raise ValueError("Endpoint not pinned to provider")
    if packet["purpose"] not in PURPOSES or type(packet["complete"]) is not bool:
        raise ValueError("Invalid purpose/completeness")
    if packet["purpose"] in {"review", "audit"} and not packet["complete"]:
        raise ValueError("Review requires complete declared evidence")
    for key in ("source", "candidate", "corrections", "request_sha256"):
        value = packet[key]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("Invalid frozen identity")
    for key in ("model", "request_id", "configuration", "questions_version"):
        if not isinstance(packet[key], str) or not packet[key]:
            raise ValueError("Missing model/configuration identity")
    for key, cap in [("input_tokens", 20000), ("output_tokens", 25000)]:
        if type(packet[key]) is not int or not 0 < packet[key] <= cap:
            raise ValueError("Token envelope exceeded")
    if type(packet["maximum_cost"]) is not int or packet["maximum_cost"] <= 0:
        raise ValueError("Positive worst-case charge required")
    scopes = {}
    for page in packet["scope"]:
        if (
            set(page) != {"page", "regions"}
            or type(page["page"]) is not int
            or page["page"] <= 0
        ):
            raise ValueError("Invalid physical page scope")
        prefix = packet["source"] + "/" + str(page["page"])
        if prefix in scopes:
            raise ValueError("Duplicate physical page")
        scopes[prefix] = 6
        for region in page["regions"]:
            if (
                not isinstance(region, str)
                or not region
                or "/" in region
                or prefix + "/" + region in scopes
            ):
                raise ValueError("Invalid canonical region")
            scopes[prefix + "/" + region] = 3
    if not scopes or not packet["assets"]:
        raise ValueError("Missing evidence scope/assets")
    for asset in packet["assets"]:
        if set(asset) != {"name", "sha256", "width", "height", "transform", "page"}:
            raise ValueError("Invalid asset metadata")
        name = asset["name"]
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or name in {"manifest.json", "request.json", ".", ".."}
        ):
            raise ValueError("Invalid asset path")
        if packet["source"] + "/" + str(asset["page"]) not in scopes:
            raise ValueError("Unaccounted evidence page")
        edge = 1568 if packet["provider"] == "jev" else 2500
        minimum = 280 if packet["provider"] == "jev" else 1
        if any(
            type(asset[k]) is not int or not minimum <= asset[k] <= edge
            for k in ("width", "height")
        ):
            raise ValueError("Image dimensions exceed adapter bounds")
        if not isinstance(asset["transform"], list) or len(asset["transform"]) != 6:
            raise ValueError("Missing crop/page transform")
        if digest(bounded_read(directory / name)) != asset["sha256"]:
            raise ValueError("Evidence asset changed")
    body = bounded_read(directory / "request.json")
    if digest(body) != packet["request_sha256"]:
        raise ValueError("Serialized request changed")
    payload = json.loads(body)
    if payload.get("model") != packet["model"]:
        raise ValueError("Request model differs from frozen model")
    # Image-token estimates, evidence inclusion, and provider schemas still need
    # independently verified adapters before live admission can be enabled.
    return packet, body, scopes
