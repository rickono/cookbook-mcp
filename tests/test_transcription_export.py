"""Synthetic ZIP/XML/evidence export checks; no image or book ingestion."""

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy

import pytest
from test_transcription import saved

from cookbook.transcription import adapt_docling, snapshot_digest
from cookbook.transcription_boundaries import propose_boundaries
from cookbook.transcription_export import export_epub
from cookbook.transcription_review import make_revision, source_evidence, target_digest

X = {"h": "http://www.w3.org/1999/xhtml", "o": "http://www.idpf.org/2007/opf"}


def unpack(payload):
    return zipfile.ZipFile(io.BytesIO(payload))


def revision(base, boundary, kind, target, value, state="source_reviewed"):
    ids = [target] if kind != "quantity" else base["tables"][0]["cells"][0]["line_ids"]
    return make_revision(
        base,
        [
            {
                "kind": kind,
                "target_id": target,
                "before_sha256": target_digest(
                    base, kind, target, selections=boundary["selections"]
                ),
                "state": state,
                "value": value,
                "reason": "Synthetic source inspection",
                "evidence": source_evidence(base, ids),
            }
        ],
        reviewer={"kind": "agent", "id": "synthetic"},
        selections=boundary["selections"],
    )


def test_epub_container_package_and_all_internal_targets_resolve():
    base = adapt_docling(*saved())
    boundary = propose_boundaries(base)
    archive = unpack(export_epub(base, boundaries=boundary))
    first = archive.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert first.extra == b"" and first.header_offset == 0
    assert archive.read("mimetype") == b"application/epub+zip"
    container = ET.fromstring(archive.read("META-INF/container.xml"))
    assert next(iter(next(iter(container)))).attrib["full-path"] == "EPUB/package.opf"
    package = ET.fromstring(archive.read("EPUB/package.opf"))
    assert package.attrib["version"] == "3.0"
    items = package.findall("o:manifest/o:item", X)
    assert len([i for i in items if i.attrib.get("properties") == "nav"]) == 1
    assert {i.attrib["href"] for i in items} == {
        "source.xhtml",
        "nav.xhtml",
        "style.css",
        "provenance.json",
    }
    assert package.find("o:spine/o:itemref", X).attrib["idref"] == "reading"
    source = ET.fromstring(archive.read("EPUB/source.xhtml"))
    ids = [n.attrib["id"] for n in source.iter() if "id" in n.attrib]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", i) for i in ids)
    nav = ET.fromstring(archive.read("EPUB/nav.xhtml"))
    for link in nav.findall(".//h:a", X):
        path, _, fragment = link.attrib["href"].partition("#")
        assert "EPUB/" + path in archive.namelist()
        if fragment:
            assert fragment in ids
    assert "file://" not in archive.read("EPUB/source.xhtml").decode()


def test_source_lines_once_with_exact_bytes_escaping_and_evidence():
    args = saved()
    args[1][0]["lines"][0]["text"] = '<script>x</script> & "salt"\nwhite  space'
    # This test covers a canonical snapshot independently of Docling parsing.
    base = adapt_docling(*saved())
    base["pages"][0]["lines"][0]["text"] = args[1][0]["lines"][0]["text"]
    archive = unpack(export_epub(base))
    source_bytes = archive.read("EPUB/source.xhtml")
    source = ET.fromstring(source_bytes)
    raw = [n.text or "" for n in source.findall(".//h:p[@class='raw']", X)]
    assert raw == [line["text"] for page in base["pages"] for line in page["lines"]]
    assert source.find(".//h:script", X) is None
    assert b"&lt;script&gt;" in source_bytes
    provenance = json.loads(archive.read("EPUB/provenance.json"))
    assert provenance["snapshot"] == base
    assert provenance["snapshot_sha256"] == snapshot_digest(base)
    assert provenance["approval"] == "unapproved"
    assert provenance["snapshot"]["pages"][0]["render_to_source"] == [
        0.5,
        0,
        0,
        0.5,
        0,
        0,
    ]
    assert base["edition"]["source_sha256"] in source_bytes.decode()
    assert base["pages"][0]["recognition"]["artifact_sha256"] in source_bytes.decode()
    assert "Physical page 1" in "".join(source.itertext())


