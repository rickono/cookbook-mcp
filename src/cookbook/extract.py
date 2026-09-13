"""Source-ordered extraction. All render/OCR output is derived; originals are read-only."""

from __future__ import annotations
import hashlib
import io
from pathlib import Path
import posixpath
import re
import subprocess
from urllib.parse import unquote, urlsplit
import zipfile
from lxml import etree
from PIL import Image
from pypdf import PdfReader
from .storage import IntegrityError, canonical, safe_key

VERSION = "extract-v2"
Image.MAX_IMAGE_PIXELS = 40_000_000


def ident(*parts):
    return hashlib.sha256(canonical(parts)).hexdigest()[:32]


def run(args, timeout=90):
    try:
        return subprocess.run(
            [str(x) for x in args], check=True, capture_output=True, timeout=timeout
        ).stdout
    except (subprocess.SubprocessError, OSError):
        raise IntegrityError("extraction subprocess failed") from None


def member(base, href):
    u = urlsplit(href)
    if u.scheme or u.netloc:
        raise IntegrityError("external EPUB reference")
    path = (
        posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(u.path)))
        if u.path
        else base
    )
    return safe_key(path), unquote(u.fragment)


def xml(raw):
    return etree.fromstring(
        raw,
        parser=etree.XMLParser(resolve_entities=False, no_network=True, recover=True),
    )


def tag(el):
    return etree.QName(el).localname.lower() if isinstance(el.tag, str) else ""


