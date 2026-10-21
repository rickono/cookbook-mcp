"""The pure scanned import: candidate files in, library units out (no rendering, no OCR)."""

import pytest
from synthetic_scanned import (
    INSTRUCTIONS,
    PAGE_4,
    SIDEBAR,
    pack,
    rows,
    sha,
)

from cookbook.scanned import CandidateError, import_candidate

SOURCE_SHA = sha("synthetic source")
SOURCE_ID = "pdf:" + SOURCE_SHA


def run(data=None, *, physical_pages=4, **changes):
    files = pack(data or rows(), SOURCE_SHA, **changes)
    return import_candidate(
        files,
        source_id=SOURCE_ID,
        source_sha256=SOURCE_SHA,
        physical_pages=physical_pages,
    )


def by_title(result):
    return {u["title"]: u for u in result["units"]}


def test_valid_candidate_imports_pages_first_then_sections_with_unapproved_label():
    result = run()
    units = result["units"]
    assert [u["kind"] for u in units[:4]] == ["page"] * 4
    assert [u["locator"]["physical_page"] for u in units[:4]] == [1, 2, 3, 4]
    assert [u["locator"]["kind"] for u in units[:4]] == ["page"] * 4
    assert units[0]["locator"]["printed_page_unverified"] == "12"
    assert units[2]["locator"]["status"] == "blank"
    recipe = by_title(result)["LENTIL SOUP"]
    assert recipe["kind"] == "recipe"
    assert recipe["locator"]["kind"] == "scanned-section"
    assert recipe["locator"]["physical_pages"] == [1, 2]
    assert recipe["locator"]["status"] == "has_unresolved"
    assert recipe["text"].index("A plain soup") < recipe["text"].index(INSTRUCTIONS)
    assert by_title(result)["ON LENTILS"]["locator"]["status"] == "complete_in_book"
    for unit in units:
        assert unit["provenance"] == "transcription"
        label = unit["transcription"]["label"]
        assert label["approval"] == "unapproved"
        assert label["description"] == "agent transcription, unapproved"
        assert label["candidate_sha256"] == result["candidate_sha256"]


def test_unresolved_quantity_is_a_marker_and_raw_crop_readings_never_appear():
    result = run()
    recipe = by_title(result)["LENTIL SOUP"]
    assert "Cumin | [unresolved u1: amount]" in recipe["text"]
    assert "Salt | 2 tsp" in recipe["text"]
    for unit in result["units"]:
        assert "3 tsp" not in unit["text"]
        assert "5 tsp" not in unit["text"] and "8 tsp" not in unit["text"]
    page_1 = result["units"][0]
    assert "Cumin | [unresolved u1: amount]" in page_1["text"]


def test_check_regions_keep_review_and_unresolved_boxes():
    recipe = by_title(run())["LENTIL SOUP"]
    regions = recipe["transcription"]["check_regions"]
    assert {r["state"] for r in regions} == {"crop_reviewed", "unresolved"}
    unresolved = next(r for r in regions if r["state"] == "unresolved")
    assert unresolved["unresolved_id"] == "u1"
    assert unresolved["code"] == "amount"
    assert unresolved["physical_page"] == 1
    assert unresolved["box"] == [0.1, 0.4, 0.9, 0.7]
    assert recipe["transcription"]["corrections"] == []


def test_pages_covered_by_sections_are_not_searchable_but_uncovered_pages_are():
    units = run()["units"]
    assert [u["searchable"] for u in units[:4]] == [False, False, True, True]
    assert units[3]["text"] == PAGE_4
    assert all(u["searchable"] for u in units[4:])


def test_toc_lists_sections_with_their_first_physical_page():
    result = run()
    ids = {u["title"]: u["id"] for u in result["units"]}
    assert [
        (t["title"], t["physical_page"], t["section_id"]) for t in result["toc"]
    ] == [
        ("LENTIL SOUP", 1, ids["LENTIL SOUP"]),
        ("ON LENTILS", 2, ids["ON LENTILS"]),
    ]


def test_summary_records_coverage_reader_and_empty_corrections():
    result = run()
    summary = result["summary"]
    assert summary["source_id"] == SOURCE_ID
    assert summary["source_sha256"] == SOURCE_SHA
    assert summary["candidate_sha256"] == result["candidate_sha256"]
    assert summary["pages_total"] == 4
    assert summary["coverage"] == {"transcribed": 3, "blank": 1, "failed": 0}
    assert summary["sections"] == 2
    assert summary["quantity_reviews"] == 1
    assert summary["unresolved"] == 1
    assert summary["reader"] == "claude:claude-haiku-5-5"
    assert summary["samples"] == 3
    assert summary["corrections"] == {"applied": [], "stale": [], "ambiguous": []}


