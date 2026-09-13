import io
import zipfile
from pathlib import Path
import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from cookbook.extract import epub, paged, render_page, run
from cookbook.storage import IntegrityError, digest_file


def make_epub(path, version="3.0"):
    image = io.BytesIO()
    Image.new("RGB", (200, 100), "green").save(image, "PNG")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/content.opf",
            f'''<package version="{version}"><manifest><item id="b" href="z.xhtml" media-type="application/xhtml+xml"/><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="n" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>''',
        )
        z.writestr(
            "OEBPS/nav.xhtml",
            '<html><nav><ol><li><a href="z.xhtml#intro">Introduction</a><ol><li><a href="z.xhtml#recipe">Bean recipe</a></li></ol></li><li><a href="a.xhtml#missing">Missing anchor</a></li></ol></nav></html>',
        )
        z.writestr(
            "OEBPS/z.xhtml",
            '<html><body><h1 id="intro">First in spine</h1><p>Some context.</p><div id="recipe" itemtype="https://schema.org/Recipe"><h2>Bean stew</h2><p>1/2 teaspoon salt. Simmer beans 20 minutes.</p></div><img src="pic.png" alt="Beans"/></body></html>',
        )
        z.writestr(
            "OEBPS/a.xhtml",
            "<html><body><h1>Last in spine</h1><p>Last text.</p></body></html>",
        )
        z.writestr("OEBPS/pic.png", image.getvalue())


@pytest.mark.parametrize("version", ["2.0", "3.0"])
def test_spine_toc_recipe_image_and_stability(tmp_path, version):
    p = tmp_path / "test.epub"
    make_epub(p, version)
    assets = []

    def emit(data):
        assets.append(data)
        return "assets/image"

    sections, images, toc = epub(p, "epub:fixture", emit)
    assert (
        sections[0]["title"] == "First in spine"
        and sections[-1]["title"] == "Last in spine"
    )
    recipe = next(s for s in sections if s["id"] == toc[1]["section_id"])
    assert recipe["kind"] == "recipe" and "1/2 teaspoon" in recipe["text"]
    assert toc[1]["depth"] == 1 and toc[2]["section_id"] is None
    assert images[0]["caption"] == "Beans" and assets[0].startswith(b"\xff\xd8")
    assert [s["id"] for s in epub(p, "epub:fixture", emit)[0]] == [
        s["id"] for s in sections
    ]
    assert len(sections) == 3


def make_pdf(path):
    im = Image.new("RGB", (1700, 2200), "white")
    d = ImageDraw.Draw(im)
    fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    font = ImageFont.truetype(next(p for p in fonts if Path(p).exists()), 45)
    for y, line in enumerate(
        [
            "SCANNED BEAN RECIPE",
            "1/2 teaspoon salt",
            "200 grams beans",
            "Simmer 20 minutes.",
        ]
    ):
        d.text((100, 120 + y * 90), line, font=font, fill="black")
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.drawString(
        40, 750, "Native recipe: 2 cups rice, 500 ml water. Simmer for twenty minutes."
    )
    c.showPage()
    c.drawImage(ImageReader(im), 0, 0, 612, 792)
    c.showPage()
    c.showPage()
    # Oversized landscape spread validates bounding without changing page identity.
    c.setPageSize((6000, 3000))
    c.drawString(
        100, 2900, "Large spread with native text and original physical page mapping."
    )
    c.showPage()
    c.save()
    return im


def test_pdf_ocr_page_identity_cache_and_bounds(tmp_path):
    p = tmp_path / "mixed.pdf"
    make_pdf(p)
    before = digest_file(p)
    source = "pdf:" + before[0]
    sections, _, toc = paged(p, "PDF", source, tmp_path / "ocr")
    assert len(sections) == 4
    assert sections[0]["provenance"] == "native"
    assert (
        sections[1]["provenance"] == "ocr"
        and "1/2 teaspoon salt" in sections[1]["text"]
    )
    assert sections[2]["provenance"] == "native+ocr-empty"
    assert sections[3]["locator"]["physical_page"] == 4
    first = list((tmp_path / "ocr").rglob("result.json"))
    times = {f: f.stat().st_mtime_ns for f in first}
    paged(p, "PDF", source, tmp_path / "ocr")
    assert times == {f: f.stat().st_mtime_ns for f in first}
    png = tmp_path / "spread.png"
    render_page(p, "PDF", 4, png, 1600)
    with Image.open(png) as im:
        assert max(im.size) <= 1600 and im.width > im.height
    assert digest_file(p) == before


def test_ocr_failure_and_timeout_not_cached(tmp_path, monkeypatch):
    import cookbook.extract as ex

    p = tmp_path / "mixed.pdf"
    make_pdf(p)
    saved = ex.run

    def fail(args, timeout=90):
        if str(args[0]) == "tesseract" and "stdout" in args:
            raise IntegrityError("extraction subprocess failed")
        return saved(args, timeout)

    monkeypatch.setattr(ex, "run", fail)
    with pytest.raises(IntegrityError):
        paged(p, "PDF", "pdf:" + digest_file(p)[0], tmp_path / "ocr")
    assert not list((tmp_path / "ocr").rglob("result.json"))
    import sys

    with pytest.raises(IntegrityError):
        saved([sys.executable, "-c", "import time;time.sleep(10)"], timeout=0.01)


def test_djvu_image_only_ocr_and_render(tmp_path):
    p = tmp_path / "mixed.pdf"
    im = make_pdf(p)
    ppm = tmp_path / "scan.ppm"
    im.save(ppm)
    djvu = tmp_path / "scan.djvu"
    run(["c44", ppm, djvu])
    before = digest_file(djvu)
    sections, _, _ = paged(djvu, "DJVU", "djvu:" + before[0], tmp_path / "ocr")
    assert (
        len(sections) == 1
        and "200 grams beans" in sections[0]["text"]
        and sections[0]["provenance"] == "ocr"
    )
    png = tmp_path / "page.png"
    render_page(djvu, "DJVU", 1, png, 1000)
    with Image.open(png) as img:
        assert max(img.size) <= 1000
    assert digest_file(djvu) == before


def test_publisher_recipe_profile_requires_toc_ingredients_and_method(tmp_path):
    p = tmp_path / "styled.epub"
    make_epub(p)
    with zipfile.ZipFile(p) as z:
        members = {name: z.read(name) for name in z.namelist()}
    members["OEBPS/z.xhtml"] = (
        b"""<html><body><h1 id="intro">Introduction</h1><p>Context.</p><p class="rt" id="recipe">Synthetic bean stew</p><p class="Serving">Serves four</p><p class="ril">200 grams beans</p><p class="ril">1/2 teaspoon salt</p><p class="rpf">Simmer twenty minutes.</p><p class="rp">Serve warm.</p></body></html>"""
    )

    def write():
        with zipfile.ZipFile(p, "w") as z:
            for name, raw in members.items():
                z.writestr(name, raw)

    write()
    sections, _, toc = epub(p, "epub:synthetic-style", lambda b: "unused")
    recipe = next(s for s in sections if s["id"] == toc[1]["section_id"])
    assert recipe["kind"] == "recipe" and recipe["title"] == "Synthetic bean stew"
    assert recipe["locator"]["recipe_structure"]["ingredient_block_ordinals"] == [2, 3]
    members["OEBPS/z.xhtml"] = members["OEBPS/z.xhtml"].replace(
        b'class="ril"', b'class="body"'
    )
    write()
    assert not any(
        s["kind"] == "recipe" for s in epub(p, "epub:changed", lambda b: "unused")[0]
    )
