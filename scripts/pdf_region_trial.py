"""Bounded regional renders retain complete PDF layers; use ocr_sandbox.py."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from pdf_candidate_trial import digest, probe_present, run


def main():
    from cookbook.ocr_limits import require_ocr_limits

    require_ocr_limits()
    from PIL import Image

    from cookbook.ocr import engine_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    output = Path("/output")
    folder = args.spec.parent
    spec = json.loads(args.spec.read_text())
    source = folder / "book.pdf"
    sha = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != spec["source_sha256"]:
        raise ValueError("Source digest mismatch")
    page = spec["page"]
    info = run(["pdfinfo", "-f", page, "-l", page, source])
    rotation = re.search(r"(?:Page\s+\d+\s+rot:|Page rot:)\s+(-?\d+)", info)
    if rotation is None or int(rotation[1]) % 360:
        raise ValueError("This regional trial requires verified zero PDF page rotation")
    match = re.search(
        r"(?:Page\s+\d+\s+size:|Page size:)\s+(\d+(?:\.\d+)?) x (\d+(?:\.\d+)?)", info
    )
    if not match:
        raise ValueError("Cannot identify page dimensions")
    width, height = map(float, match.groups())
    results = {
        "spec": spec,
        "engine": engine_config("PDF"),
        "best_sha256": digest(folder / "tessdata_best/eng.traineddata"),
        "regions": [],
    }
    for index, region in enumerate(spec["regions"]):
        item = {"region": region, "candidates": {}}
        for edge in (2300, 4600):
            require_ocr_limits()
            box = region["box"]
            if not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                raise ValueError("Invalid region")
            scale = edge / max(width, height)
            x, y, right, bottom = [
                round(v * dimension * scale)
                for v, dimension in zip(box, (width, height, width, height))
            ]
            if max(right - x, bottom - y) > 2500:
                raise ValueError("Regional image exceeds 2500-pixel bound")
            prefix = output / f"region-{index}-{edge}"
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
                    "-x",
                    x,
                    "-y",
                    y,
                    "-W",
                    right - x,
                    "-H",
                    bottom - y,
                    "-png",
                    source,
                    prefix,
                ]
            )
            image = prefix.with_suffix(".png")
            with Image.open(image) as pixels:
                if max(pixels.size) > 2500:
                    raise ValueError("Renderer returned oversized region")
            for best in (False, True):
                require_ocr_limits()
                name = f"{edge}-{'best' if best else 'default'}"
                dest = output / f"region-{index}-{name}"
                command = ["tesseract", image, dest, "-l", "eng", "--psm", "6"]
                if best:
                    command += ["--tessdata-dir", folder / "tessdata_best"]
                log = run(
                    command
                    + ["-c", "tessedit_create_txt=1", "-c", "tessedit_create_tsv=1"]
                )
                dest.with_suffix(".log").write_text(log)
                text = dest.with_suffix(".txt").read_text()
                item["candidates"][name] = {
                    "text": text,
                    "image_sha256": digest(image),
                    "matches": [probe_present(text, p) for p in region["probes"]],
                }
        results["regions"].append(item)
    (output / "comparison.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