def test_ledger_argument_is_accepted_and_applies_nothing_yet():
    files = pack(rows(), SOURCE_SHA)
    plain = import_candidate(
        files, source_id=SOURCE_ID, source_sha256=SOURCE_SHA, physical_pages=4
    )
    with_ledger = import_candidate(
        files,
        source_id=SOURCE_ID,
        source_sha256=SOURCE_SHA,
        physical_pages=4,
        ledger=[{"physical_page": 1, "replace": "Salt", "with": "Pepper"}],
    )
    assert with_ledger == plain


def test_failed_page_becomes_a_marker_never_a_graphic():
    data = rows()
    data["pages"][3] = data["pages"][3] | {
        "status": "failed",
        "text": "",
        "text_sha256": sha(""),
        "page_reader": None,
        "unresolved_ids": ["u2"],
    }
    data["unresolved"].append(
        {
            "id": "u2",
            "section_id": None,
            "physical_page": 4,
            "field": "other",
            "code": "failed_page",
            "reason": "no reader returned text",
            "source_fragment": None,
            "box": [0.0, 0.0, 1.0, 1.0],
            "review_id": None,
            "crop_readings": [],
        }
    )
    page_4 = run(data)["units"][3]
    assert page_4["text"] == "[unresolved u2: failed_page]"
    assert page_4["images"] == []
    assert page_4["locator"]["status"] == "failed"


def drop_page(data, n=2):
    data["pages"] = [p for p in data["pages"] if p["physical_page"] != n]
    return data


def repeat_page(data, n=2):
    data["pages"].insert(n, data["pages"][n - 1])
    return data


def blank_without_evidence(data):
    del data["pages"][2]["blank_evidence"]
    return data


def failed_without_marker(data):
    data["pages"][3] |= {"status": "failed", "text": "", "text_sha256": sha("")}
    return data


def text_digest_wrong(data):
    data["pages"][0]["text_sha256"] = sha("other")
    return data


def dangling_section(data):
    data["unresolved"][0]["section_id"] = "9001:missing"
    return data


def dangling_review(data):
    data["unresolved"][0]["review_id"] = "9001:p002:crop9"
    return data


def bad_code(data):
    data["unresolved"][0]["code"] = "guess"
    return data


def tiny_box(data):
    data["quantity-review"][0]["box"] = [0.1, 0.1, 0.11, 0.5]
    return data


def unknown_key(data):
    data["sections"][0]["approved"] = True
    return data


def graphic_with_text(data):
    data["sections"][1]["parts"][1]["kind"] = "graphic"
    return data


def part_off_section_pages(data):
    data["sections"][1]["parts"][1]["source_page"] = 4
    return data


def page_sections_disagree(data):
    data["pages"][1]["section_ids"] = [SIDEBAR]
    return data


@pytest.mark.parametrize(
    "change",
    [
        drop_page,
        repeat_page,
        blank_without_evidence,
        failed_without_marker,
        text_digest_wrong,
        dangling_section,
        dangling_review,
        bad_code,
        tiny_box,
        unknown_key,
        graphic_with_text,
        part_off_section_pages,
        page_sections_disagree,
    ],
)
def test_malformed_candidate_rows_are_refused(change):
    with pytest.raises(CandidateError):
        run(change(rows()))


@pytest.mark.parametrize(
    "changes",
    [
        {"approval": "approved"},
        {"version": "scanned-candidate.v0"},
        {"counts": {"sections": 3, "quantity_reviews": 1, "unresolved": 1}},
        {"coverage": {"pages_total": 4, "transcribed": 4, "blank": 0, "failed": 0}},
        {
            "reader": {
                "spec": "x",
                "samples": 2,
                "sample_labels": ["a"],
                "fallback": None,
            }
        },
        {"extra": 1},
    ],
)
def test_malformed_freeze_record_is_refused(changes):
    with pytest.raises(CandidateError):
        run(**changes)


KWARGS = {"source_id": SOURCE_ID, "source_sha256": SOURCE_SHA, "physical_pages": 4}


