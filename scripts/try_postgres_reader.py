"""Run actual synthetic reader HTTP tests against disposable local PostgreSQL.

Example: uv run --extra postgres python scripts/try_postgres_reader.py --postgres-bin /Library/PostgreSQL/17/bin
No library credentials, real provider, source books or production storage are used.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from local_session_postgres import local_postgres


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    installed = shutil.which("postgres")
    parser.add_argument(
        "--postgres-bin",
        type=Path,
        default=Path(installed).parent if installed else None,
    )
    args = parser.parse_args()
    if args.postgres_bin is None:
        parser.error("Supply --postgres-bin pointing to installed PostgreSQL binaries")
    root = Path(__file__).resolve().parents[1]
    with local_postgres(args.postgres_bin) as conninfo:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_reader_postgres.py",
                "tests/test_session_database.py",
            ],
            cwd=root,
            env={
                **os.environ,
                "READER_TRIAL_DATABASE": conninfo,
                "READER_TRIAL_PG_BIN": str(args.postgres_bin.resolve()),
            },
            check=False,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
