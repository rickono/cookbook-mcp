"""Production transcription of any registered book: synthetic pages, injected render, reader and
crop. No model calls, no helper, no page images; the private data area is never touched."""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts/reader_bench"))

import assemble
import bench
import pipeline
import production
import readers

BOOK, SHA = 7, "a" * 64
HAIKU = [f"claude:claude-haiku-5-5#{k}" for k in (1, 2, 3)]
LUNA = "codex:gpt-6-luna@low#fallback"
# 2000 output tokens at $0.50/M is $0.001 per call for both readers (prices.json)
TOKENS = {
    "claude": {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 2000,
    },
    "codex": {"input_tokens": 0, "output_tokens": 2000},
}
PAGES = {  # p3 is blank (only empty responses), p4 always times out
    1: "BREAD\n1½ cups flour\n¾ cup sugar",
    2: "Mix and bake.",
}
CROP = {
    HAIKU[0]: "1⅓ cups flour\n½ cup sugar",
    HAIKU[1]: "1⅓ cups flour\n⅓ cup sugar",
    HAIKU[2]: "1½ cups flour\n¼ cup sugar",
}
LABELS = {
    "BREAD": {
        "printed_page": "12",
        "page_kinds": ["recipe"],
        "blocks": [
            {"from": 1, "to": 1, "section_title": "Bread", "section_kind": "recipe",
             "continues_previous_page": False, "part": "title"},
            {"from": 2, "to": 3, "section_title": "Bread", "section_kind": "recipe",
             "continues_previous_page": False, "part": "ingredients"},
        ],
        "references": [],
    },
    "Mix and bake.": {
        "printed_page": "13",
        "page_kinds": ["recipe"],
        "blocks": [
            {"from": 1, "to": 1, "section_title": "Bread", "section_kind": "recipe",
             "continues_previous_page": True, "part": "instructions"},
        ],
        "references": [],
    },
}  # fmt: skip


def ok(reader, text):
    return text, {
        "model": reader,
        "seconds": 1.0,
        "attempt": 1,
        "tokens": TOKENS[reader.split(":")[0]],
        "cost_usd": None,
        "errors": [],
    }


class Fakes:
    """The injected world: a registered 4-page book, its guarded renders and crops, the readers."""

    def __init__(self):
        self.calls, self.renders, self.stop_on = [], [], None

    def render(self, book, start, end):
        self.renders.append((book, start, end))
        return [
            {
                "physical_page": p,
                "image": f"/synthetic/b{book}-p{p}.jpg",
                "sha256": f"{p:064x}",
                "source_sha256": SHA,
                "bytes": 1,
                "pixels": [1600, 2300],
            }
            for p in range(start, end + 1)
        ]

    def crop(self, out, book, page, source_sha, box, n):
        assert source_sha == SHA
        return {
            "image": f"/synthetic/crop-b{book}-p{page}-r{n}.jpg",
            "sha256": f"{page:062x}c{n}",
            "pixels": [2400, 1200],
            "long_edge": 2400,
            "request": f"detail-requests/b{book}-p{page:03d}-r{n}.json",
        }

    def call(self, out, reader, prompt, image, **kw):
        if readers.STOP.is_set():
            return None, {"model": reader, "errors": ["stopped"]}
        page = int(re.search(r"-p(\d+)", image).group(1)) if image else None
        self.calls.append((reader, prompt[:20], page))
        if prompt == pipeline.PAGE_PROMPT:
            if page == self.stop_on:
                readers.STOP.set()
                return None, {"model": reader, "errors": ["usage limit reached"]}
            if page == 2 and reader != LUNA:
                return None, {
                    "model": reader,
                    "errors": ["API Error: Output blocked by content filtering policy"],
                }
            if page == 3:
                return None, {"model": reader, "errors": ["empty response"] * 3}
            if page == 4:
                return None, {"model": reader, "errors": ["timeout 300s"] * 3}
            return ok(reader, PAGES[page])
        if prompt == pipeline.REGION_PROMPT:
            box = [0.1, 0.2, 0.6, 0.5] if page == 1 else None
            return ok(
                reader,
                json.dumps({"regions": [{"label": "q", "box": box}] if box else []}),
            )
        if prompt == pipeline.CROP_PROMPT:
            return ok(reader, CROP[reader])
        this = prompt.split("THIS PAGE (label these):\n")[1].split("\n\nNEXT PAGE")[0]
        first = this.split("\n")[0].removeprefix("1: ")
        empty = {"printed_page": None, "page_kinds": [], "blocks": [], "references": []}
        return ok(reader, json.dumps(LABELS.get(first, empty)))


