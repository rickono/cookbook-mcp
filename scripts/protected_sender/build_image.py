"""Extract only CPython, stdlib, TLS roots and required shared libraries."""

import re
import shutil
import subprocess
import sysconfig
from pathlib import Path

target = Path("/minimal")
stdlib = Path(sysconfig.get_path("stdlib"))
shutil.copytree(
    stdlib,
    target / stdlib.relative_to("/"),
    ignore=shutil.ignore_patterns(
        "site-packages",
        "ensurepip",
        "__pycache__",
        "test",
        "tests",
        "tkinter",
        "idlelib",
    ),
)
python = Path("/usr/local/bin/python3.12")
(target / "usr/local/bin").mkdir(parents=True)
shutil.copy2(python, target / "usr/local/bin/python")
libraries = set()
for file in [python, *stdlib.glob("lib-dynload/*.so")]:
    text = subprocess.check_output(["ldd", str(file)], text=True)
    libraries.update(re.findall(r"(/[^\s()]+)", text))
for name in libraries:
    path = Path(name)
    destination = target / path.relative_to("/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path.resolve(), destination)
destination = target / "etc/ssl/certs/ca-certificates.crt"
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2("/etc/ssl/certs/ca-certificates.crt", destination)
(target / "tmp").mkdir(mode=0o1777)
