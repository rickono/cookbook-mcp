"""Synthetic manifest benchmark. Requires dev dependencies; never invokes OCR.

Run with PYTHONPATH=src:tests python scripts/benchmark_manifest_cache.py
--output /absolute/private/output.json. Source books are neither read nor generated.
Baseline reproduces Runtime.manifest before this change in the same process.
"""

import argparse
import gc
import hashlib
import json
from pathlib import Path
import platform
import re
import resource
import shutil
import statistics
import tempfile
import time
import tracemalloc
from unittest.mock import patch

from conftest import fixture_build
from cookbook.library import Library
from cookbook.publication import Entry, Manifest, Runtime, validate_version
from cookbook.storage import IntegrityError, LocalStore, canonical


class BaselineRuntime(Runtime):
    """The pre-cache lookup, preserved only for this synthetic comparison."""

    def manifest(self, publication_id):
        if not re.fullmatch("[a-f0-9]{32}", publication_id):
            raise IntegrityError("unavailable publication")
        path = self.root / "versions" / publication_id / "manifest.json"
        if not path.exists():
            raise IntegrityError("unavailable publication")
        return Manifest.model_validate_json(path.read_bytes())


def measure(root, store, pubs, runtime_class, iterations):
    def library():
        return Library(runtime_class(store, root))

    lib = library()
    citation = lib.search("salt")["results"][0]["citation"]
    args = [pubs[0], citation["book_id"], citation["source_id"]]
    operations = {
        "catalog_search": lambda lib: lib.search("Beans", mode="catalog"),
        "fulltext_search": lambda lib: lib.search("salt"),
        "section_read": lambda lib: lib.read_section(
            *args, citation["section_id"], limit=50
        ),
        "cached_image": lambda lib: lib.get_image(*args, "image-0"),
    }
    # Prime the disk asset cache in both modes; only manifest residency varies.
    operations["cached_image"](lib)
    metrics = {}
    for name, operation in operations.items():
        cold, warm = [], []
        original = Manifest.model_validate_json
        parses = 0

        def parse(raw):
            nonlocal parses
            parses += 1
            return original(raw)

        with patch.object(Manifest, "model_validate_json", parse):
            for _ in range(iterations):
                lib = library()
                start = time.perf_counter_ns()
                first = operation(lib)
                cold.append((time.perf_counter_ns() - start) / 1e6)
                start = time.perf_counter_ns()
                second = operation(lib)
                warm.append((time.perf_counter_ns() - start) / 1e6)
                assert first == second
            total_parses = parses
        metrics[name] = {
            "response_sha256": hashlib.sha256(repr(first).encode()).hexdigest(),
            "cold_median_ms": statistics.median(cold),
            "warm_median_ms": statistics.median(warm),
            "parses_for_cold_warm_pairs": total_parses,
        }
    # Measure allocations retained by a full three-publication working set,
    # independently from timing. Do not equate JSON bytes with object memory.
    lib = library()
    gc.collect()
    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    for pub in pubs:
        lib.runtime.manifest(pub)
    gc.collect()
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "operations": metrics,
        "retained_python_bytes_three_publications": retained - before,
        "peak_python_bytes_during_population": peak - before,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entries", type=int, default=11000)
    parser.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args()
    if args.entries < 4 or args.iterations < 1:
        parser.error("at least four entries and one iteration are required")
    with tempfile.TemporaryDirectory(prefix="cookbook-manifest-benchmark-") as work:
        work = Path(work)
        root = work / "runtime"
        store = LocalStore(work / "store")
        pubs, sizes = [], []
        for i in range(3):
            m, inputs = fixture_build(
                work / f"build-{i}", publication_id=f"{i + 1:032x}"
            )
            seed = next(e for e in m.files if e.role == "asset")
            m.files.extend(
                Entry(
                    path=f"assets/synthetic-inventory-{j:05d}.jpg",
                    sha256=seed.sha256,
                    size=seed.size,
                    role="asset",
                )
                for j in range(args.entries - len(m.files))
            )
            destination = root / "versions" / m.publication_id
            (destination / "runtime").mkdir(parents=True)
            shutil.copyfile(
                inputs["runtime/index.sqlite"], destination / "runtime/index.sqlite"
            )
            store.put_file(seed.key, inputs[seed.path])
            raw = canonical(m.model_dump())
            (destination / "manifest.json").write_bytes(raw)
            pointer = {
                "publication_id": m.publication_id,
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            }
            validate_version(pointer, destination)
            if i == 0:
                (root / "active.json").write_bytes(canonical(pointer))
            pubs.append(m.publication_id)
            sizes.append(len(raw))
        report = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "entries_per_manifest": args.entries,
            "manifest_bytes": sizes,
            "index_bytes": (root / "versions" / pubs[0] / "runtime/index.sqlite")
            .stat()
            .st_size,
            "cache_capacity": 3,
            "iterations_per_operation": args.iterations,
            "existing_machine_limit_bytes": 1024**3,
            "before": measure(root, store, pubs, BaselineRuntime, args.iterations),
            "after": measure(root, store, pubs, Runtime, args.iterations),
        }
        for operation in report["before"]["operations"]:
            assert (
                report["before"]["operations"][operation]["response_sha256"]
                == report["after"]["operations"][operation]["response_sha256"]
            )
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["whole_benchmark_process_peak_rss_bytes"] = (
            peak if platform.system() == "Darwin" else peak * 1024
        )
        report["after"]["retained_fraction_of_machine_limit"] = (
            report["after"]["retained_python_bytes_three_publications"] / 1024**3
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
