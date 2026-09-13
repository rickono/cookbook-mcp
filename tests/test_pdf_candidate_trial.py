"""Synthetic checks for trial scoring: never mistake a different quantity for a fix."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pdf_candidate_trial", Path(__file__).parents[1] / "scripts/pdf_candidate_trial.py"
)
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


def test_fraction_normalization_keeps_mixed_number_boundaries():
    assert trial.probe_present("Use 1½ cups water", "1 1/2 cups water")
    assert trial.probe_present("½ teaspoon salt", "1/2 teaspoon salt")
    assert not trial.probe_present("11/2 teaspoon salt", "1/2 teaspoon salt")
    assert not trial.probe_present("¾ teaspoon salt", "1/4 teaspoon salt")
    assert not trial.probe_present("15g salt", "5g salt")


def test_quantity_disagreement_includes_attached_units_and_repeated_tokens():
    assert trial.triage({"a": "5g salt", "b": "8g salt"})["numeric_token_disagreement"]
    assert trial.triage({"a": "2 cups 2 cups", "b": "2 cups"})[
        "numeric_token_disagreement"
    ]


@pytest.mark.parametrize("text", ["", "5g salt", "unreadable", "1/2 cup water"])
def test_candidate_agreement_never_accepts_text(text):
    result = trial.triage({"native": text, "ocr": text})
    assert not result["numeric_token_disagreement"]
    assert result["decision"] == "review_required"


def test_suspicious_quantity_forms_are_reported_without_rewriting():
    source = "V2 cup oil; V4 teaspoon salt; Sg tamari; 6% cups water"
    assert trial.triage({"native": source})["suspicious_quantity_forms"]["native"] == [
        "V2",
        "V4",
        "Sg",
        "6%",
    ]


def test_comparison_refuses_before_opening_inputs(monkeypatch, tmp_path):
    from cookbook import ocr_limits

    def refuse():
        raise RuntimeError("admission refused")

    monkeypatch.setattr(ocr_limits, "require_ocr_limits", refuse)
    with pytest.raises(RuntimeError, match="admission refused"):
        trial.compare(tmp_path / "missing.json", tmp_path)
    assert not list(tmp_path.iterdir())
