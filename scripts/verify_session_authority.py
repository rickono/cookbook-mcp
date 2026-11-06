"""Verify the research SQL protocol against a disposable local PostgreSQL cluster.

Uses installed PostgreSQL binaries, a private Unix socket and synthetic rows.
It never connects to an existing database, R2, a provider, or application config.
This is a protocol proof, not application verification or a performance benchmark.
"""

import argparse
import os
import selectors
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


def run(binary_dir):
    with tempfile.TemporaryDirectory(prefix="session-authority-") as temp:
        root = Path(temp)
        data, socket = root / "data", root / "socket"
        socket.mkdir(mode=0o700)
        subprocess.run(
            [
                str(binary_dir / "initdb"),
                "-D",
                str(data),
                "-U",
                "session_research",
                "-A",
                "trust",
                "--no-locale",
            ],
            check=True,
            capture_output=True,
        )
        pg_ctl = [str(binary_dir / "pg_ctl"), "-D", str(data), "-w"]
        start = [
            *pg_ctl,
            "-l",
            str(root / "server.log"),
            "-o",
            shlex.join(
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
                ]
            ),
            "start",
        ]
        command = [
            str(binary_dir / "psql"),
            "-X",
            "-w",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            str(socket),
            "-p",
            "55432",
            "-U",
            "session_research",
            "-d",
            "postgres",
        ]
        holders = []
        count = 0

        def query(sql, *, fails=False):
            result = subprocess.run(
                [*command, "-c", sql],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if fails:
                assert result.returncode != 0
                return result.stderr
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        def reset():
            query(
                "TRUNCATE sessions,owners; INSERT INTO owners VALUES ('owner',1); INSERT INTO sessions(device,subject,generation) VALUES ('a','owner',1),('b','owner',1);"
            )

        def hold(sql):
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            holders.append(process)
            process.stdin.write("BEGIN; " + sql + "; SELECT 'ready';\n")
            process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                output = b""
                while selector.select(timeout=5):
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    output += chunk
                    if b"ready\n" in output:
                        return process
            raise AssertionError("SQL barrier did not become ready")

        def release(process):
            process.stdin.write("COMMIT;\n\\q\n")
            process.stdin.flush()
            process.communicate(timeout=10)
            assert process.returncode == 0

        try:
            subprocess.run(start, check=True, capture_output=True)
            source = (
                Path(__file__).resolve().parents[1]
                / "docs/prototypes/session_authority.sql"
            )
            query(source.read_text())
            reset()
            before = query(
                "SELECT seen,refresh_generation FROM sessions ORDER BY device;"
            )
            assert query("SELECT allowed('a',1);") == "t"
            assert query("SELECT activity('a',1,60);") == "t"
            assert (
                query("SELECT seen,refresh_generation FROM sessions ORDER BY device;")
                == before
            )
            assert query("SELECT activity('a',60,60);") == "t"
            assert (
                query("SELECT seen,refresh_generation FROM sessions ORDER BY device;")
                == "60|0\n0|0"
            )
            count += 1

            reset()
            query(
                "CREATE FUNCTION reject_touch() RETURNS trigger LANGUAGE plpgsql "
                "AS $$ BEGIN RAISE EXCEPTION 'synthetic touch failure'; END $$; "
                "CREATE TRIGGER reject_touch BEFORE UPDATE ON sessions "
                "FOR EACH ROW EXECUTE FUNCTION reject_touch();"
            )
            assert "synthetic touch failure" in query(
                "SELECT activity('a',60,60);", fails=True
            )
            assert query("SELECT activity('a',1,60);") == "t"
            assert query("SELECT seen FROM sessions WHERE device='a';") == "0"
            query(
                "DROP TRIGGER reject_touch ON sessions; DROP FUNCTION reject_touch();"
            )
            count += 1

            reset()
            process = hold(
                "SELECT generation FROM owners WHERE subject='owner' FOR KEY SHARE"
            )
            query(
                "SET lock_timeout='200ms'; "
                "UPDATE owners SET generation=generation+1 WHERE subject='owner';"
            )
            assert query("SELECT allowed('a',1);") == "f"
            release(process)
            count += 1

            reset()
            process = hold(
                "SELECT generation FROM owners WHERE subject='owner' FOR SHARE"
            )
            error = query(
                "SET lock_timeout='200ms'; SELECT end_all('owner');", fails=True
            )
            assert "lock timeout" in error
            release(process)
            query("SELECT end_all('owner');")
            assert (
                query("SELECT allowed('a',1),allowed('b',1),activity('a',60,60);")
                == "f|f|f"
            )
            query("SELECT begin_device('new','owner',1);")
            assert query("SELECT allowed('new',1);") == "t"
            count += 1

            reset()
            process = hold("SELECT end_all('owner')")
            error = query(
                "SET lock_timeout='200ms'; SELECT begin_device('new','owner',1);",
                fails=True,
            )
            assert "lock timeout" in error
            release(process)
            query("SELECT begin_device('new','owner',1);")
            assert query("SELECT allowed('a',1),allowed('new',1);") == "f|t"
            count += 1

            reset()
            query("SELECT end_device('a');")
            assert query("SELECT activity('a',60,60),allowed('b',1);") == "f|t"
            count += 1

            reset()
            pending = [
                subprocess.Popen(
                    [*command, "-c", f"SELECT claim('a','{name}',0,1);"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for name in ("left", "right")
            ]
            outcomes = [process.communicate(timeout=10) for process in pending]
            assert all(process.returncode == 0 for process in pending)
            assert sorted(stdout.strip() for stdout, _ in outcomes) == ["f", "t"]
            nonce = query("SELECT lease FROM sessions WHERE device='a';")
            assert (
                query(f"SELECT settle('a','{nonce}',0,2),settle('a','{nonce}',0,2);")
                == "t|t"
            )
            assert (
                query("SELECT refresh_generation FROM sessions WHERE device='a';")
                == "1"
            )
            count += 1

            reset()
            assert query("SELECT claim('a','held',0,1);") == "t"
            assert (
                query(
                    "SELECT claim('a','other',0,11),settle('a','held',0,12),allowed('a',12);"
                )
                == "f|f|f"
            )
            reset()
            assert query("SELECT claim('a','held',0,1);") == "t"
            query("SELECT end_all('owner');")
            assert query("SELECT settle('a','held',0,2);") == "f"
            reset()
            query("UPDATE sessions SET seen=2591999 WHERE device='a';")
            assert query("SELECT claim('a','last-second',0,2591999);") == "t"
            assert query("SELECT settle('a','last-second',0,2592000);") == "f"
            count += 1

            reset()
            assert query("SELECT allowed('a',604799),allowed('a',604800);") == "t|f"
            query("UPDATE sessions SET seen=2591999 WHERE device='a';")
            assert query("SELECT allowed('a',2591999),allowed('a',2592000);") == "t|f"
            count += 1

            reset()
            query("SELECT end_all('owner');")
            subprocess.run(
                [*pg_ctl, "-m", "fast", "stop"], check=True, capture_output=True
            )
            subprocess.run(start, check=True, capture_output=True)
            assert query("SELECT allowed('a',1),allowed('b',1);") == "f|f"
            assert query("SHOW synchronous_commit;") == "on"
            assert query("SHOW fsync;") == "on"
            count += 1
            print(f"PostgreSQL protocol checks passed: {count} scenarios")
            print(
                "Checked: bounded touches; device/all-device logout; concurrent sign-in;"
            )
            print(
                "single refresh claim; idempotent settlement; stale lease; expiry; restart."
            )
            print(
                "Not proved: JWT/provider integration, failover, outbox, migration, or latency."
            )
        finally:
            for process in holders:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
            subprocess.run(
                [*pg_ctl, "-m", "immediate", "stop"],
                check=False,
                capture_output=True,
                timeout=10,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    found = shutil.which("postgres")
    parser.add_argument(
        "--postgres-bin", type=Path, default=Path(found).parent if found else None
    )
    args = parser.parse_args()
    if args.postgres_bin is None:
        parser.error("Supply --postgres-bin pointing to installed PostgreSQL binaries")
    run(args.postgres_bin)
