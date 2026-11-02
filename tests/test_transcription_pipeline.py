"""Synthetic whole-path evidence/ownership/review/reading test, without OCR."""

import io
import json
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy

from test_transcription_boundaries import containing, evidence, recipe, region

from cookbook.transcription import validate_snapshot
from cookbook.transcription_boundaries import propose_boundaries, validate_boundaries
from cookbook.transcription_export import export_epub
from cookbook.transcription_review import (
    make_revision,
    reviewed_view,
    source_evidence,
    target_digest,
)

X = {"h": "http://www.w3.org/1999/xhtml"}


def test_continuation_sidebar_review_and_reading_preserve_one_source_owner():
    base = evidence(
        recipe("Synthetic stew"),
        [region("list_item", "3. Serve the stew.")]
        + recipe("Independent relish", x=600, y=300)
        + [region("picture", "Uncertain illustrated region", y=650)],
    )
    validate_snapshot(base)
    boundary = propose_boundaries(base)
    validate_boundaries(base, boundary)
    stew, relish = containing(boundary, "p1-l0"), containing(boundary, "p2-l1")
    assert "p2-l0" in stew["line_ids"]
    assert set(stew["line_ids"]).isdisjoint(relish["line_ids"])
    original = deepcopy((base, boundary))
    changes = [
        {
            "kind": "line_text",
            "target_id": "p1-l1",
            "before_sha256": target_digest(
                base, "line_text", "p1-l1", selections=boundary["selections"]
            ),
            "state": "source_reviewed",
            "value": "½ cup water",
            "reason": "Synthetic inspected source.",
            "evidence": source_evidence(base, ["p1-l1"]),
        }
    ]
    revision = make_revision(
        base,
        changes,
        reviewer={"kind": "agent", "id": "synthetic"},
        selections=boundary["selections"],
    )
    view = reviewed_view(base, revisions=[revision], selections=boundary["selections"])
    assert view["lines"][1]["raw_text"] == "2 cups water"
    assert view["lines"][1]["text"] == "½ cup water"
    with zipfile.ZipFile(
        io.BytesIO(
            export_epub(
                base, boundaries=boundary, revisions=[revision], reading="review"
            )
        )
    ) as archive:
        source = ET.fromstring(archive.read("EPUB/source.xhtml"))
        raw = [p.text for p in source.findall(".//h:p[@class='raw']", X)]
        assert raw == [line["text"] for page in base["pages"] for line in page["lines"]]
        nav = ET.fromstring(archive.read("EPUB/nav.xhtml"))
        entries = nav.findall(".//h:nav[@id='selections']/h:ol/h:li", X)
        assert [len(entry.findall(".//h:a", X)) for entry in entries] == [
            sum(
                view["memberships"][line_id]["value"] == [selection["id"]]
                for line_id in selection["line_ids"]
            )
            for selection in boundary["selections"]
        ]
        assert "½ cup water" in "".join(source.itertext())
        provenance = json.loads(archive.read("EPUB/provenance.json"))
        assert provenance["revisions"] == [revision]
        assert provenance["boundaries"]["links"][0]["line_ids"] == ["p2-l0"]
        assert provenance["snapshot"] == base
    assert (base, boundary) == original
