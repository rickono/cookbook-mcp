"""Disposable PostgreSQL for serving-only trials; private socket, no TCP listener."""

import contextlib
import shlex
import subprocess
import tempfile
from pathlib import Path

from psycopg.conninfo import make_conninfo


@contextlib.contextmanager
def local_postgres(binary_dir):
    binary_dir = Path(binary_dir)
    with tempfile.TemporaryDirectory(prefix="reader-pg-") as directory:
        root = Path(directory)
        data, socket = root / "data", root / "socket"
        socket.mkdir(mode=0o700)
        subprocess.run(
            [
                str(binary_dir / "initdb"),
                "-D",
                str(data),
                "-U",
                "reader_trial",
                "-A",
                "trust",
                "--no-locale",
                "--encoding=UTF8",
            ],
            check=True,
            capture_output=True,
        )
        control = [str(binary_dir / "pg_ctl"), "-D", str(data), "-w"]
        options = shlex.join(
            [
                "-k",
                str(socket),
                "-p",
                "55432",
                "-c",
                "listen_addresses=",
                "-c",
                "fsync=on",
                "-c",
                "synchronous_commit=on",
                "-c",
                "reader.local_trial=on",
            ]
        )
        subprocess.run(
            [*control, "-l", str(root / "postgres.log"), "-o", options, "start"],
            check=True,
            capture_output=True,
        )
        try:
            yield make_conninfo(
                host=str(socket), port=55432, dbname="postgres", user="reader_trial"
            )
        finally:
            subprocess.run(
                [*control, "-m", "immediate", "stop"], check=True, capture_output=True
            )