def test_corrections_only_displayed_explicitly_and_unresolved_never_falls_back():
    base = adapt_docling(*saved())
    boundary = propose_boundaries(base)
    correction = revision(
        base, boundary, "line_text", "p:l0", "Corrected synthetic text"
    )
    raw = unpack(export_epub(base, boundaries=boundary, revisions=[correction]))
    assert b"Corrected synthetic text" not in raw.read("EPUB/source.xhtml")
    assert b"Corrected synthetic text" in raw.read("EPUB/provenance.json")
    reviewed = unpack(
        export_epub(base, boundaries=boundary, revisions=[correction], reading="review")
    )
    assert b"Corrected synthetic text" in reviewed.read("EPUB/source.xhtml")
    cell = base["tables"][0]["cells"][0]
    uncertain = revision(base, boundary, "quantity", cell["id"], None, "unresolved")
    for mode in ("raw", "review"):
        archive = unpack(
            export_epub(base, boundaries=boundary, revisions=[uncertain], reading=mode)
        )
        source = ET.fromstring(archive.read("EPUB/source.xhtml"))
        note = source.find(".//h:p[@class='quantity']", X).text
        assert "UNRESOLVED QUANTITY" in note and "½" not in note
        assert [p.text for p in source.findall(".//h:p[@class='raw']", X)] == [
            "1. Stir the synthetic soup.",
            "½",
        ]
        assert "raw OCR is not an asserted value" in "".join(source.itertext())


def test_null_line_and_unresolved_picture_remain_visible():
    base = adapt_docling(*saved())
    boundary = propose_boundaries(base)
    unresolved = revision(base, boundary, "line_text", "p:l0", None, "unresolved")
    archive = unpack(
        export_epub(base, boundaries=boundary, revisions=[unresolved], reading="review")
    )
    source = ET.fromstring(archive.read("EPUB/source.xhtml"))
    assert (
        source.find(".//h:p[@class='reading']", X).text
        == "[UNRESOLVED TEXT — no reading asserted]"
    )
    assert "UNRESOLVED ELEMENT" in "".join(source.itertext())
    assert "header flags are unverified" in "".join(source.itertext())


def test_deterministic_without_mutation_and_stale_boundaries_fail():
    base = adapt_docling(*saved())
    boundary = propose_boundaries(base)
    original = deepcopy((base, boundary))
    first = export_epub(base, boundaries=boundary)
    assert first == export_epub(deepcopy(base), boundaries=deepcopy(boundary))
    assert (base, boundary) == original
    boundary["snapshot_digest"] = "f" * 64
    with pytest.raises(ValueError, match="digest"):
        export_epub(base, boundaries=boundary)


@pytest.mark.parametrize(
    "options",
    [
        {"reading": "accepted"},
        {"title": ""},
        {"title": "bad\x00text"},
        {"language": 'en" onload="x'},
    ],
)
def test_invalid_options_refuse(options):
    with pytest.raises(ValueError):
        export_epub(adapt_docling(*saved()), **options)


def test_resolved_quantity_remains_separate_from_raw_and_default_view():
    base = adapt_docling(*saved())
    boundary = propose_boundaries(base)
    cell = base["tables"][0]["cells"][0]
    corrected = revision(base, boundary, "quantity", cell["id"], "2/3 cup")
    raw = unpack(export_epub(base, boundaries=boundary, revisions=[corrected]))
    assert b"2/3 cup" not in raw.read("EPUB/source.xhtml")
    reviewed = unpack(
        export_epub(base, boundaries=boundary, revisions=[corrected], reading="review")
    )
    source = ET.fromstring(reviewed.read("EPUB/source.xhtml"))
    assert "2/3 cup" in source.find(".//h:p[@class='quantity']", X).text
    assert [p.text for p in source.findall(".//h:p[@class='raw']", X)] == [
        "1. Stir the synthetic soup.",
        "½",
    ]


def test_membership_overlay_changes_navigation_without_copying_source_text():
    from test_transcription_boundaries import evidence, recipe

    base = evidence(
        recipe("Synthetic soup") + recipe("Independent sauce", x=600, y=300)
    )
    boundary = propose_boundaries(base)
    owner = boundary["selections"][1]["id"]
    revised = revision(base, boundary, "membership", "p1-l1", [owner])
    for reading, counts in (("raw", [5, 5]), ("review", [4, 6])):
        archive = unpack(
            export_epub(base, boundaries=boundary, revisions=[revised], reading=reading)
        )
        nav = ET.fromstring(archive.read("EPUB/nav.xhtml"))
        entries = nav.findall(".//h:nav[@id='selections']/h:ol/h:li", X)
        assert [len(entry.findall(".//h:a", X)) for entry in entries] == counts
        source = ET.fromstring(archive.read("EPUB/source.xhtml"))
        assert len(source.findall(".//h:p[@class='raw']", X)) == 10


def test_separate_authored_marker_and_empty_lines_remain_represented():
    base = adapt_docling(*saved())
    base["pages"][0]["lines"][0]["text"] = "Stir the synthetic soup."
    base["pages"][0]["lines"][1]["text"] = ""
    archive = unpack(export_epub(base))
    source = ET.fromstring(archive.read("EPUB/source.xhtml"))
    assert source.find(".//h:p[@class='marker']", X).text.endswith("1.")
    assert len(source.findall(".//h:p[@class='raw']", X)) == 2
    assert source.findall(".//h:p[@class='raw']", X)[1].text is None
