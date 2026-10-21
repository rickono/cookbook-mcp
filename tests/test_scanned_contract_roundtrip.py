"""The reader pipeline's candidate (#48) passes the scanned import (#47) unchanged.

Reuses the production-transcription test's synthetic world: injected readers, no model
calls, no rendering, no OCR.
"""

from test_production_transcription import SHA, assembled, world  # noqa: F401

from cookbook.scanned import import_candidate, read_candidate


def test_pipeline_candidate_imports_with_markers_and_page_statuses(world, monkeypatch):  # noqa: F811
    result = import_candidate(
        read_candidate(assembled(world, monkeypatch)),
        source_id="pdf:" + SHA,
        source_sha256=SHA,
        physical_pages=4,
    )
    pages = [u for u in result["units"] if u["kind"] == "page"]
    assert [p["locator"]["status"] for p in pages] == [
        "transcribed",
        "transcribed",
        "blank",
        "failed",
    ]
    assert (
        pages[3]["text"].startswith("[unresolved ")
        and "failed_page]" in pages[3]["text"]
    )
    (recipe,) = [u for u in result["units"] if u["kind"] == "recipe"]
    assert recipe["locator"]["status"] == "has_unresolved"
    assert ": amount]" in recipe["text"]
    assert result["summary"]["coverage"] == {"transcribed": 2, "blank": 1, "failed": 1}
