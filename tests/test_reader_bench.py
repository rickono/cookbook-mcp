"""Synthetic checks of the reader benchmark's voting, naming and pricing; no model calls."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts/reader_bench"))

import bench
import costs
import pipeline
import readers

R = [f"claude:claude-haiku-5-5#{k}" for k in (1, 2, 3)]


def test_crop_majority_corrects_quantity_and_supersedes_own_page_read():
    voted = pipeline.vote(
        {R[0]: "1⅓ cups flour", R[1]: "1⅓ cups flour", R[2]: "1½ cups flour"}
    )
    text, corrections = pipeline.patch("Flour\n1½ cups flour", voted, R[0])
    assert text == "Flour\n1⅓ cups flour"
    assert corrections[0]["voters"] == 3 and corrections[0]["why"] == ["quantity"]


def test_three_way_tie_keeps_page_read():
    voted = pipeline.vote(
        {R[0]: "½ cup sugar", R[1]: "⅓ cup sugar", R[2]: "¼ cup sugar"}
    )
    assert voted[0]["tie"]
    text, _ = pipeline.patch("¾ cup sugar", voted, R[0])
    assert text == "¾ cup sugar"


def test_missing_reading_counts_against_change():
    voted = pipeline.vote({R[1]: "2 eggs", R[2]: "2 eggs"})
    voted[0]["of"] = 3  # the third crop reading failed
    text, corrections = pipeline.patch("3 eggs", voted, "other#1")
    assert text == "3 eggs" and corrections[0]["rejected"]


def test_config_names_follow_earlier_cells():
    assert (
        bench.names("claude:claude-haiku-5-5")["config"]
        == "pipeline-claude-haiku-5-5-x3-a4"
    )
    n = bench.names("codex:gpt-6-luna@low")
    assert n["config"] == "pipeline-gpt-6-luna--low-x3-a4"
    assert n["samples"][2] == "codex:gpt-6-luna@low#3"
    assert readers.parse("haiku#2") == ("claude", "claude-haiku-5-5", None)
    with pytest.raises(ValueError):
        readers.parse("gemini:flash")


def test_list_cost_uses_price_table_and_refuses_unknown_readers():
    t = {
        "input_tokens": 2,
        "cache_creation_input_tokens": 1000,
        "cache_read_input_tokens": 0,
        "output_tokens": 2000,
    }
    assert costs.list_cost(R[0], t) == pytest.approx(
        (2 * 0.10 + 1000 * 0.10 + 2000 * 0.50) / 1e6
    )
    with pytest.raises(SystemExit):
        costs.list_cost("claude:claude-unpriced#1", t)


@pytest.mark.parametrize(
    ("error", "used"),
    [
        ("API Error: Output blocked by content filtering policy", True),
        ("timeout 300s", False),
    ],
)
def test_fallback_reads_only_pages_the_output_filter_refused(
    tmp_path, monkeypatch, error, used
):
    def call(out, reader, prompt, image, **kw):
        if prompt != pipeline.PAGE_PROMPT:
            return "", {"model": reader, "errors": []}  # no quantity regions
        if reader == "luna#fallback":
            return "Glossary\nACHIOTE PASTE", {"model": reader, "errors": []}
        return None, {"model": reader, "errors": [error] * 3}

    monkeypatch.setattr(pipeline.rd, "call", call)
    monkeypatch.setattr(
        pipeline,
        "image_meta",
        lambda b, p: {"image": "x.jpg", "sha256": "s", "source_sha256": "t"},
    )
    monkeypatch.setattr(pipeline, "READERS", R)
    monkeypatch.setattr(pipeline, "FALLBACK", "luna#fallback")
    rec = pipeline.run_page(tmp_path, 81, 382)
    calls = rec["page_read"]["calls"]
    assert (rec["final_text"] == "Glossary\nACHIOTE PASTE") is used
    assert len(calls) == (2 if used else 1)
    assert calls[-1].get("fallback_for") == ("output filter" if used else None)
