"""Image candidate navigation over a synthetic chapter; no OCR or source books."""

import json
import sqlite3

import pytest

from conftest import fixture_build
from cookbook.library import Library
from cookbook.publication import Runtime, publish
from cookbook.storage import IntegrityError, LocalStore, digest_file


@pytest.fixture(params=[False, True], ids=["context", "legacy"])
def chapter_library(tmp_path, request):
    manifest, inputs = fixture_build(tmp_path / "build", count=2)
    db = sqlite3.connect(inputs["runtime/index.sqlite"])
    source = db.execute("select source_id from books where id='book-0'").fetchone()[0]
    ids = ["image-0"]
    for i in range(1, 55):
        image_id = f"chapter-image-{i}"
        ids.append(image_id)
        db.execute(
            "insert into images values(?,?,?,?,?)",
            (image_id, source, "assets/image", "chapter.xhtml", f"Other dish {i}"),
        )
    db.execute("update sections set images=? where id='section-0'", (json.dumps(ids),))
    if request.param:
        db.execute("drop table image_context")
    else:
        db.execute(
            "insert into image_context values(?,?,?)", ("image-0", "Beans", "section-0")
        )
    db.commit()
    db.close()
    index = next(e for e in manifest.files if e.path == "runtime/index.sqlite")
    index.sha256, index.size = digest_file(inputs[index.path])
    store = LocalStore(tmp_path / "store")
    runtime = Runtime(store, tmp_path / "runtime")
    publish(store, manifest, inputs, expected_version=None, activate=runtime.activate)
    return (
        Library(runtime),
        dict(
            publication_id=manifest.publication_id,
            book_id="book-0",
            source_id=source,
            section_id="section-0",
        ),
        request.param,
    )


def test_candidates_are_metadata_only_paginated_and_source_bound(chapter_library):
    lib, args, legacy = chapter_library

    # Discovery must not fetch assets, even when inspecting an entire chapter.
    def no_asset_reads(*args, **kwargs):
        pytest.fail("candidate discovery fetched image bytes")

    lib.cached = no_asset_reads
    candidates = []
    offset = 0
    while True:
        result = lib.list_images(**args, offset=offset, limit=20)
        assert result["citation"]["section_id"] == args["section_id"]
        assert result["association"] == "epub_document"
        assert len(result["images"]) <= 20
        candidates.extend(result["images"])
        offset = result["next_offset"]
        if offset is None:
            break
    assert len(candidates) == 55  # Includes candidates past read_section's 50-ID cap.
    assert len({im["image_id"] for im in candidates}) == 55
    assert candidates[0]["caption"] == "Synthetic beans"
    assert candidates[0]["recipe_context"] == (
        None if legacy else {"title": "Beans", "section_id": "section-0"}
    )
    assert candidates[1]["recipe_context"] is None
    assert all("asset" not in im and "data" not in im for im in candidates)
    with pytest.raises(IntegrityError):
        lib.list_images(**{**args, "book_id": "book-1"})
    with pytest.raises(IntegrityError):
        lib.list_images(**{**args, "section_id": "section-1"})
    with pytest.raises(IntegrityError):
        lib.list_images(**{**args, "section_id": "../../metadata.db"})
    for bounds in [{"limit": 0}, {"limit": 21}, {"offset": -1}, {"offset": 100001}]:
        with pytest.raises(IntegrityError):
            lib.list_images(**args, **bounds)