@pytest.fixture
def world(tmp_path, monkeypatch):
    fakes = Fakes()
    readers.STOP.clear()
    monkeypatch.setattr(pipeline.rd, "call", fakes.call)
    monkeypatch.setattr(pipeline, "guarded_crop", fakes.crop)
    monkeypatch.setattr(
        pipeline, "image_meta", lambda b, p: pytest.fail("frozen images")
    )
    monkeypatch.setattr(assemble, "EXP", tmp_path / "frozen-benchmark-must-not-be-read")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps({"books": [{"book_id": BOOK, "sha256": SHA, "physical_pages": 4}]})
    )
    fakes.registry = registry
    fakes.n = production.config(tmp_path / "production")
    fakes.reg = production.registered(registry)
    yield fakes
    readers.STOP.clear()


def transcribe(w, **kw):
    return production.transcribe(w.n, [BOOK], w.reg, workers=1, render=w.render, **kw)


def test_any_registered_book_is_transcribed_over_its_full_page_range(world):
    [progress] = transcribe(world)
    assert world.renders == [(BOOK, 1, 4)]
    assert world.n["config"] == "pipeline-claude-haiku-5-5-x3-fb-gpt-6-luna--low-a4"
    pages = world.n["work"] / "pages"
    assert sorted(p.name for p in pages.iterdir()) == ["b7-p001.json", "b7-p002.json"]
    p1 = json.loads((pages / "b7-p001.json").read_text())
    assert p1["final_text"] == "BREAD\n1⅓ cups flour\n¾ cup sugar"
    p2 = json.loads((pages / "b7-p002.json").read_text())
    assert p2["page_read"]["calls"][-1]["model"] == LUNA
    # page calls: p1 1+3+3, p2 3 haiku + 1 luna, p3 and p4 3 region calls on each of 2 passes
    assert progress == {
        "book": BOOK,
        "pages": 4,
        "transcribed": 2,
        "blank": 1,
        "failed": 1,
        "pending": 0,
        "page_list_usd": 0.023,
        "sectioning_list_usd": 0.0,
        "list_usd": 0.023,
    }


def test_interrupted_run_resumes_without_repaying_finished_pages(world):
    world.stop_on = 2  # a usage limit on page 2's page read
    with pytest.raises(SystemExit, match="rerun the same command to resume"):
        transcribe(world)
    assert {p for _, _, p in world.calls} == {1, 2}
    readers.STOP.clear()
    world.stop_on, world.calls = None, []
    [progress] = transcribe(world)
    assert 1 not in {p for _, _, p in world.calls}
    assert world.renders == [(BOOK, 1, 4)]  # page images are rendered once
    # the same pages and list price as an uninterrupted run: nothing was paid twice
    assert (progress["transcribed"], progress["list_usd"]) == (2, 0.023)


def test_rerun_retries_failed_pages_but_not_blank_ones(world):
    transcribe(world)
    world.calls = []
    [progress] = transcribe(world)
    assert {p for _, _, p in world.calls} == {4}
    assert (progress["blank"], progress["failed"]) == (1, 1)


def cli(world, monkeypatch, *argv):
    monkeypatch.setattr(production, "REGISTRY", world.registry)
    monkeypatch.setattr(production, "PROD", world.n["root"].parent)
    monkeypatch.setattr(production, "helper_render", world.render)
    production.main(list(argv))


def test_run_refuses_before_any_render_or_call_when_the_sandbox_doctor_refuses(
    world, monkeypatch
):
    def refuse():
        sys.exit("scripts/ocr_sandbox.py doctor refused")

    monkeypatch.setattr(bench, "doctor", refuse)
    with pytest.raises(SystemExit, match="doctor refused"):
        cli(world, monkeypatch, "run", str(BOOK))
    assert world.renders == [] and world.calls == []
    assert not world.n["root"].exists()


