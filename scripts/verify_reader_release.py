#!/usr/bin/env python3
"""Explicit serving-only release selection: no discovery of OCR/ingestion tests."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = [
    "reader_release",
    "reader_http",
    "reader_session_races",
    "reader_content",
    "reader_original",
    "reader_raster",
    "reader_search",
    "reader_search_trial",
    "reader_updates",
    "reader_validation",
    "reader_personal",
    "reader_presentation",
    "owner_reports",
    "mcp",
    "dashboard",
    "library_auth",
    "hosted",
    "manifest_cache",
    "reports",
    "storage_conditions",
    "search_process",
    "rendering",
]
NODE = [
    "reader_session",
    "reader_content",
    "reader_original",
    "reader_search",
    "reader_updates",
    "reader_personal",
    "reader_presentation",
    "owner_reports",
    "image_viewer",
    "recipe_viewer",
]


def main():
    subprocess.run(
        ["uv", "run", "pytest", "-q", "-s", *[f"tests/test_{n}.py" for n in PYTHON]],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["node", "--test", *[f"tests/{n}.test.mjs" for n in NODE]],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
