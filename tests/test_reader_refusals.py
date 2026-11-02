"""Refusals are terminal evidence, never a reason for another provider or prompt."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts/reader_bench"))

import assemble
import pipeline
import production
import readers


@pytest.mark.parametrize("response", ["policy", "text"])
def test_refusal_does_not_retry_the_provider(tmp_path, monkeypatch, response):
    calls = []

    def backend(*args):
        calls.append(args)
        if response == "policy":
            return (
                "",
                None,
                None,
                "API Error: Output blocked by content filtering policy",
            )
        return "I cannot provide the requested transcription.", None, None, None

    monkeypatch.setitem(readers.BACKENDS, "claude", backend)
    monkeypatch.setattr(readers.time, "sleep", lambda seconds: None)
    text, record = readers.call(tmp_path, "haiku#1", "Read this page", "synthetic.jpg")
    assert text is None and len(calls) == 1
    assert record["refused"] is True


@pytest.mark.parametrize("stage", ["page", "region", "crop"])
def test_refused_page_gets_no_further_provider_or_prompt(tmp_path, monkeypatch, stage):
    calls = []
    refused = []
    prompts = {
        "page": pipeline.PAGE_PROMPT,
        "region": pipeline.REGION_PROMPT,
        "crop": pipeline.CROP_PROMPT,
    }

    def call(out, reader, prompt, image):
        assert not refused, "another model/prompt was attempted after a refusal"
        calls.append((reader, prompt))
        if prompt == prompts[stage]:
            refused.append(True)
            return None, {
                "model": reader,
                "errors": ["API Error: Output blocked by content filtering policy"],
            }
        text = (
            "Soup\n2 onions"
            if prompt == pipeline.PAGE_PROMPT
            else json.dumps(
                {"regions": [{"label": "amount", "box": [0.1, 0.1, 0.6, 0.6]}]}
            )
        )
        return text, {"model": reader, "errors": []}

    monkeypatch.setattr(readers, "call", call)
    monkeypatch.setattr(pipeline, "READERS", ["haiku#1", "haiku#2", "haiku#3"])
    monkeypatch.setattr(pipeline, "FALLBACK", "luna#fallback")
    monkeypatch.setattr(pipeline, "guarded_crop", lambda *args: {"image": "crop.jpg"})
    rec = pipeline.run_page(
        tmp_path,
        7,
        1,
        {"image": "synthetic.jpg", "sha256": "a" * 64, "source_sha256": "b" * 64},
    )
    assert rec["refused"] is True and rec["final_text"] == ""
    assert all(reader != "luna#fallback" for reader, _ in calls)


def test_production_resume_never_retries_a_recorded_refusal(tmp_path, monkeypatch):
    n = production.config(tmp_path)
    failure = production.failure_file(n, 7, 1)
    failure.parent.mkdir(parents=True)
    failure.write_text(
        json.dumps(
            {
                "book": 7,
                "page": 1,
                "attempts": [
                    {
                        "page_read": {
                            "text": None,
                            "calls": [
                                {
                                    "model": "haiku#1",
                                    "errors": [
                                        "API Error: Output blocked by content filtering policy"
                                    ],
                                }
                            ],
                        }
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(
        pipeline, "run_page", lambda *args: pytest.fail("refusal retried")
    )
    production.run_book(n, 7, [{"physical_page": 1}], workers=1)


def test_old_false_refusal_of_authored_prose_is_not_terminal():
    assert not readers.has_refusal(
        {
            "page_read": {
                "calls": [
                    {
                        "model": "haiku#1",
                        "errors": ["refusal: Copyrighted by Imaginary Kitchen."],
                    }
                ]
            }
        }
    )


def test_label_refusal_is_not_retried(tmp_path, monkeypatch):
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        return None, {
            "model": "haiku#1",
            "errors": ["API Error: Output blocked by content filtering policy"],
        }

    monkeypatch.setattr(readers, "call", call)
    rec = assemble.label_page(
        "haiku#1", tmp_path, {1: {"final_text": "Soup"}}, 1, tmp_path
    )
    assert len(calls) == 1 and rec["label"] is None


def test_cached_fallback_text_is_not_reused_or_labelled(tmp_path, monkeypatch):
    rec = {
        "book": 7,
        "page": 1,
        "final_text": "BLOCKED FALLBACK TEXT",
        "page_read": {
            "text": "BLOCKED FALLBACK TEXT",
            "calls": [
                {
                    "model": "haiku#1",
                    "errors": ["API Error: Output blocked by content filtering policy"],
                },
                {"model": "luna#fallback", "errors": []},
            ],
        },
        "regions": {},
        "crops": [],
        "corrections": [],
    }
    pages = tmp_path / "pages"
    pages.mkdir()
    path = pages / "b7-p001.json"
    raw = json.dumps(rec)
    path.write_text(raw)
    monkeypatch.setattr(
        readers, "call", lambda *a, **kw: pytest.fail("cached refusal read")
    )
    safe = pipeline.run_page(tmp_path, 7, 1)
    assert safe["final_text"] == "" and safe["page_read"]["text"] is None
    assert path.read_text() == raw, "original evidence must remain intact"
    label = assemble.label_page("haiku#1", tmp_path, {1: rec}, 1, tmp_path)
    assert label["label"]["blocks"] == [] and assemble.lines_of(rec) == []
