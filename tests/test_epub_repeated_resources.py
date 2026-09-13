"""Synthetic EPUB regressions; no paged ingestion or OCR."""

import io
import zipfile
from PIL import Image
from cookbook.extract import epub
from cookbook.build import create_index, add_content


def test_repeated_spine_and_shared_image_can_be_indexed(tmp_path):
    picture = io.BytesIO()
    Image.new("RGB", (20, 20), "green").save(picture, "PNG")
    path = tmp_path / "repeat.epub"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>',
        )
        z.writestr(
            "book.opf",
            '<package><manifest><item id="a" href="a.xhtml"/><item id="b" href="b.xhtml"/><item id="nav" href="nav.xhtml" properties="nav"/></manifest><spine><itemref idref="a"/><itemref idref="a"/><itemref idref="b"/></spine></package>',
        )
        for name in ["a", "b"]:
            z.writestr(
                name + ".xhtml",
                f'<html><body><h1 id="heading">Chapter {name}</h1><p>Salt and beans.</p><img src="image.png"/><img src="image.png"/></body></html>',
            )
        z.writestr(
            "nav.xhtml",
            '<html><nav><ol><li><a href="a.xhtml#heading">Chapter a</a></li><li><a href="b.xhtml#heading">Chapter b</a></li></ol></nav></html>',
        )
        z.writestr("image.png", picture.getvalue())
    sections, images, toc = epub(path, "epub:synthetic", lambda _: "assets/picture")
    db = create_index(tmp_path / "index.sqlite", "synthetic")
    add_content(
        db,
        "epub:synthetic",
        "EPUB",
        "0" * 64,
        "backup/repeat.epub",
        sections,
        images,
        toc,
    )
    assert [s["title"] for s in sections] == ["Chapter a", "Chapter b"]
    assert [s["locator"]["spine_ordinal"] for s in sections] == [0, 2]
    assert len(images) == 1
    assert all(s["images"] == [images[0]["id"]] for s in sections)
    assert [t["section_id"] for t in toc] == [s["id"] for s in sections]
    db.close()


def test_adjacent_toc_anchors_without_text_all_resolve(tmp_path):
    path = tmp_path / "anchors.epub"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>',
        )
        z.writestr(
            "book.opf",
            '<package><manifest><item id="a" href="a.xhtml"/><item id="nav" href="nav.xhtml" properties="nav"/></manifest><spine><itemref idref="a"/></spine></package>',
        )
        z.writestr(
            "a.xhtml",
            '<html><body><section id="outer"><figure id="inner"></figure></section></body></html>',
        )
        z.writestr(
            "nav.xhtml",
            '<html><nav><ol><li><a href="a.xhtml#outer">Outer</a></li><li><a href="a.xhtml#inner">Inner</a></li></ol></nav></html>',
        )
    sections, _, toc = epub(path, "epub:anchors", lambda _: "unused")
    assert [t["section_id"] for t in toc] == [sections[0]["id"]] * 2
