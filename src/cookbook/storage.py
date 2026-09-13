"""Small streaming object-store seam. Local backend is private, not an HTTP server."""

from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import BinaryIO

CHUNK = 1024 * 1024


class IntegrityError(Exception):
    pass


class Conflict(Exception):
    pass


def safe_key(key: str) -> str:
    if (
        not key
        or key.startswith("/")
        or "\\" in key
        or any(p in ("", ".", "..") for p in key.split("/"))
    ):
        raise IntegrityError("invalid object key")
    return key


def digest_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


@contextlib.contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+b") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class LocalStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, key):
        p = self.root / safe_key(key)
        if not p.resolve().is_relative_to(self.root):
            raise IntegrityError("unsafe store path")
        return p

    def open(self, key) -> BinaryIO:
        return self.path(key).open("rb")

    def read(self, key):
        return self.path(key).read_bytes()

    def exists(self, key):
        return self.path(key).is_file()

    def put_file(self, key, path):
        dst = self.path(key)
        dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # A separate inode prevents subsequent mutations of build inputs corrupting stored objects.
        fd, tmp = tempfile.mkstemp(dir=dst.parent)
        try:
            with os.fdopen(fd, "wb") as out, Path(path).open("rb") as src:
                for chunk in iter(lambda: src.read(CHUNK), b""):
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            try:
                os.link(tmp, dst)
            except FileExistsError:
                pass
        finally:
            Path(tmp).unlink(missing_ok=True)

    def put_bytes(self, key, data, expected=None):
        with file_lock(self.root / ".control.lock"):
            dst = self.path(key)
            current = (
                hashlib.sha256(dst.read_bytes()).hexdigest() if dst.exists() else None
            )
            if current != expected:
                raise Conflict("conditional write conflict")
            atomic_write(dst, data)
        return hashlib.sha256(data).hexdigest()

    def read_version(self, key):
        try:
            data = self.read(key)
            return data, hashlib.sha256(data).hexdigest()
        except FileNotFoundError:
            return None, None

    def list(self, prefix):
        p = self.path(prefix)
        return (
            sorted(str(x.relative_to(self.root)) for x in p.rglob("*") if x.is_file())
            if p.exists()
            else []
        )

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)


class S3Store:
    """Endpoint/bucket/credentials supplied by caller. No provider-specific core behavior."""

    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def open(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=safe_key(key))["Body"]

    def read(self, key):
        with self.open(key) as f:
            return f.read()

    def exists(self, key):
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=safe_key(key))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def put_file(self, key, path):
        from botocore.exceptions import ClientError

        # Single PUT POC; fail explicitly instead of unsafe unconditional multipart overwrites.
        if Path(path).stat().st_size > 5_000_000_000:
            raise IntegrityError("multipart validation required")
        try:
            with Path(path).open("rb") as f:
                self.client.put_object(
                    Bucket=self.bucket, Key=safe_key(key), Body=f, IfNoneMatch="*"
                )
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("PreconditionFailed", "412"):
                raise

    def put_bytes(self, key, data, expected=None):
        from botocore.exceptions import ClientError

        try:
            r = self.client.put_object(
                Bucket=self.bucket,
                Key=safe_key(key),
                Body=data,
                **({"IfMatch": expected} if expected else {"IfNoneMatch": "*"}),
            )
            return r["ETag"]
        except ClientError as e:
            if e.response["Error"]["Code"] in (
                "PreconditionFailed",
                "412",
                "ConditionalRequestConflict",
                "409",
            ):
                raise Conflict("conditional write conflict") from None
            raise

    def read_version(self, key):
        from botocore.exceptions import ClientError

        try:
            r = self.client.get_object(Bucket=self.bucket, Key=safe_key(key))
            with r["Body"] as f:
                return f.read(), r["ETag"]
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None, None
            raise

    def list(self, prefix):
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=safe_key(prefix) + "/"
        )
        return [o["Key"] for page in pages for o in page.get("Contents", [])]

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=safe_key(key))


def verify(store, key: str, sha256: str, size: int, destination: Path | None = None):
    h = hashlib.sha256()
    total = 0
    with contextlib.ExitStack() as stack:
        src = stack.enter_context(store.open(key))
        out = stack.enter_context(destination.open("wb")) if destination else None
        for chunk in iter(lambda: src.read(CHUNK), b""):
            total += len(chunk)
            if total > size:
                raise IntegrityError("object length mismatch")
            h.update(chunk)
            if out:
                out.write(chunk)
        if total != size or h.hexdigest() != sha256:
            raise IntegrityError("object checksum mismatch")
