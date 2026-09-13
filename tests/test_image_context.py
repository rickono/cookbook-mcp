"""Synthetic EPUB-only caption checks; no PDF rendering or OCR."""

import zipfile

from test_extract import make_epub

from cookbook.extract import epub


def test_caption_and_recipe_context_are_distinct_and_bounded(tmp_path):
    path = tmp_path / "captions.epub"
    make_epub(path)
    with zipfile.ZipFile(path) as z:
        members = {name: z.read(name) for name in z.namelist()}
    members["OEBPS/z.xhtml"] = b"""<html><body>
      <h1 id="intro">Introduction</h1><img src="before.png"/>
      <p class="rt" id="recipe">Bean stew</p>
      <img src="beside.png" alt=""/>
      <p class="ril">200 grams beans</p><p class="rpf">Simmer.</p>
      <h2>Unrelated essay</h2><img src="after.png"/>
      <figure><img src="captioned.png" alt="Generic photo"/>
      <figcaption>Beans with toasted bread</figcaption></figure>
      </body></html>"""
    for name in ("before", "beside", "after", "captioned"):
        members[f"OEBPS/{name}.png"] = members["OEBPS/pic.png"]
    with zipfile.ZipFile(path, "w") as z:
        for name, raw in members.items():
            z.writestr(name, raw)
    sections, images, _ = epub(path, "epub:synthetic", lambda data: "assets/image")
    assert images[0]["recipe_context"] is None
    assert images[1]["caption"] == ""
    recipe = next(s for s in sections if s["kind"] == "recipe")
    assert images[1]["recipe_context"] == {
        "title": "Bean stew",
        "section_id": recipe["id"],
    }
    assert images[2]["recipe_context"] is None
    assert images[3]["caption"] == "Beans with toasted bread"
    assert images[3]["recipe_context"] is None
