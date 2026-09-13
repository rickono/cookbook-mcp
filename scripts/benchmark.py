"""Run inside a memory-limited Docker container; prints metrics, never passages."""

import argparse
import json
from pathlib import Path
import resource
import time
from cookbook.storage import LocalStore
from cookbook.publication import Runtime
from cookbook.library import Library

p = argparse.ArgumentParser()
p.add_argument("--store", type=Path, required=True)
p.add_argument("--runtime", type=Path, required=True)
p.add_argument("--real", action="store_true")
a = p.parse_args()
start = time.monotonic()
runtime = Runtime(LocalStore(a.store), a.runtime)
pub = runtime.recover()
lib = Library(runtime)
restore_seconds = time.monotonic() - start
times = []
for i in range(100):
    t = time.monotonic()
    r = lib.search(["salt", "beans", "wine", "chicken"][i % 4])
    times.append(time.monotonic() - t)
with lib.db(pub) as db:
    books = db.execute(
        "select b.id,b.source_id,s.format from books b join sources s on b.source_id=s.id"
    ).fetchall()
    images = db.execute("select id,source_id from images limit 5").fetchall()
    if a.real:
        for im in images:
            b = next(b for b in books if b["source_id"] == im["source_id"])
            lib.get_image(pub, b["id"], b["source_id"], im["id"])
        for b in books:
            if b["format"] in ("PDF", "DJVU"):
                for page in [1, 20]:
                    lib.get_page(pub, b["id"], b["source_id"], page)
size = sum(p.stat().st_size for p in a.runtime.rglob("*") if p.is_file())
try:
    cgroup_peak = int(Path("/sys/fs/cgroup/memory.peak").read_text())
except OSError:
    cgroup_peak = None
print(
    json.dumps(
        {
            "publication_id": pub,
            "records": len(books),
            "restore_seconds": restore_seconds,
            "search_p50_ms": sorted(times)[50] * 1000,
            "search_p95_ms": sorted(times)[95] * 1000,
            "runtime_disk_bytes": size,
            "max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "cgroup_peak_bytes": cgroup_peak,
            "elapsed_seconds": time.monotonic() - start,
            "real_fixtures": a.real,
        }
    )
)
