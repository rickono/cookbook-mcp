"""Fail-closed admission and launcher policy; kernel enforcement is tested separately."""

import importlib.util
from pathlib import Path

import pytest

from cookbook import ocr_limits


def test_native_refusal_before_ocr_side_effects(monkeypatch, tmp_path):
    from cookbook import extract, ocr

    monkeypatch.setattr(ocr_limits.sys, "platform", "darwin")
    monkeypatch.setenv("COOKBOOK_OCR_SANDBOX", "1")
    monkeypatch.setattr(
        ocr, "engine_config", lambda *_: pytest.fail("engine was invoked")
    )
    with pytest.raises(ocr_limits.OcrIsolationError, match="resource-isolated"):
        ocr.ocr_page(None, "PDF", 1, tmp_path / "cache", "", None, None)
    assert not (tmp_path / "cache").exists()
    with pytest.raises(ocr_limits.OcrIsolationError):
        ocr.process_image(None, tmp_path, None)
    with pytest.raises(ocr_limits.OcrIsolationError):
        ocr.recognize(None, tmp_path, None, 1)
    monkeypatch.setattr(
        extract, "PdfReader", lambda *_: pytest.fail("PDF parser was invoked")
    )
    with pytest.raises(ocr_limits.OcrIsolationError):
        extract.paged(None, "PDF", "", tmp_path)


@pytest.mark.parametrize(
    "file,value",
    [
        ("memory.max", "max"),
        ("memory.max", str(ocr_limits.MAX_MEMORY + 1)),
        ("memory.swap.max", "1"),
        ("pids.max", "max"),
        ("pids.max", "65"),
        ("cpu.max", "max 100000"),
        ("cpu.max", "200001 100000"),
        ("cpu.max", "0 0"),
    ],
)
def test_unlimited_or_excessive_kernel_limits_rejected(tmp_path, file, value):
    for name, text in {
        "memory.max": "67108864",
        "memory.swap.max": "0",
        "pids.max": "12",
        "cpu.max": "50000 100000",
    }.items():
        (tmp_path / name).write_text(text)
    (tmp_path / file).write_text(value)
    with pytest.raises(ocr_limits.OcrIsolationError):
        ocr_limits.kernel_limits(tmp_path)


def launcher():
    path = Path(__file__).resolve().parents[1] / "scripts/ocr_sandbox.py"
    spec = importlib.util.spec_from_file_location("ocr_sandbox_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refused_preflight_cannot_run_payload_or_create_output(monkeypatch, tmp_path):
    mod = launcher()
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("Docker unavailable")

    monkeypatch.setattr(mod, "docker", unavailable)
    with pytest.raises(RuntimeError, match="unavailable"):
        mod.run_job("unused", tmp_path / "output", ["false"])
    assert len(calls) == 1 and calls[0][0] == "context"
    assert not (tmp_path / "output").exists()


def test_excessive_policy_request_fails_before_docker(monkeypatch, tmp_path):
    mod = launcher()
    monkeypatch.setattr(mod, "preflight", lambda: pytest.fail("contacted Docker"))
    for settings in [
        dict(memory=4 * 1024**3),
        dict(pids=128),
        dict(cpus=3),
        dict(seconds=301),
    ]:
        with pytest.raises(ValueError):
            mod.run_job("unused", tmp_path / "output", ["false"], **settings)
