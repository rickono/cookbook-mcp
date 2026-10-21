"""Production transcription of any registered PDF book (spec #46): the reader-benchmark pipeline,
generalised from the frozen benchmark page list to a registered book's full page range.

  production.py run      BOOK... | --all [--workers N]   page images from the guarded helper, then
                                                         page reads, crop votes and patches (resumes)
  production.py assemble BOOK... | --all [--offline] [--allow-missing]
                                                         sectioning, assembler v4, scanned candidate
  production.py status   [BOOK...]                       per-book progress and list-price cost

The reader is fixed to the production config: Claude Haiku 5.5 x3, with Codex Luna low reading only
pages Anthropic's output filter refuses. Everything is written under
$COOKBOOK_DATA/production/transcription/<config>/, never to the frozen benchmark (EXP, reader-bench
work dirs, baseline.json). `run` refuses to start unless scripts/ocr_sandbox.py doctor passes, and
page images and crops come only from the registered-book helper, which runs each job through the
sandbox. A page whose page read failed is not cached as done; its calls are kept in
work/failures/ so the cost is counted, and a page whose reads were only ever empty is blank.
"""

import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
import threading
import time

import assemble as asm
import bench
import candidate
import costs
import pipeline as fp
import readers as rd

READER = "claude:claude-haiku-5-5"
FALLBACK = "codex:gpt-6-luna@low"
PROD = fp.DATA / "production/transcription"
REGISTRY = fp.HELPER.parents[1] / "manifest.json"
WINDOW = 20  # the helper renders at most 20 registered pages per job
BLANK_ROUNDS = 2  # a page is blank once two run passes saw only empty page reads
_log_lock = threading.Lock()


def config(root=None):
    n = bench.names(READER, FALLBACK)
    base = (root or PROD) / n["config"]
    return {**n, "root": base, "work": base / "work"}


def registered(manifest=None):
    """{book_id: {sha256, physical_pages}} from the frozen helper registration."""
    books = json.loads((manifest or REGISTRY).read_text())["books"]
    return {
        b["book_id"]: {"sha256": b["sha256"], "physical_pages": b["physical_pages"]}
        for b in books
    }


def book_dir(n, book):
    return n["root"] / "books" / str(book)


def helper_render(book, start, end):
    """Overview renders through the guarded helper (it runs the doctor and the sandbox itself)."""
    p = subprocess.run(
        [sys.executable, str(fp.HELPER), "render", str(book), str(start), str(end)],
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if p.returncode:
        sys.exit(f"helper render {book} {start}-{end} refused:\n{p.stderr[-1500:]}")
    return json.loads(p.stdout)["images"]


def page_images(n, book, reg, render=helper_render):
    """The book's page image records in the frozen images.json shape, rendered once per window."""
    want = reg["physical_pages"]
    out = book_dir(n, book) / "images.json"
    if out.exists():
        rows = json.loads(out.read_text())
    else:
        rows = []
        cache = book_dir(n, book) / "render"
        cache.mkdir(parents=True, exist_ok=True)
        for start in range(1, want + 1, WINDOW):
            end = min(want, start + WINDOW - 1)
            f = cache / f"w{start:04d}-{end:04d}.json"
            if not f.exists():
                got = render(book, start, end)
                if sorted(r["physical_page"] for r in got) != list(
                    range(start, end + 1)
                ):
                    sys.exit(f"book {book}: render {start}-{end} returned other pages")
                f.write_text(json.dumps(got, indent=1))
            rows += [
                {k: r[k] for k in ("image", "physical_page", "sha256", "source_sha256")}
                for r in json.loads(f.read_text())
            ]
        out.write_text(json.dumps(rows, indent=1))
    if [r["physical_page"] for r in rows] != list(range(1, want + 1)) or any(
        r["source_sha256"] != reg["sha256"] for r in rows
    ):
        sys.exit(f"book {book}: page images do not match the registered source")
    return rows


def page_file(n, book, page):
    return n["work"] / "pages" / f"b{book}-p{page:03d}.json"


def failure_file(n, book, page):
    return n["work"] / "failures" / f"b{book}-p{page:03d}.json"


def record_failure(n, book, page, rec):
    """Keep a failed page's calls (they are priced) and why its page read failed."""
    f = failure_file(n, book, page)
    f.parent.mkdir(exist_ok=True)
    d = (
        json.loads(f.read_text())
        if f.exists()
        else {"book": book, "page": page, "attempts": []}
    )
    d["attempts"].append(
        {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            **{k: rec[k] for k in ("page_read", "regions", "crops")},
        }
    )
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def blank(n, book, page):
    """True when every recorded page read of the page, over BLANK_ROUNDS passes, came back empty."""
    f = failure_file(n, book, page)
    if page_file(n, book, page).exists() or not f.exists():
        return False
    return candidate.blank_evidence(json.loads(f.read_text()), BLANK_ROUNDS) is not None


def run_book(n, book, images, workers):
    meta = {r["physical_page"]: r for r in images}
    jobs = [
        p
        for p in sorted(meta)
        if not page_file(n, book, p).exists() and not blank(n, book, p)
    ]

    def one(page):
        rec = fp.run_page(n["work"], book, page, meta[page])
        if rd.STOP.is_set() or not rec["page_read"]["text"]:
            page_file(n, book, page).unlink(missing_ok=True)
            if not rd.STOP.is_set():
                record_failure(n, book, page, rec)
        return rec

    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(one, p): p for p in jobs}
        for f in cf.as_completed(futs):
            p = futs[f]
            try:
                r = f.result()
                line = {
                    "book": book,
                    "page": p,
                    "ok": bool(r["page_read"]["text"]),
                    "page_model": (r["page_read"]["calls"] or [{}])[-1].get("model"),
                }
            except Exception as e:  # noqa: BLE001 - keep going; failure is evidence
                line = {"book": book, "page": p, "exception": repr(e)}
            with _log_lock:
                print(json.dumps(line), flush=True)


