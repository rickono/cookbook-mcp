#!/bin/sh
# Local-only complete POC workflow, against the explicitly approved existing snapshot.
set -eu
umask 077
if [ "$#" -ne 1 ]; then
  echo 'Usage: scripts/publish-fixture.sh /absolute/private-output-directory' >&2
  exit 2
fi
case "$1" in /*) ;; *) echo 'Output directory must be absolute.' >&2; exit 2;; esac
snapshot='/Users/rick/cookbook-mcp-data/snapshots/20260911T120144.142161Z/library'
mkdir -p "$1"
build_dir=$(mktemp -d "$1/.build-XXXXXXXX")
# Builder requires a new directory; remove only this empty, newly created directory.
rmdir "$build_dir"
export PYTHONPATH="$(pwd)/src"
# PDF/DjVu books (6, 9, 45) are deferred to the OCR follow-up; first trial is EPUB-only.
uv run python -m cookbook.cli build --snapshot "$snapshot" --books 5 40 --output "$build_dir" --ocr-cache "$1/ocr-cache"
uv run python -m cookbook.cli publish-local --build "$build_dir" --store "$1/store" --runtime "$1/runtime"
