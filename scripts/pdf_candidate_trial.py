"""Compare frozen page images inside ocr_sandbox.py; never select accepted text."""

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import time
import unicodedata
from collections import Counter
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(text):
    # Expand vulgar fractions with a separator so 1½ does not become 11/2.
    text = re.sub(
        r"[¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]",
        lambda m: " " + unicodedata.normalize("NFKC", m[0]),
        text,
    )
    text = unicodedata.normalize("NFKC", text).replace("⁄", "/")
    return " ".join(text.lower().split())


def probe_present(text, reference):
    # Keep punctuation and numeric boundaries: 1/2 must not match 11/2.
    return bool(
        re.search(
            r"(?<![\w/])" + re.escape(normalized(reference)) + r"(?![\w/])",
            normalized(text),
        )
    )


def triage(candidates):
    """Uncalibrated review signals only; agreement is never an acceptance signal."""
    suspicious = {}
    numeric = {}
    for name, text in candidates.items():
        suspicious[name] = re.findall(
            r"(?i)(?<!\w)(?:[VY][2348]|Sg|\d*[%*][/,]?)(?=\s*(?:cups?\b|teaspoons?\b|tablespoons?\b|tsp\b|tbsp\b|lb\b|gallons?\b|tamari\b))",
            text,
        )
        numeric[name] = Counter(
            re.findall(r"(?<!\w)\d+(?:[./]\d+)*(?![\d/])", normalized(text))
        )
    first = next(iter(numeric.values()), Counter())
    return {
        "suspicious_quantity_forms": suspicious,
        "numeric_token_disagreement": any(value != first for value in numeric.values()),
        "numeric_tokens": {name: dict(value) for name, value in numeric.items()},
        "decision": "review_required",
        "warning": "Signals include layout/page-number differences and false positives; no automatic correction or acceptance.",
    }


def run(args):
    result = subprocess.run(
        [str(a) for a in args], capture_output=True, timeout=60, check=True
    )
    return (result.stdout + result.stderr).decode(errors="replace")


def compare(source, output):
    from PIL import Image, ImageOps

    from cookbook.ocr import engine_config
    from cookbook.ocr_limits import require_ocr_limits

    require_ocr_limits()
    spec = json.loads(source.read_text())
    folder = source.parent
    image_path = folder / spec["image"]
    native_path = folder / "native.txt"
    if (
        digest(image_path) != spec["image_sha256"]
        or digest(native_path) != spec["native_sha256"]
    ):
        raise ValueError("Frozen evaluation input digest mismatch")
    image = Image.open(image_path).convert("RGB")
    if max(image.size) > 2500:
        raise ValueError("Use bounded staged page images")
    image.save(output / "original.png")
    best = folder / "tessdata_best"
    provenance = {
        "default": engine_config("PDF"),
        "best_eng_sha256": digest(best / "eng.traineddata"),
        "spec_sha256": digest(source),
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2))
    candidates = {"native": native_path.read_text()}
    details = {}

    def recognize(pixels, name, psm, model):
        require_ocr_limits()
        path = output / f"{name}.png"
        pixels.save(path)
        args = ["tesseract", path, output / name, "-l", "eng", "--psm", psm]
        if model:
            args += ["--tessdata-dir", best]
        started = time.monotonic()
        # Staged traineddata has no configs/ directory. Request outputs explicitly;
        # missing named configs can otherwise yield exit 0 but no TSV file.
        log = run(args + ["-c", "tessedit_create_txt=1", "-c", "tessedit_create_tsv=1"])
        (output / f"{name}.log").write_text(log)
        rows = list(
            csv.DictReader(
                io.StringIO((output / f"{name}.tsv").read_text()),
                delimiter="\t",
                quoting=csv.QUOTE_NONE,
            )
        )
        words = [r for r in rows if r["level"] == "5" and r["text"].strip()]
        details[name] = {
            "seconds": time.monotonic() - started,
            "image_sha256": digest(path),
            "psm": psm,
            "word_count": len(words),
            "mean_confidence": sum(float(w["conf"]) for w in words)
            / max(1, len(words)),
        }
        return (output / f"{name}.txt").read_text()

    candidates["default_whole"] = recognize(image, "default_whole", 3, False)
    candidates["best_whole"] = recognize(image, "best_whole", 3, True)
    for contrast in (False, True):
        variant = "best_contrast_regions" if contrast else "best_regions"
        parts = []
        for index, region in enumerate(spec["regions"]):
            box = region["box"]
            if not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                raise ValueError("Invalid region")
            crop = image.crop(
                tuple(round(v * image.size[i % 2]) for i, v in enumerate(box))
            )
            if contrast:
                crop = ImageOps.autocontrast(crop.convert("L"))
            crop = ImageOps.expand(crop, border=12, fill="white")
            name = f"{variant}-{index}"
            parts.append(recognize(crop, name, region.get("psm", 6), True))
        candidates[variant] = "\n\n".join(parts)
    result = {
        "spec": spec,
        "candidates": candidates,
        "details": details,
        "triage": triage(candidates),
        "probes": [
            {
                **probe,
                "matches": {
                    name: probe_present(text, probe["text"])
                    for name, text in candidates.items()
                },
            }
            for probe in spec["probes"]
        ],
    }
    (output / "comparison.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    print(
        json.dumps(
            {
                "book_id": spec["book_id"],
                "page": spec["page"],
                "scores": {
                    name: sum(p["matches"][name] for p in result["probes"])
                    for name in candidates
                },
            }
        )
    )


def main():
    from cookbook.ocr_limits import require_ocr_limits

    require_ocr_limits()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, default=Path("/output"))
    args = parser.parse_args()
    compare(args.spec, args.output)


if __name__ == "__main__":
    main()