def progress(n, book, reg):
    """Pages transcribed, blank, failed and not yet tried, and list-price cost so far."""
    pages = range(1, reg["physical_pages"] + 1)
    done = [p for p in pages if page_file(n, book, p).exists()]
    blanks = [p for p in pages if blank(n, book, p)]
    failed = [
        p
        for p in pages
        if p not in done and p not in blanks and failure_file(n, book, p).exists()
    ]
    paid = sorted((n["work"] / "pages").glob(f"b{book}-p*.json")) + sorted(
        (n["work"] / "failures").glob(f"b{book}-p*.json")
    )
    labels = sorted((n["work"] / "sections" / str(book)).glob("p*.json"))
    page_usd = costs.summarize(paid)["list_usd"] if paid else 0.0
    label_usd = costs.summarize(labels)["list_usd"] if labels else 0.0
    return {
        "book": book,
        "pages": len(pages),
        "transcribed": len(done),
        "blank": len(blanks),
        "failed": len(failed),
        "pending": len(pages) - len(done) - len(blanks) - len(failed),
        "page_list_usd": page_usd,
        "sectioning_list_usd": label_usd,
        "list_usd": round(page_usd + label_usd, 4),
    }


def transcribe(n, books, registry, workers=3, passes=2, render=helper_render):
    """Page-read every registered page of `books`; reruns skip finished and blank pages."""
    fp.READERS, fp.FALLBACK = n["samples"], n["fallback"]
    (n["work"] / "empty").mkdir(parents=True, exist_ok=True)  # readers' cwd
    report = []
    for book in books:
        images = page_images(n, book, registry[book], render)
        for _ in range(passes):  # later passes retry pages whose page read failed
            run_book(n, book, images, workers)
            if rd.STOP.is_set():
                print(json.dumps(progress(n, book, registry[book])), flush=True)
                sys.exit(
                    "stopped on a usage/rate limit; rerun the same command to resume"
                )
        report.append(progress(n, book, registry[book]))
        print(json.dumps(report[-1]), flush=True)
    return report


def no_render(book, start, end):
    sys.exit(f"book {book}: no page images yet; run `production.py run {book}` first")


def assemble_book(n, book, reg, workers=4, allow_missing=False):
    """Sectioning and assembler v4 into books/<b>/assembly, then the scanned candidate."""
    images = page_images(n, book, reg, no_render)
    pages = range(1, reg["physical_pages"] + 1)
    lost = [
        p for p in pages if not page_file(n, book, p).exists() and not blank(n, book, p)
    ]
    if lost and not allow_missing:
        sys.exit(
            f"book {book}: {len(lost)} pages not transcribed, e.g. {lost[:10]}; rerun "
            "`production.py run`, or pass --allow-missing to publish them as unresolved"
        )
    assembly = book_dir(n, book) / "assembly"
    asm.assemble(
        n["samples"][0],
        n["model"],
        n["work"],
        book,
        assembly,
        n["config"],
        workers,
        allow_missing=True,  # every missing page is blank or explicitly allowed above
        images=images,
    )
    failures = {
        p: json.loads(failure_file(n, book, p).read_text())
        for p in pages
        if failure_file(n, book, p).exists()
    }
    result = candidate.write(
        assembly,
        n["work"],
        images,
        failures,
        book_dir(n, book) / "candidate",
        BLANK_ROUNDS,
    )
    print(json.dumps({"book": book, **result}), flush=True)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("command", choices=["run", "assemble", "status"])
    ap.add_argument("books", nargs="*", type=int, metavar="BOOK")
    ap.add_argument("--all", action="store_true", help="every registered book")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument(
        "--offline",
        action="store_true",
        help="assemble from cached labels; any model call fails",
    )
    ap.add_argument(
        "--allow-missing",
        action="store_true",
        help="assemble although some pages failed (they become unresolved)",
    )
    a = ap.parse_args(argv)
    registry = registered()
    books = (
        sorted(registry)
        if a.all or (a.command == "status" and not a.books)
        else a.books
    )
    if not books:
        ap.error("name BOOK ids or pass --all")
    unknown = [b for b in books if b not in registry]
    if unknown:
        sys.exit(f"not registered: {', '.join(map(str, unknown))}")
    n = config()
    if a.command == "status":
        for b in books:
            print(json.dumps(progress(n, b, registry[b])))
    elif a.command == "run":
        bench.doctor()  # admission precedes every render, page read and crop
        bench.record(n, "production run " + " ".join(map(str, books)))
        transcribe(n, books, registry, a.workers, render=helper_render)
    else:
        if a.offline:
            rd.OFFLINE.set()
        bench.record(n, "production assemble " + " ".join(map(str, books)))
        for b in books:
            assemble_book(n, b, registry[b], a.workers, a.allow_missing)


if __name__ == "__main__":
    main()
