"""Benchmark a small reader model against the Haiku 5.5 x3 baseline (docs/reader-benchmark.md).

  bench.py smoke    READER                one page-read call; proves the CLI wiring, no crops
  bench.py pilot    READER [--workers N]  the 39 reference pages, then the pilot score
  bench.py full     READER [--workers N]  all 872 pages of the three books (resumes; one retry pass)
  bench.py assemble READER [--offline] [--allow-missing]
                                          sectioning calls + the candidate files for each book
  bench.py prompts  READER                evaluation briefs and the delegate_task calls to grade them
  bench.py compare  READER                pilot score, cost, time, lost pages, grades vs baseline.json
  bench.py verify                         after any code change: rebuild the baseline from its cached
                                          artifacts with zero model calls and check every number and file

READER is a spec from readers.py, e.g. claude:claude-haiku-5-5 or codex:gpt-6-luna@low; it is
sampled three times. --fallback READER2 (pilot, full, assemble, prompts, compare) reads a page with
READER2 only when READER's page read is refused by a provider output filter; it is a separate
config with its own work dir. Pages and labels are cached under $COOKBOOK_DATA/batches/reader-bench, so
every command can be rerun. Crops go only through the guarded pdf_helper; pilot and full refuse
to start unless scripts/ocr_sandbox.py doctor passes.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import assemble as asm
import costs
import eval_prompt
import pipeline as fp
import readers as rd
import score

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BENCH = fp.DATA / "batches/reader-bench"
BOOKS = (6, 79, 81)
SMOKE_PAGE = (6, 34)
BASELINE = HERE / "baseline.json"
EVAL_TARGET = {
    "providerInstanceId": "codex",
    "model": "gpt-6.1-sol",
    "options": {"reasoningEffort": "medium"},
}


def slug(model, effort):
    return re.sub(r"[^a-z0-9]+", "-", model.lower()) + (f"--{effort}" if effort else "")


def names(reader, fallback=None):
    backend, model, effort = rd.parse(reader)
    base = f"pipeline-{slug(model, effort)}-x3"
    if fallback:
        _, fmodel, feffort = rd.parse(fallback)
        base += f"-fb-{slug(fmodel, feffort)}"
    return {
        "backend": backend,
        "model": model,
        "effort": effort,
        "work": BENCH / base,
        "config": f"{base}-a{asm.ASSEMBLER.removeprefix('v')}",
        "samples": [f"{reader}#{k}" for k in (1, 2, 3)],
        "fallback": f"{fallback}#fallback" if fallback else None,
    }


def code_sha():
    return {
        f: hashlib.sha256((HERE / f).read_bytes()).hexdigest()[:16]
        for f in ("pipeline.py", "readers.py", "assemble.py")
    }


def doctor():
    p = subprocess.run(
        [sys.executable, str(REPO / "scripts/ocr_sandbox.py"), "doctor"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    if p.returncode:
        sys.exit(
            "scripts/ocr_sandbox.py doctor refused; guarded crops are unavailable, so the run was "
            "not started:\n" + (p.stdout + p.stderr)[-1500:]
        )


def record(n, command):
    """Append what ran to manifest.json, so a result can be traced to its code and protocol."""
    n["work"].mkdir(parents=True, exist_ok=True)
    f = n["work"] / "manifest.json"
    m = (
        json.loads(f.read_text())
        if f.exists()
        else {"reader_samples": n["samples"], "fallback": n["fallback"], "runs": []}
    )
    git = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    clis = [n["backend"]] + ([rd.parse(n["fallback"])[0]] if n["fallback"] else [])
    versions = []
    for c in dict.fromkeys(clis):
        v = subprocess.run(
            [c, "--version"], check=False, capture_output=True, text=True
        )
        versions.append((v.stdout or v.stderr).strip()[:80])
    m["runs"].append(
        {
            "command": command,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "code_sha": code_sha(),
            "repo_head": git.stdout.strip() or None,
            "cli_version": "; ".join(versions),
        }
    )
    f.write_text(json.dumps(m, indent=1))


def pages(spec_file):
    out = []
    for spec in (HERE / spec_file).read_text().split():
        b, ps = spec.split(":")
        out += [(int(b), int(p)) for p in ps.split(",")]
    return out


def run_pages(n, jobs, workers, passes):
    fp.READERS, fp.FALLBACK = n["samples"], n["fallback"]
    for k in range(passes):  # the second pass retries pages whose page read failed
        fp.run(n["work"], jobs, workers)
        if rd.STOP.is_set():
            sys.exit("stopped on a usage/rate limit; rerun the same command to resume")
    done = {
        (b, p)
        for b, p in jobs
        if (n["work"] / "pages" / f"b{b}-p{p:03d}.json").exists()
    }
    print(
        json.dumps(
            {"pages": len(jobs), "done": len(done), "lost": sorted(set(jobs) - done)}
        )
    )


def cmd_smoke(n, a):
    (n["work"] / "empty").mkdir(parents=True, exist_ok=True)
    text, meta = rd.call(
        n["work"],
        n["samples"][0],
        fp.PAGE_PROMPT,
        fp.image_meta(*SMOKE_PAGE)["image"],
        attempts=1,
    )
    print(
        json.dumps(
            {
                "ok": bool(text),
                "first_line": (text or "").strip().splitlines()[:1],
                **meta,
            }
        )
    )
    if text and "tokens" in meta:
        print(f"list cost ${costs.list_cost(meta['model'], meta['tokens']):.5f}")
    sys.exit(0 if text else 1)


def cmd_pilot(n, a):
    doctor()
    record(n, "pilot")
    run_pages(n, pages("pilot-pages.txt"), a.workers, passes=1)
    score.report(n["work"] / "pages", show_detail=False)


def cmd_full(n, a):
    doctor()
    record(n, "full")
    run_pages(n, pages("full-pages.txt"), a.workers, passes=2)


def cmd_assemble(n, a):
    if a.offline:
        rd.OFFLINE.set()
    graded = [
        b
        for b in BOOKS
        if (fp.EXP / f"evaluation/candidates/{n['config']}/books/{b}").exists()
    ]
    if graded:
        sys.exit(
            f"{n['config']} books {graded} are already graded; their candidate files are frozen"
        )
    record(n, "assemble")
    for b in BOOKS:
        asm.assemble(
            n["samples"][0],
            n["model"],
            n["work"],
            b,
            fp.EXP / f"runs/{n['config']}/books/{b}/output",
            n["config"],
            a.workers,
            a.allow_missing,
        )


def cmd_prompts(n, a):
    reader = (
        f"scripted pipeline: {n['backend']} {n['model']}"
        + (f" effort {n['effort']}" if n["effort"] else "")
        + " x3 samples (page read, region boxes, crop votes, sectioning)"
        + (
            f"; pages whose page read {n['model']} refused under its provider output filter were page-read "
            f"once by {n['fallback'].split('#')[0]} instead (region boxes, crop votes and sectioning stay "
            f"{n['model']}); assembler "
            if n["fallback"]
            else "; assembler "
        )
        + f"{asm.ASSEMBLER}, deterministic, whose cross-page join rules and quantity-review records were revised "
        "after evaluator feedback on earlier cells of this pipeline (so it is not a blind first pass of the "
        "assembler)"
    )
    graded = [
        b
        for b in BOOKS
        if (fp.EXP / f"evaluation/candidates/{n['config']}/books/{b}").exists()
    ]
    if graded:
        sys.exit(
            f"{n['config']} books {graded} already have evaluations; their briefs are frozen"
        )
    for b in BOOKS:
        path = eval_prompt.write(n["config"], b, reader)
        rid = f"mc3b-eval-{n['config']}-b{b}-r1"
        print(
            json.dumps(
                {
                    "tool": "mcp__t3-code__delegate_task",
                    "args": {
                        "task": f"Read the file {path} and carry out its instructions exactly. That file is your complete brief.",
                        "target": EVAL_TARGET,
                        "mode": "async",
                        "role": "review",
                        "clientRequestId": rid,
                    },
                }
            )
        )


def measure(work, config):
    page_files = sorted((work / "pages").glob("b*-p*.json"))
    label_files = sorted((work / "sections").glob("*/p*.json"))
    per_book, _ = score.score(work / "pages")
    grades = {}
    for b in BOOKS:
        f = fp.EXP / f"evaluation/candidates/{config}/books/{b}/bench-summary.json"
        grades[str(b)] = json.loads(f.read_text()) if f.exists() else None
    return {
        "pilot": {
            str(b): {k: c[k] for k in ("after", "n", "qafter", "qn", "missing")}
            for b, c in sorted(per_book.items())
        },
        "pages_done": len(page_files),
        "pages_by_fallback": sum(
            1
            for f in page_files
            if json.loads(f.read_text())["page_read"]["calls"][-1].get("fallback_for")
        ),
        "pages_total": len(pages("full-pages.txt")),
        "page_costs": costs.summarize(page_files) if page_files else None,
        "sectioning_costs": costs.summarize(label_files) if label_files else None,
        "grades": grades,
    }


def cmd_compare(n, a):
    new, base = measure(n["work"], n["config"]), json.loads(BASELINE.read_text())
    out = {
        "reader": n["samples"][0].split("#")[0]
        + (f" + fallback {n['fallback'].split('#')[0]}" if n["fallback"] else ""),
        "config": n["config"],
        "code_sha": code_sha(),
        "baseline_code_sha": base["code_sha"],
        **new,
    }
    (n["work"] / "compare.json").write_text(json.dumps(out, indent=1))

    def tot(m, k):
        return sum(v[k] for v in m["pilot"].values())

    def money(m, k):
        return f"${m[k]['list_usd']:.2f} ({m[k]['files']} pages)" if m.get(k) else "-"

    def grade(g):
        if not g:
            return "not graded"
        f, r, s = g["fidelity"], g["retrieval"], g["structural"]
        return (
            f"fid {f['passed']}/{f['denominator']}  ret {r['hit_at_1']}/{r['probes']},"
            f"{r['hit_at_5']}/{r['probes']},{r['mrr']:.3f}  struct {s['errors']}/{s['warnings']}/{s['unknowns']}"
        )

    rows = [
        (
            "pilot items",
            f"{tot(base, 'after')}/{tot(base, 'n')}",
            f"{tot(new, 'after')}/{tot(new, 'n')}",
        ),
        (
            "pilot quantity lines",
            f"{tot(base, 'qafter')}/{tot(base, 'qn')}",
            f"{tot(new, 'qafter')}/{tot(new, 'qn')}",
        ),
        ("pilot pages lost", str(tot(base, "missing")), str(tot(new, "missing"))),
        (
            "pages read by fallback",
            *(str(m.get("pages_by_fallback", 0)) for m in (base, new)),
        ),
        (
            "pages done",
            f"{base['pages_done']}/{base['pages_total']}",
            f"{new['pages_done']}/{new['pages_total']}",
        ),
        ("page list cost", money(base, "page_costs"), money(new, "page_costs")),
        (
            "sectioning list cost",
            money(base, "sectioning_costs"),
            money(new, "sectioning_costs"),
        ),
        (
            "call seconds median",
            *(
                str((m.get("page_costs") or {}).get("call_seconds_median"))
                for m in (base, new)
            ),
        ),
        (
            "page seconds median",
            *(
                str((m.get("page_costs") or {}).get("page_seconds_median"))
                for m in (base, new)
            ),
        ),
    ]
    rows += [
        (f"b{b} grade", grade(base["grades"][str(b)]), grade(new["grades"][str(b)]))
        for b in BOOKS
    ]
    w = max(len(r[1]) for r in rows)
    print(f"{'':22} {'baseline ' + base['reader']:<{w}}  {out['reader']}")
    for label, x, y in rows:
        print(f"{label:22} {x:<{w}}  {y}")
    if out["code_sha"] != base["code_sha"]:
        print(
            "\nNOTE: pipeline/readers/assemble code differs from the baseline's; `bench.py verify` must "
            "pass, and prompts or command lines must be unchanged, before these results compare."
        )
    if base.get("grade_note"):
        print("\nNOTE: " + base["grade_note"])


def cmd_verify(n, a):
    """The protocol is unchanged iff the baseline's recorded readings still produce its page texts,
    candidate files, pilot score and costs. Needs no model calls and no guarded crops."""
    base = json.loads(BASELINE.read_text())
    work = Path(base["work"].replace("$COOKBOOK_DATA", str(fp.DATA)))
    rd.OFFLINE.set()
    bad = []
    for f in sorted((work / "pages").glob("b*-p*.json")):
        r = json.loads(f.read_text())
        boxes = {
            m: fp.parse_regions(c["raw"])
            for m, c in zip(r["regions"]["by_model"], r["regions"]["calls"])
        }
        voted = []
        for c in r["crops"]:
            if "image" in c:
                voted += fp.vote(c["readings"]) if len(c["readings"]) >= 2 else []
        page_model = (
            r["page_read"]["calls"][-1].get("model") if r["page_read"]["text"] else None
        )
        final, corrections = fp.patch(r["page_read"]["text"] or "", voted, page_model)
        if (
            fp.cluster(boxes) != r["regions"]["merged"]
            or voted != [v for c in r["crops"] for v in c.get("voted") or []]
            or (final, corrections) != (r["final_text"], r["corrections"])
        ):
            bad.append(f"page {f.name}: regions, votes or patched text differ")
    with tempfile.TemporaryDirectory() as tmp:
        for b in BOOKS:
            out = Path(tmp) / str(b)
            asm.assemble(
                "haiku#1",
                "haiku",
                work,
                b,
                out,
                base["assembled"]["config"],
                allow_missing=True,
            )
            for name, sha in base["assembled"]["books"][str(b)].items():
                if hashlib.sha256((out / name).read_bytes()).hexdigest() != sha:
                    bad.append(f"book {b} {name} differs from the v4 baseline assembly")
    now = measure(work, base["config"])
    for k in ("pilot", "pages_done"):
        if now[k] != base[k]:
            bad.append(f"{k}: {now[k]} != baseline {base[k]}")
    for k in ("page_costs", "sectioning_costs"):
        now[k].pop("tokens")
        if now[k] != base[k]:
            bad.append(f"{k}: {now[k]} != baseline {base[k]}")
    print(
        "\n".join(bad)
        or f"baseline reproduced: {now['pages_done']} pages, 3 books, pilot, costs"
    )
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "command",
        choices=["smoke", "pilot", "full", "assemble", "prompts", "compare", "verify"],
    )
    ap.add_argument("reader", nargs="?")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument(
        "--fallback",
        metavar="READER2",
        help="page reader for pages READER's output filter refuses",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="assemble from cached labels; any model call fails",
    )
    ap.add_argument(
        "--allow-missing",
        action="store_true",
        help="assemble although some pages were lost",
    )
    a = ap.parse_args()
    if not a.reader and a.command != "verify":
        ap.error("READER is required")
    n = names(a.reader, a.fallback) if a.reader else None
    globals()[f"cmd_{a.command}"](n, a)


if __name__ == "__main__":
    main()
