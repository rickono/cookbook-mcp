"""Private, bounded PDF survey and OCR comparisons; always use ocr_sandbox.py."""

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path


def run(args, timeout=90):
    return subprocess.run(
        [str(x) for x in args], capture_output=True, check=True, timeout=timeout
    ).stdout.decode("utf-8", errors="replace")


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False))


def survey(source, output):
    from cookbook.ocr_limits import require_ocr_limits

    require_ocr_limits()
    info = run(["pdfinfo", source])
    count = int(re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)[1])
    selected = sorted({max(1, round(count * f)) for f in (0.25, 0.5, 0.75)})
    run(["pdftotext", "-layout", source, output / "native.txt"], timeout=120)
    pages = (output / "native.txt").read_text().split("\f")
    fonts = run(["pdffonts", source])
    images = "\n".join(
        run(["pdfimages", "-f", page, "-l", page, "-list", source]) for page in selected
    )
    (output / "pdfinfo.txt").write_text(info)
    (output / "fonts.txt").write_text(fonts)
    (output / "images.txt").write_text(images)
    image_pages = {}
    for line in images.splitlines()[2:]:
        cols = line.split()
        if len(cols) < 14:
            continue
        try:
            page, width, height = int(cols[0]), int(cols[3]), int(cols[4])
            image_pages.setdefault(page, []).append(
                {
                    "width": width,
                    "height": height,
                    "kind": cols[2],
                    "x_ppi": float(cols[12]),
                    "y_ppi": float(cols[13]),
                }
            )
        except ValueError:
            continue
    stats = []
    for i in range(count):
        text = pages[i] if i < len(pages) else ""
        stats.append(
            {
                "page": i + 1,
                "alphanumeric": sum(c.isalnum() for c in text),
                "replacement_chars": text.count("\ufffd"),
                "images": image_pages.get(i + 1, []) if i + 1 in selected else None,
            }
        )
    for page in selected:
        prefix = output / f"page-{page}"
        run(
            [
                "pdftoppm",
                "-f",
                page,
                "-l",
                page,
                "-singlefile",
                "-scale-to",
                2300,
                "-jpeg",
                "-jpegopt",
                "quality=92",
                source,
                prefix,
            ]
        )
        (output / f"page-{page}.txt").write_text(
            pages[page - 1] if page <= len(pages) else ""
        )
        run(
            [
                "pdftotext",
                "-f",
                page,
                "-l",
                page,
                "-bbox-layout",
                source,
                output / f"page-{page}.html",
            ]
        )
    result = {
        "pages": count,
        "page_stats": stats,
        "sample_pages": selected,
        "font_report": fonts,
        "text_pages": sum(p["alphanumeric"] >= 40 for p in stats),
        "sample_image_pages": len(image_pages),
        "image_metadata_scope": "sample_pages_only",
        "sample_image_sha256": {
            str(page): hashlib.sha256(
                (output / f"page-{page}.jpg").read_bytes()
            ).hexdigest()
            for page in selected
        },
        "warning": "Text presence and OCR confidence do not establish correctness.",
    }
    save(output / "survey.json", result)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("page_stats", "font_report")}
        )
    )


def main():
    from cookbook.ocr_limits import require_ocr_limits

    require_ocr_limits()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["survey"])
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("/output"))
    args = parser.parse_args()
    start = time.monotonic()
    hasher = hashlib.sha256()
    with args.source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    save(
        args.output / "source.json",
        {"sha256": hasher.hexdigest(), "filename": args.source.name},
    )
    survey(args.source, args.output)
    print(json.dumps({"elapsed_seconds": time.monotonic() - start}))


if __name__ == "__main__":
    main()