def test_unregistered_books_are_refused(world, monkeypatch):
    monkeypatch.setattr(bench, "doctor", lambda: None)
    with pytest.raises(SystemExit, match="not registered: 8"):
        cli(world, monkeypatch, "run", "8")
    assert world.renders == [] and world.calls == []


def fake_record(n, command):
    """bench.record without its git and reader --version subprocesses."""
    f = n["work"] / "manifest.json"
    m = (
        json.loads(f.read_text())
        if f.exists()
        else {"reader_samples": n["samples"], "fallback": n["fallback"], "runs": []}
    )
    m["runs"].append(
        {"command": command, "code_sha": bench.code_sha(), "repo_head": "abc1234"}
    )
    f.write_text(json.dumps(m))


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def is_sha(v):
    return isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) is not None


def assembled(world, monkeypatch, *flags):
    """The synthetic book's page 4 failed, so it is assembled with --allow-missing."""
    monkeypatch.setattr(bench, "record", fake_record)
    transcribe(world)
    cli(world, monkeypatch, "assemble", str(BOOK), "--allow-missing", *flags)
    return world.n["root"] / "books" / str(BOOK) / "candidate"


def test_assemble_writes_a_scanned_candidate_bound_to_its_source_and_files(
    world, monkeypatch
):
    out = assembled(world, monkeypatch)
    c = json.loads((out / "candidate.json").read_text())
    assert {
        k: c[k] for k in ("version", "book_id", "source", "config_id", "reader")
    } == {
        "version": "scanned-candidate.v1",
        "book_id": BOOK,
        "source": {"sha256": SHA, "format": "PDF", "physical_pages": 4},
        "config_id": "pipeline-claude-haiku-5-5-x3-fb-gpt-6-luna--low-a4",
        "reader": {
            "spec": "claude:claude-haiku-5-5",
            "samples": 3,
            "sample_labels": HAIKU,
            "fallback": LUNA,
        },
    }
    assert (c["assembler"], c["approval"], c["repo_head"]) == (
        "v4",
        "unapproved",
        "abc1234",
    )
    assert sorted(c["prompts_sha256"]) == ["crop", "page", "region", "sectioning"]
    assert all(is_sha(v) for v in [*c["prompts_sha256"].values(), c["code_sha256"]])
    assert c["coverage"] == {
        "pages_total": 4,
        "transcribed": 2,
        "blank": 1,
        "failed": 1,
    }
    assert c["counts"] == {"sections": 1, "quantity_reviews": 1, "unresolved": 2}
    names = ["pages.jsonl", "quantity-review.jsonl", "sections.jsonl", "unresolved.jsonl",
             "vote-corrections.jsonl"]  # fmt: skip
    assert sorted(c["files"]) == names
    for name in names:
        data = (out / name).read_bytes()
        assert c["files"][name] == {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }


def test_candidate_pages_account_for_every_physical_page(world, monkeypatch):
    pages = rows(assembled(world, monkeypatch) / "pages.jsonl")
    assert [(p["physical_page"], p["status"]) for p in pages] == [
        (1, "transcribed"), (2, "transcribed"), (3, "blank"), (4, "failed"),
    ]  # fmt: skip
    p1, p2, p3, p4 = pages
    assert p1["text"] == "BREAD\n1⅓ cups flour\n¾ cup sugar"
    assert p1["text_sha256"] == hashlib.sha256(p1["text"].encode()).hexdigest()
    assert (p1["printed_page"], p1["section_ids"], p1["unresolved_ids"]) == (
        "12", ["7:bread"], ["u3"],
    )  # fmt: skip
    assert (p1["page_reader"], p2["page_reader"]) == (HAIKU[0], LUNA)
    assert p1["vote_correction_ids"] == ["7:p001:c0", "7:p001:c1"]
    assert p1["image_sha256"] == f"{1:064x}"
    assert p3["blank_evidence"] == {
        "rule": "page_read_empty_response",
        "attempts": 2,
        "page_read_errors": ["empty response"] * 6,
    }
    assert (p3["text"], p3["unresolved_ids"], p3["section_ids"]) == ("", [], [])
    assert (p4["text"], p4["blank_evidence"], p4["page_reader"]) == ("", None, None)
    assert (p4["unresolved_ids"], p4["section_ids"]) == (["u2"], [])