def test_candidate_binds_to_source_digest_and_page_count_not_book_id():
    files = pack(rows(), SOURCE_SHA)
    with pytest.raises(CandidateError, match="different source"):
        import_candidate(files, **(KWARGS | {"source_sha256": sha("other")}))
    with pytest.raises(CandidateError, match="page count"):
        import_candidate(files, **(KWARGS | {"physical_pages": 5}))
    assert run(book_id=1)["summary"]["pages_total"] == 4


def test_file_bytes_must_match_the_freeze_record():
    files = pack(rows(), SOURCE_SHA)
    files["pages.jsonl"] += b"\n"
    with pytest.raises(CandidateError):
        import_candidate(files, **KWARGS)


def test_duplicate_json_keys_and_extra_files_are_refused():
    files = pack(rows(), SOURCE_SHA)
    dup = files["candidate.json"][:-1] + b',"approval":"unapproved"}'
    with pytest.raises(CandidateError, match="duplicate"):
        import_candidate(files | {"candidate.json": dup}, **KWARGS)
    with pytest.raises(CandidateError):
        import_candidate(files | {"notes.txt": b"x"}, **KWARGS)


def test_candidate_status_field_is_not_trusted():
    data = rows()
    data["sections"][0]["status"] = "complete_in_book"
    recipe = by_title(run(data))["LENTIL SOUP"]
    assert recipe["locator"]["status"] == "has_unresolved"


def test_whole_line_is_replaced_when_the_span_is_absent():
    data = rows()
    del data["unresolved"][0]["span"]
    recipe = by_title(run(data))["LENTIL SOUP"]
    assert "[unresolved u1: amount]" in recipe["text"].split("\n")
    assert "Cumin" not in recipe["text"]


def test_published_schema_matches_the_validator_and_accepts_the_synthetic_rows():
    import json
    from pathlib import Path

    from cookbook import scanned

    jsonschema = pytest.importorskip("jsonschema")  # transitive via mcp

    path = Path(__file__).parents[1] / "docs/schemas/scanned-candidate.v1.schema.json"
    schema = json.loads(path.read_text())
    defs = schema["$defs"]
    for name, required, optional in [
        ("Candidate", scanned.CANDIDATE_KEYS, ()),
        ("Page", scanned.PAGE_KEYS, scanned.PAGE_OPTIONAL),
        ("Section", scanned.SECTION_KEYS, scanned.SECTION_OPTIONAL),
        ("Part", scanned.PART_KEYS, ()),
        ("Reference", scanned.REFERENCE_KEYS, ()),
        ("QuantityReview", scanned.REVIEW_KEYS, ()),
        ("Unresolved", scanned.UNRESOLVED_KEYS, scanned.UNRESOLVED_OPTIONAL),
        ("VoteCorrection", scanned.CORRECTION_KEYS, ()),
    ]:
        assert set(defs[name]["required"]) == set(required), name
        assert set(defs[name]["properties"]) == {*required, *optional}, name
    assert set(defs["Candidate"]["properties"]["files"]["required"]) == set(
        scanned.FILES
    )
    assert defs["Page"]["properties"]["status"]["enum"] == list(scanned.PAGE_STATUSES)
    assert defs["Section"]["properties"]["kind"]["enum"] == list(scanned.SECTION_KINDS)
    assert defs["Part"]["properties"]["kind"]["enum"] == list(scanned.PART_KINDS)
    assert defs["Unresolved"]["properties"]["code"]["enum"] == list(
        scanned.UNRESOLVED_CODES
    )

    def check(value, name):
        jsonschema.validate(value, {"$ref": f"#/$defs/{name}", "$defs": defs})

    files = pack(rows(), SOURCE_SHA)
    jsonschema.validate(json.loads(files["candidate.json"]), schema)
    for file, name in [
        ("pages.jsonl", "Page"),
        ("sections.jsonl", "Section"),
        ("quantity-review.jsonl", "QuantityReview"),
        ("unresolved.jsonl", "Unresolved"),
        ("vote-corrections.jsonl", "VoteCorrection"),
    ]:
        for line in files[file].splitlines():
            check(json.loads(line), name)


def test_validator_imports_without_the_extraction_or_server_stack():
    import subprocess
    import sys

    code = (
        "import sys, cookbook.scanned;"
        "heavy={'lxml','PIL','pypdf','pydantic','fastapi','mcp','starlette'};"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in heavy))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"
