"""Write one book's `scanned-candidate.v1` from its assembler v4 output and the pipeline work dir.

Runs after `assemble.build` and never changes its files. Code only: no model calls, no images.
The contract (one directory per book) is defined with the scanned import, ticket #47; this writer
adds what v4 does not record:

- the freeze identity: reader samples and fallback, prompt hashes, code hash, page coverage;
- page text and a page status, `transcribed`, `blank` (only with recorded evidence) or `failed`;
- a stable `code` per unresolved item, and the crop box and quantity review it came from;
- which section part each unresolved item sits in.

The "no printed text transcribed" graphic part v4 gives a page without text is dropped (a failed
page is unresolved content, not a picture), and so is the failed-page item of a blank page.
"""

import hashlib
import json
import shutil

import assemble as asm
import pipeline as fp

from cookbook.scanned import BLANK_RULE, EMPTY_RESPONSE, VERSION
from cookbook.storage import canonical

WHOLE_PAGE = [0, 0, 1, 1]
CODES = {
    "page transcription failed": "failed_page",
    "section labelling failed; page kept as one untitled block": "label",
    "crop readers did not reach a majority": "amount",
    "crop majority not confirmed per quantity; page read kept": "amount",
    "crop majority not matched to a page-read line; not applied": "amount",
    "quantity crop unavailable or unconfirmed; page read kept": "other",
}
FAILED = "page transcription failed"
ASSEMBLY = [
    "sections.jsonl",
    "page-ledger.jsonl",
    "quantity-review.jsonl",
    "corrections.jsonl",
    "unresolved.jsonl",
    "progress.json",
    "report.md",
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def blank_evidence(failure, rounds):
    """The production blank rule: `rounds` recorded passes whose page-read errors are all empty
    responses. Returns the evidence to store, or None (the page is then failed)."""
    attempts = (failure or {}).get("attempts") or []
    errors = [e for a in attempts for c in a["page_read"]["calls"] for e in c["errors"]]
    if len(attempts) < rounds or not errors or any(e != EMPTY_RESPONSE for e in errors):
        return None
    return {
        "rule": BLANK_RULE,
        "attempts": len(attempts),
        "page_read_errors": errors,
    }


def refuse(message):
    raise SystemExit(f"candidate refused: {message}")


def read_assembly(assembly):
    """The v4 files, checked against the digests freeze.json recorded for them."""
    freeze = json.loads((assembly / "freeze.json").read_text())
    if sorted(freeze["files"]) != sorted(ASSEMBLY):
        refuse(f"{assembly} is not an assembler {asm.ASSEMBLER} output")
    for name, want in freeze["files"].items():
        data = (assembly / name).read_bytes()
        if {"sha256": sha256(data), "bytes": len(data)} != want:
            refuse(f"{assembly / name} changed after assembly")

    def jl(name):
        return [json.loads(x) for x in (assembly / name).read_text().splitlines()]

    return freeze, {
        n.removesuffix(".jsonl"): jl(n) for n in ASSEMBLY if n.endswith(".jsonl")
    }


def identity(work):
    """Reader, prompts and code of the run that produced the work dir's last assembly."""
    m = json.loads((work / "manifest.json").read_text())
    samples, last = m["reader_samples"], m["runs"][-1]
    specs = {s.split("#")[0] for s in samples}
    if len(samples) != 3 or len(specs) != 1:
        refuse(f"{work} was not read by three samples of one reader")
    return {
        "reader": {
            "spec": specs.pop(),
            "samples": len(samples),
            "sample_labels": samples,
            "fallback": m["fallback"],
        },
        "assembler": asm.ASSEMBLER,
        "prompts_sha256": {
            k: sha256(p.encode())
            for k, p in (
                ("page", fp.PAGE_PROMPT),
                ("region", fp.REGION_PROMPT),
                ("crop", fp.CROP_PROMPT),
                ("sectioning", asm.PROMPT),
            )
        },
        "code_sha256": sha256(canonical(last["code_sha"])),
        "repo_head": last.get("repo_head"),
    }


def link_unresolved(unresolved, reviews, keep):
    """Give each kept item its code, box and review. v4 writes an amount item for each entry of a
    crop's remaining_uncertainty, page by page in crop order, so the two lists pair up in order."""
    amount = {}
    for u in unresolved:
        if u["reason"] not in CODES:
            refuse(f"unknown unresolved reason {u['reason']!r}")
        if CODES[u["reason"]] == "amount":
            amount.setdefault(u["physical_page"], []).append(u)
    link = {}
    for r in reviews:
        for entry in r["remaining_uncertainty"]:
            queue = amount.get(r["physical_page"]) or refuse(
                f"{r['id']}: no unresolved row"
            )
            u = queue.pop(0)
            if u["source_fragment"] not in (None, entry):
                refuse(f"{u['id']} does not match {r['id']}")
            link[u["id"]] = r
    if any(amount.values()):
        refuse("unresolved amounts without a quantity review")
    rows = []
    for u in unresolved:
        if not keep(u):
            continue
        r = link.get(u["id"])
        rows.append(
            {
                "id": u["id"],
                "section_id": u["section_id"],
                "physical_page": u["physical_page"],
                "field": u["field"],
                "code": CODES[u["reason"]],
                "reason": u["reason"],
                "source_fragment": u["source_fragment"],
                "box": r["request"]["box"] if r else u.get("box", WHOLE_PAGE),
                "review_id": r["id"] if r else None,
                "crop_readings": u.get("crop_readings") or [],
            }
        )
    return rows


def write(assembly, work, images, failures, out, blank_rounds):
    """images: the page universe (images.json rows); failures: {page: failure sidecar}."""
    freeze, v4 = read_assembly(assembly)
    book = freeze["book_id"]
    universe = [im["physical_page"] for im in images]
    if universe != list(range(1, len(images) + 1)):
        refuse("page images are not physical pages 1..N")
    if {im["source_sha256"] for im in images} != {freeze["source_sha256"]}:
        refuse("assembly and page images name different sources")
    if [r["physical_page"] for r in v4["page-ledger"]] != universe:
        refuse("the page ledger does not cover every page exactly once")

    records, status, evidence = {}, {}, {}
    for p in universe:
        f = work / "pages" / f"b{book}-p{p:03d}.json"
        rec = json.loads(f.read_text()) if f.exists() else None
        if rec and rec.get("final_text"):  # the assembler's own test for a failed page
            records[p], status[p] = rec, "transcribed"
        else:
            evidence[p] = blank_evidence(failures.get(p), blank_rounds)
            status[p] = "blank" if evidence[p] else "failed"

    unresolved = link_unresolved(
        v4["unresolved"],
        v4["quantity-review"],
        lambda u: not (u["reason"] == FAILED and status[u["physical_page"]] == "blank"),
    )
    by_page = {}
    for u in unresolved:
        by_page.setdefault(u["physical_page"], []).append(u)

    sections = []
    for s in v4["sections"]:
        parts = [
            {
                "kind": part["kind"],
                "source_page": part["source_page"],
                "text": part["text"],
                "description": part.get("description"),
                "unresolved_ids": [],
            }
            for part in s["parts"]
            if not (
                part["text"] is None and status[part["source_page"]] != "transcribed"
            )
        ]
        if parts:
            sections.append({**{k: s[k] for k in ("id", "kind", "title")}, "parts": parts,
                             **{k: s[k] for k in ("physical_pages", "printed_pages", "references")}})  # fmt: skip
    kept = {s["id"]: s for s in sections}
    for s in sections:
        s["references"] = [
            {**r, "target_section_id": r["target_section_id"] if r["target_section_id"] in kept else None}
            for r in s["references"]
        ]  # fmt: skip
    for u in unresolved:
        s = kept.get(u["section_id"])
        if s and u["source_fragment"]:
            part = next(
                (
                    part
                    for part in s["parts"]
                    if part["source_page"] == u["physical_page"]
                    and u["source_fragment"] in (part["text"] or "")
                ),
                None,
            )
            if part:
                part["unresolved_ids"].append(u["id"])

    reviews = []
    for r in v4["quantity-review"]:
        crop = records[r["physical_page"]]["crops"][int(r["id"].rsplit("crop", 1)[1])]
        if crop.get("sha256") != r["returned_sha256"]:
            refuse(f"{r['id']} does not match its page record's crop")
        reviews.append(
            {
                "id": r["id"],
                "physical_page": r["physical_page"],
                "box": r["request"]["box"],
                "section_ids": [
                    sid for sid in r["request"]["field_scope"] if sid in kept
                ],
                "crop_sha256": r["returned_sha256"],
                "fields_reviewed": r["fields_reviewed"],
                "remaining_uncertainty": r["remaining_uncertainty"],
                "readers": sorted(crop["readings"]),
            }
        )

    votes = {}
    for c in v4["corrections"]:
        votes.setdefault(c["physical_page"], []).append(c["id"])
    pages = []
    for row in v4["page-ledger"]:
        p = row["physical_page"]
        rec = records.get(p)
        text = rec["final_text"] if rec else ""
        pages.append(
            {
                "physical_page": p,
                "status": status[p],
                "text": text,
                "text_sha256": sha256(text.encode()),
                "image_sha256": row["sha256"],
                "printed_page": row["printed_page"],
                "section_ids": [sid for sid in row["section_ids"] if sid in kept],
                "unresolved_ids": [u["id"] for u in by_page.get(p, [])],
                "page_reader": rec["page_read"]["calls"][-1]["model"] if rec else None,
                "vote_correction_ids": votes.get(p, []),
                "blank_evidence": evidence.get(p),
            }
        )

    files = {
        "pages.jsonl": pages,
        "sections.jsonl": sections,
        "quantity-review.jsonl": reviews,
        "unresolved.jsonl": unresolved,
        "vote-corrections.jsonl": v4["corrections"],
    }
    blobs = {
        name: "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs).encode()
        for name, rs in files.items()
    }
    counts = {
        s: sum(1 for p in pages if p["status"] == s)
        for s in ("transcribed", "blank", "failed")
    }
    head = {
        "version": VERSION,
        "book_id": book,
        "source": {
            "sha256": freeze["source_sha256"],
            "format": "PDF",
            "physical_pages": len(universe),
        },
        "config_id": freeze["config_id"],
        **identity(work),
        "coverage": {"pages_total": len(universe), **counts},
        "counts": {
            "sections": len(sections),
            "quantity_reviews": len(reviews),
            "unresolved": len(unresolved),
        },
        "approval": "unapproved",
        "files": {
            n: {"sha256": sha256(b), "bytes": len(b)} for n, b in sorted(blobs.items())
        },
    }
    blobs["candidate.json"] = canonical(
        head
    )  # the candidate digest is this file's sha256

    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, b in blobs.items():
        (tmp / name).write_bytes(b)
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    return {
        "candidate_sha256": sha256(blobs["candidate.json"]),
        "coverage": head["coverage"],
        "counts": head["counts"],
    }