def test_candidate_sections_link_unresolved_items_to_their_parts(world, monkeypatch):
    # the failed and blank pages' "no printed text transcribed" graphic holders are gone
    [bread] = rows(assembled(world, monkeypatch) / "sections.jsonl")
    assert "status" not in bread  # the import derives it from unresolved counts
    assert (bread["id"], bread["kind"], bread["physical_pages"], bread["printed_pages"]) == (
        "7:bread", "recipe", [1, 2], ["12", "13"],
    )  # fmt: skip
    assert [(p["kind"], p["source_page"], p["unresolved_ids"]) for p in bread["parts"]] == [
        ("title", 1, []), ("ingredients", 1, ["u3"]), ("instructions", 2, []),
    ]  # fmt: skip
    assert bread["parts"][1] == {
        "kind": "ingredients",
        "source_page": 1,
        "text": "1⅓ cups flour\n¾ cup sugar",
        "description": None,
        "unresolved_ids": ["u3"],
    }


def test_candidate_unresolved_items_carry_code_box_and_review_link(world, monkeypatch):
    out = assembled(world, monkeypatch)
    box = [0.08, 0.18, 0.62, 0.52]  # the three agreeing boxes, padded by 0.02
    assert rows(out / "quantity-review.jsonl") == [
        {
            "id": "7:p001:crop0",
            "physical_page": 1,
            "box": box,
            "section_ids": ["7:bread"],
            "crop_sha256": f"{1:062x}c0",
            "fields_reviewed": ["1⅓ cups flour"],
            "remaining_uncertainty": ["¾ cup sugar"],
            "readers": HAIKU,
        }
    ]
    # the blank page's "page transcription failed" row (u1) is not unresolved content
    assert rows(out / "unresolved.jsonl") == [
        {
            "id": "u2",
            "section_id": None,
            "physical_page": 4,
            "field": "other",
            "code": "failed_page",
            "reason": "page transcription failed",
            "source_fragment": None,
            "box": [0, 0, 1, 1],
            "review_id": None,
            "crop_readings": [],
        },
        {
            "id": "u3",
            "section_id": "7:bread",
            "physical_page": 1,
            "field": "amount",
            "code": "amount",
            "reason": "crop readers did not reach a majority",
            "source_fragment": "¾ cup sugar",
            "box": box,
            "review_id": "7:p001:crop0",
            "crop_readings": ["¼ cup sugar", "½ cup sugar", "⅓ cup sugar"],
        },
    ]
    assert [r["id"] for r in rows(out / "vote-corrections.jsonl")] == [
        "7:p001:c0", "7:p001:c1",
    ]  # fmt: skip


def test_reassembly_from_the_caches_is_offline_and_byte_identical(world, monkeypatch):
    out = assembled(world, monkeypatch)
    first = {f.name: f.read_bytes() for f in out.iterdir()}
    world.calls = []
    try:
        cli(world, monkeypatch, "assemble", str(BOOK), "--allow-missing", "--offline")
    finally:
        readers.OFFLINE.clear()
    assert world.calls == []
    assert {f.name: f.read_bytes() for f in out.iterdir()} == first


def test_assemble_refuses_a_book_with_failed_pages_unless_allowed(world, monkeypatch):
    transcribe(world)
    with pytest.raises(SystemExit, match="1 pages not transcribed"):
        production.assemble_book(world.n, BOOK, world.reg[BOOK], 1, allow_missing=False)
    assert not (world.n["root"] / "books" / str(BOOK) / "candidate").exists()


def finished_elsewhere(world, monkeypatch, tmp_path):
    """The same config run and assembled in another work area, as the benchmark cell was."""
    monkeypatch.setattr(bench, "record", fake_record)
    other = production.config(tmp_path / "benchmark")
    production.transcribe(other, [BOOK], world.reg, workers=1, render=world.render)
    fake_record(other, "full")
    production.assemble_book(other, BOOK, world.reg[BOOK], 1, allow_missing=True)
    world.calls, world.renders = [], []
    return other


