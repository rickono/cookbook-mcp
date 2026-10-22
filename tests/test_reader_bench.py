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


@pytest.mark.parametrize(
    "text",
    [
        "A cook's note\n\nI can't wait to share this simple soup.\n2 onions",
        "Copyrighted 2026 by Imaginary Kitchen.\nAll rights reserved.",
    ],
)
def test_authored_prose_is_not_a_reader_refusal(tmp_path, monkeypatch, text):
    monkeypatch.setitem(
        readers.BACKENDS,
        "claude",
        lambda *args: (text, None, None, None),
    )
    monkeypatch.setattr(readers.time, "sleep", lambda seconds: None)
    result, record = readers.call(tmp_path, R[0], "Transcribe this page.", "page.jpg")
    assert result == text
    assert record["errors"] == []


@pytest.mark.parametrize(
    "text",
    [
        "I can't continue that transcription.",
        "Sorry, I cannot reproduce this page.",
        "A heading\nI am not able to provide the requested transcription.",
    ],
)
def test_actual_reader_refusals_remain_failed_calls(tmp_path, monkeypatch, text):
    monkeypatch.setitem(
        readers.BACKENDS,
        "claude",
        lambda *args: (text, None, None, None),
    )
    monkeypatch.setattr(readers.time, "sleep", lambda seconds: None)
    result, record = readers.call(tmp_path, R[0], "Transcribe this page.", "page.jpg")
    assert result is None
    assert len(record["errors"]) == 1
    assert record["refused"] is True
    assert all(error.startswith("refusal:") for error in record["errors"])


@pytest.mark.parametrize("patcher", [pipeline.patch, pipeline.reviewed_patch])
def test_crop_majority_corrects_quantity_and_supersedes_own_page_read(patcher):
    voted = pipeline.vote(
        {R[0]: "1⅓ cups flour", R[1]: "1⅓ cups flour", R[2]: "1½ cups flour"}
    )
    text, corrections = patcher("Flour\n1½ cups flour", voted, R[0])
    assert text == "Flour\n1⅓ cups flour"
    assert corrections[0]["voters"] == 3 and corrections[0]["why"] == ["quantity"]


@pytest.mark.parametrize("patcher", [pipeline.patch, pipeline.reviewed_patch])
def test_three_way_tie_keeps_page_read(patcher):
    voted = pipeline.vote(
        {R[0]: "½ cup sugar", R[1]: "⅓ cup sugar", R[2]: "¼ cup sugar"}
    )
    assert voted[0]["tie"]
    text, _ = patcher("¾ cup sugar", voted, R[0])
    assert text == "¾ cup sugar"


def test_overlapping_crop_votes_do_not_add_an_existing_ingredient_twice():
    voted = pipeline.vote(dict.fromkeys(R, "7g synthetic herb"))
    text, corrections = pipeline.reviewed_patch(
        "7g synthetic herb", voted + voted, R[0]
    )
    assert text == "7g synthetic herb"
    assert not any(c.get("added") for c in corrections)


def test_quantity_vote_matches_the_amount_line_instead_of_a_similar_heading():
    page = "Fragrant, peppery seed components\nMint\n1 part fragrant, peppery seed component"
    voted = pipeline.vote(dict.fromkeys(R, "1 part fragrant, peppery seed component"))
    text, corrections = pipeline.reviewed_patch(page, voted, R[0])
    assert text == page
    assert corrections == []


def test_authored_repeated_ingredients_remain_separate_occurrences():
    page = "First preparation\n7g synthetic herb\nSecond preparation\n7g synthetic herb"
    voted = pipeline.vote(dict.fromkeys(R, "7g synthetic herb\n7g synthetic herb"))
    text, _ = pipeline.reviewed_patch(page, voted + voted, R[0])
    assert text == page


def test_crop_majority_still_adds_a_missing_distinct_ingredient():
    voted = pipeline.vote(dict.fromkeys(R, "7g synthetic herb"))
    text, corrections = pipeline.reviewed_patch("2 onions", voted, R[0])
    assert text == "2 onions\n7g synthetic herb"
    assert corrections[0]["added"]


def test_review_crop_fragment_does_not_duplicate_part_of_an_instruction():
    sentence = "1. Add 7g synthetic herb and stir for 3 minutes."
    page = sentence + " Cook until fragrant and serve in warm bowls."
    voted = pipeline.vote(dict.fromkeys(R, sentence))
    text, corrections = pipeline.reviewed_patch(page, voted, R[0])
    assert text == page
    assert corrections == []


def test_review_crop_fragment_does_not_match_inside_another_number():
    page = "Mix 12g synthetic herb with onions and simmer until fragrant."
    voted = pipeline.vote(dict.fromkeys(R, "2g synthetic herb"))
    text, corrections = pipeline.reviewed_patch(page, voted, R[0])
    assert text == page + "\n2g synthetic herb"
    assert corrections[0]["added"]


@pytest.mark.parametrize("patcher", [pipeline.patch, pipeline.reviewed_patch])
def test_missing_reading_counts_against_change(patcher):
    voted = pipeline.vote({R[1]: "2 eggs", R[2]: "2 eggs"})
    voted[0]["of"] = 3  # the third crop reading failed
    text, corrections = patcher("3 eggs", voted, "other#1")
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
        ("API Error: Output blocked by content filtering policy", False),
        ("timeout 300s", False),
    ],
)
def test_fallback_never_retries_a_provider_policy_refusal(
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