def text(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def epub(path: Path, source: str, emit_asset):
    sections = []
    images = []
    toc = []
    with zipfile.ZipFile(path) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise IntegrityError("duplicate EPUB member")
        if sum(i.file_size for i in z.infolist()) > 4_000_000_000:
            raise IntegrityError("EPUB expansion limit")

        def read(name):
            if z.getinfo(name).file_size > 32_000_000:
                raise IntegrityError("EPUB member limit")
            return z.read(name)

        container = xml(read("META-INF/container.xml"))
        opfpath = container.xpath('//*[local-name()="rootfile"]')[0].get("full-path")
        safe_key(opfpath)
        package = xml(read(opfpath))
        manifest = {
            e.get("id"): e for e in package.xpath('//*[local-name()="manifest"]/*')
        }
        spine = [
            manifest[e.get("idref")]
            for e in package.xpath('//*[local-name()="spine"]/*')
        ]
        section_by_path = {}
        anchors = {}
        nav_targets = {}
        for navitem in manifest.values():
            if (
                "nav" not in (navitem.get("properties") or "").split()
                and navitem.get("media-type") != "application/x-dtbncx+xml"
            ):
                continue
            navpath, _ = member(opfpath, navitem.get("href"))
            navroot = xml(read(navpath))
            for node in navroot.iter():
                href = (
                    node.get("href")
                    if tag(node) == "a"
                    else node.get("src")
                    if tag(node) == "content"
                    else None
                )
                if href:
                    dp, an = member(navpath, href)
                    if an:
                        nav_targets.setdefault(dp, set()).add(an)
        for ordinal, item in enumerate(spine):
            docpath, _ = member(opfpath, item.get("href"))
            # Some EPUBs repeat a document in the spine. Its source-bound
            # sections have one identity; retain their first reading position.
            if docpath in section_by_path:
                continue
            root = xml(read(docpath))
            if root is None:
                raise IntegrityError("unreadable EPUB document")
            for e in list(root.iter()):
                if tag(e) in ("script", "style") and e.getparent() is not None:
                    e.getparent().remove(e)
            bodies = root.xpath('//*[local-name()="body"]')
            body = bodies[0] if bodies else root
            # Deterministic leaf-block traversal: heading boundaries, no duplicated nested text.
            blocks = []

            def walk(el):
                if el.get("id") in nav_targets.get(docpath, set()):
                    blocks.append(("anchor", el.get("id")))
                if tag(el) in (
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                    "p",
                    "li",
                    "figcaption",
                    "td",
                    "pre",
                ):
                    blocks.append(el)
                    return
                if el.text and el.text.strip():
                    blocks.append(("text", el.text))
                for child in el:
                    walk(child)
                    if child.tail and child.tail.strip():
                        blocks.append(("text", child.tail))

            walk(body)
            groups = []
            current = []
            for b in blocks:
                if (
                    (
                        (isinstance(b, tuple) and b[0] == "anchor")
                        or (
                            not isinstance(b, tuple)
                            and tag(b).startswith("h")
                            and len(tag(b)) == 2
                        )
                    )
                    and current
                    and any(
                        not isinstance(x, tuple) or x[0] != "anchor" for x in current
                    )
                ):
                    groups.append(current)
                    current = []
                current.append(b)
            if current:
                groups.append(current)
            if not groups:
                groups = [[]]
            offset = 0
            for gi, group in enumerate(groups):
                lines = [
                    re.sub(r"\s+", " ", b[1]).strip()
                    if isinstance(b, tuple)
                    else text(b)
                    for b in group
                    if not isinstance(b, tuple) or b[0] != "anchor"
                ]
                content = "\n".join(x for x in lines if x)
                heading = next(
                    (
                        text(b)
                        for b in group
                        if not isinstance(b, tuple)
                        and tag(b) in ("h1", "h2", "h3", "h4", "h5", "h6")
                    ),
                    "",
                )
                sid = ident(source, docpath, gi, VERSION)
                anchor = next(
                    (b[1] for b in group if isinstance(b, tuple) and b[0] == "anchor"),
                    None,
                ) or next(
                    (
                        b.get("id")
                        for b in group
                        if not isinstance(b, tuple) and b.get("id")
                    ),
                    None,
                )
                loc = {
                    "kind": "epub",
                    "document": docpath,
                    "anchor": anchor,
                    "text_offset": offset,
                    "spine_ordinal": ordinal,
                    "section_ordinal": gi,
                    "algorithm": "epub-spine-v2",
                }
                section = {
                    "id": sid,
                    "title": heading or f"Section {ordinal + 1}.{gi + 1}",
                    "text": content,
                    "locator": loc,
                    "provenance": "native",
                    "kind": "section",
                    "images": [],
                }
                # A bounded, TOC-linked publisher style observed in the approved EPUB fixture.
                # Both ingredient and method blocks are required; class names alone are insufficient.
                leaf_blocks = [b for b in group if not isinstance(b, tuple)]
                first = leaf_blocks[0] if leaf_blocks else None
                if (
                    first is not None
                    and tag(first) == "p"
                    and first.get("class") in {"rt", "rt-alt", "rtno"}
                    and first.get("id") in nav_targets.get(docpath, set())
                ):
                    ingredient_lines = [
                        i
                        for i, b in enumerate(leaf_blocks)
                        if b.get("class") in {"ril", "rils"}
                    ]
                    method_lines = [
                        i
                        for i, b in enumerate(leaf_blocks)
                        if b.get("class") in {"rpf", "rp"}
                    ]
                    if (
                        ingredient_lines
                        and method_lines
                        and min(method_lines) > max(ingredient_lines)
                    ):
                        section["kind"] = "recipe"
                        section["title"] = text(first)
                        loc["recipe_structure"] = {
                            "profile": "toc-rt-ril-rp-v1",
                            "ingredient_block_ordinals": ingredient_lines,
                            "method_block_ordinals": method_lines,
                        }
                if anchor:
                    anchors[(docpath, anchor)] = sid
                for candidate in body.iter():
                    semantic = (
                        (
                            (candidate.get("itemtype") or "")
                            + " "
                            + (
                                candidate.get("{http://www.idpf.org/2007/ops}type")
                                or ""
                            )
                        )
                        .lower()
                        .split()
                    )
                    if any(
                        x.endswith("/recipe") or x == "recipe" for x in semantic
                    ) and re.sub(r"\s+", "", text(candidate)) == re.sub(
                        r"\s+", "", content
                    ):
                        section["kind"] = "recipe"
                # Only explicit semantic recipe containers wholly matching a section justify a recipe label.
                for b in group:
                    if isinstance(b, tuple) and b[0] == "anchor":
                        anchors[(docpath, b[1])] = sid
                    elif not isinstance(b, tuple):
                        for e in b.iter():
                            if e.get("id"):
                                anchors[(docpath, e.get("id"))] = sid
                sections.append(section)
                section_by_path.setdefault(docpath, sid)
                offset += len(content) + 1
            docsections = [s for s in sections if s["locator"]["document"] == docpath]
            # Match wrapper anchors to their first known child section; missing anchors remain explicit.
            for e in body.iter():
                if e.get("id") and (docpath, e.get("id")) not in anchors:
                    child_id = next(
                        (
                            anchors[(docpath, c.get("id"))]
                            for c in e.iterdescendants()
                            if (docpath, c.get("id")) in anchors
                        ),
                        None,
                    )
                    if child_id:
                        anchors[(docpath, e.get("id"))] = child_id
            recipe_context = None
            section_lookup = {s["id"]: s for s in docsections}
            for e in body.iter():
                boundary = section_lookup.get(anchors.get((docpath, e.get("id"))))
                if boundary is not None:
                    recipe_context = boundary if boundary["kind"] == "recipe" else None
                elif tag(e) in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    recipe_context = None
                if tag(e) not in ("img", "image"):
                    continue
                href = (
                    e.get("src")
                    or e.get("{http://www.w3.org/1999/xlink}href")
                    or e.get("href")
                )
                if not href:
                    continue
                ipath, _ = member(docpath, href)
                raw = read(ipath)
                # Decode and normalize, never deliver active SVG/HTML content.
                try:
                    with Image.open(io.BytesIO(raw)) as im:
                        im.thumbnail((1600, 1600))
                        out = io.BytesIO()
                        im.convert("RGB").save(out, "JPEG", quality=85)
                except Exception as ex:
                    raise IntegrityError("unsupported EPUB image") from ex
                iid = ident(source, ipath)
                asset = emit_asset(out.getvalue())
                caption = (e.get("alt") or "").strip()[:500]
                figure = next(
                    (a for a in e.iterancestors() if tag(a) == "figure"), None
                )
                if figure is not None:
                    captions = [text(c) for c in figure if tag(c) == "figcaption"]
                    caption = next((c[:500] for c in captions if c), caption)
                images.append(
                    {
                        "id": iid,
                        "asset": asset,
                        "document": docpath,
                        "caption": caption,
                        "recipe_context": {
                            "title": recipe_context["title"],
                            "section_id": recipe_context["id"],
                        }
                        if recipe_context
                        else None,
                    }
                )
                # Chapter-level association is honest when exact surrounding section is unavailable.
                for s in docsections:
                    if iid not in s["images"]:
                        s["images"].append(iid)
        nav = next(
            (
                e
                for e in manifest.values()
                if "nav" in (e.get("properties") or "").split()
            ),
            None,
        )
        if nav is not None:
            navpath, _ = member(opfpath, nav.get("href"))
            root = xml(read(navpath))
            navs = root.xpath('//*[local-name()="nav"]')
            primary = next(
                (
                    n
                    for n in navs
                    if "toc"
                    in (n.get("{http://www.idpf.org/2007/ops}type") or "").split()
                ),
                navs[0] if navs else root,
            )
            for a in primary.xpath('.//*[local-name()="a"]'):
                dp, an = member(navpath, a.get("href", ""))
                depth = sum(tag(p) == "ol" for p in a.iterancestors()) - 1
                toc.append(
                    {
                        "title": text(a),
                        "depth": max(0, depth),
                        "document": dp,
                        "anchor": an or None,
                        "section_id": anchors.get((dp, an))
                        if an
                        else section_by_path.get(dp),
                    }
                )
        else:
            ncx = next(
                (
                    e
                    for e in manifest.values()
                    if e.get("media-type") == "application/x-dtbncx+xml"
                ),
                None,
            )
            if ncx is not None:
                navpath, _ = member(opfpath, ncx.get("href"))
                root = xml(read(navpath))
                for n in root.xpath('//*[local-name()="navPoint"]'):
                    label = n.xpath('./*[local-name()="navLabel"]')
                    targets = n.xpath('./*[local-name()="content"]')
                    if not targets:
                        continue
                    dp, an = member(navpath, targets[0].get("src"))
                    depth = sum(tag(p) == "navpoint" for p in n.iterancestors())
                    toc.append(
                        {
                            "title": text(label[0]) if label else "",
                            "depth": depth,
                            "document": dp,
                            "anchor": an or None,
                            "section_id": anchors.get((dp, an))
                            if an
                            else section_by_path.get(dp),
                        }
                    )
    indexed = {s["id"]: s for s in sections}
    for entry in toc:
        section = indexed.get(entry.get("section_id"))
        if section and section["title"].startswith("Section ") and entry["title"]:
            section["title"] = entry["title"]
    return sections, list({im["id"]: im for im in images}.values()), toc


def render_page(path: Path, fmt: str, page: int, destination: Path, edge=1600):
    if page < 1 or not 256 <= edge <= 2500:
        raise IntegrityError("invalid render request")
    if fmt == "PDF":
        prefix = destination.with_suffix("")
        run(
            [
                "pdftoppm",
                "-f",
                page,
                "-l",
                page,
                "-singlefile",
                "-scale-to",
                edge,
                "-png",
                path,
                prefix,
            ]
        )
        rendered = prefix.with_suffix(".png")
        if rendered != destination:
            rendered.replace(destination)
    elif fmt == "DJVU":
        raw = run(
            ["ddjvu", "-format=ppm", f"-page={page}", f"-size={edge}x{edge}", path]
        )
        with Image.open(io.BytesIO(raw)) as im:
            im.save(destination, "PNG")
    else:
        raise IntegrityError("unsupported page format")
    with Image.open(destination) as im:
        if max(im.size) > edge:
            raise IntegrityError("render exceeded pixel limit")


def ocr_page(path, fmt, ordinal, cache: Path, source_hash, *, timeout=90):
    from .ocr import ocr_page as reviewed_ocr

    return reviewed_ocr(
        path, fmt, ordinal, cache, source_hash, render_page, run, timeout=timeout
    )


def paged(path, fmt, source, cache, *, progress=lambda x: None, force_ocr=False):
    # PDF/DjVu ingestion can require OCR even without force_ocr. Admit the
    # whole ingestion before parsing/rendering, not just its eventual OCR call.
    from .ocr_limits import require_ocr_limits

    require_ocr_limits()
    sections = []
    if fmt == "PDF":
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise IntegrityError("encrypted PDF")
        count = len(reader.pages)
        labels = (
            reader.page_labels if "/PageLabels" in reader.trailer["/Root"] else None
        )
        texts = (
            ("" for _ in range(count))
            if force_ocr
            else (p.extract_text() or "" for p in reader.pages)
        )
    else:
        count = int(run(["djvused", path, "-e", "n"]).decode().strip())
        labels = None
        texts = (
            ("" for _ in range(count))
            if force_ocr
            else (
                run(["djvutxt", f"--page={n}", path]).decode("utf-8")
                for n in range(1, count + 1)
            )
        )
    for ordinal, native in enumerate(texts, 1):
        provenance = "native"
        content = native
        assessment = None
        if force_ocr or len(re.sub(r"\W", "", native)) < 40:
            assessment = ocr_page(path, fmt, ordinal, cache, source.split(":")[-1])
            candidate = assessment["text"]
            if candidate.strip():
                content = candidate
                provenance = "ocr"
            else:
                provenance = "ocr-empty" if force_ocr else "native+ocr-empty"
        locator = {
            "kind": "page",
            "physical_page": ordinal,
            "printed_label": labels[ordinal - 1] if labels else None,
        }
        if force_ocr:
            locator["text_selection"] = "forced-ocr"
        if assessment is not None:
            locator["ocr"] = {k: v for k, v in assessment.items() if k != "text"}
            if assessment["decision"]:
                content = assessment["text"]
                provenance = "ocr-reviewed-" + assessment["decision"]["decision"]
            locator["ocr"]["section_text_sha256"] = hashlib.sha256(
                content.encode()
            ).hexdigest()
        sections.append(
            {
                "id": ident(source, ordinal),
                "title": f"Page {ordinal}",
                "text": content,
                "locator": locator,
                "provenance": provenance,
                "kind": "page",
                "images": [],
            }
        )
        if ordinal % 25 == 0:
            progress(
                {
                    "event": "pages_extracted",
                    "format": fmt,
                    "completed": ordinal,
                    "total": count,
                }
            )
    return (
        sections,
        [],
        [{"title": s["title"], "depth": 0, "section_id": s["id"]} for s in sections],
    )