def frozen_images(book):
    return [
        {k: r[k] for k in ("image", "physical_page", "sha256", "source_sha256")}
        for r in Fakes().render(book, 1, 4)
    ]


def candidate_files(n):
    out = n["root"] / "books" / str(BOOK) / "candidate"
    return {f.name: f.read_bytes() for f in out.iterdir() if f.name != "candidate.json"}


def test_seeded_work_area_assembles_offline_without_repaying_any_page(
    world, monkeypatch, tmp_path
):
    other = finished_elsewhere(world, monkeypatch, tmp_path)
    production.seed(world.n, [BOOK], world.reg, other["work"], images=frozen_images)
    assert production.progress(world.n, BOOK, world.reg[BOOK]) == {
        **production.progress(other, BOOK, world.reg[BOOK]),
        "transcribed": 2,
        "blank": 1,
        "failed": 1,
        "pending": 0,
    }
    try:
        cli(world, monkeypatch, "assemble", str(BOOK), "--allow-missing", "--offline")
    finally:
        readers.OFFLINE.clear()
    assert world.calls == [] and world.renders == []
    assert candidate_files(world.n) == candidate_files(other)
    m = json.loads((world.n["work"] / "manifest.json").read_text())
    assert m["seeded"][0]["from"] == str(other["work"])
    assert m["seeded"][0]["books"] == {
        str(BOOK): {"pages": 2, "labels": 4, "failures": 2}
    }


def test_seed_refuses_a_work_dir_read_by_another_reader_config(
    world, monkeypatch, tmp_path
):
    other = finished_elsewhere(world, monkeypatch, tmp_path)
    m = json.loads((other["work"] / "manifest.json").read_text())
    (other["work"] / "manifest.json").write_text(json.dumps({**m, "fallback": None}))
    with pytest.raises(SystemExit, match="not read by the production config"):
        production.seed(world.n, [BOOK], world.reg, other["work"], images=frozen_images)
    assert not world.n["root"].exists()


def test_seed_refuses_page_records_read_from_other_page_images(
    world, monkeypatch, tmp_path
):
    other = finished_elsewhere(world, monkeypatch, tmp_path)

    def other_edition(book):
        return [{**r, "sha256": "f" * 64} for r in frozen_images(book)]

    with pytest.raises(SystemExit, match="another page image"):
        production.seed(world.n, [BOOK], world.reg, other["work"], images=other_edition)
    assert not world.n["root"].exists()


def test_reseeding_is_idempotent_and_never_overwrites_production_work(
    world, monkeypatch, tmp_path
):
    other = finished_elsewhere(world, monkeypatch, tmp_path)
    production.seed(world.n, [BOOK], world.reg, other["work"], images=frozen_images)
    production.seed(world.n, [BOOK], world.reg, other["work"], images=frozen_images)
    page = world.n["work"] / "pages" / "b7-p001.json"
    page.write_text(page.read_text().replace("BREAD", "BRED"))
    with pytest.raises(SystemExit, match="exists with other content"):
        production.seed(world.n, [BOOK], world.reg, other["work"], images=frozen_images)
    assert "BRED" in page.read_text()


def test_seed_command_takes_page_images_from_the_frozen_benchmark_inputs(
    world, monkeypatch, tmp_path
):
    other = finished_elsewhere(world, monkeypatch, tmp_path)
    frozen = tmp_path / "frozen-benchmark"
    (frozen / "inputs/books/7").mkdir(parents=True)
    (frozen / "inputs/books/7/images.json").write_text(json.dumps(frozen_images(BOOK)))
    monkeypatch.setattr(assemble, "EXP", frozen)
    cli(world, monkeypatch, "seed", str(BOOK), "--from", str(other["work"]))
    images = world.n["root"] / "books" / "7" / "images.json"
    assert json.loads(images.read_text()) == frozen_images(BOOK)
    assert production.progress(world.n, BOOK, world.reg[BOOK])["pending"] == 0
