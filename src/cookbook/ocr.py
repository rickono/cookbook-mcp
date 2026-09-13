"""Local English OCR, derived-image correction and digest-bound human review."""

from __future__ import annotations
import csv
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import html
import io
import json
from pathlib import Path
import re
import subprocess
import shlex
import tempfile
from PIL import Image, __version__ as pillow_version
import numpy as np
from .storage import IntegrityError, atomic_write, canonical, digest_file, file_lock
from .ocr_limits import require_ocr_limits

POLICY = "ocr-review-v2"
SETTINGS = {
    "policy": POLICY,
    "orientation_method": "word-geometry-v1",
    "edge": 2500,
    "probe_edge": 1600,
    "psm": 3,
    "minimum_confidence": 85,
    "low_word_confidence": 60,
    "maximum_low_fraction": 0.15,
    "quantity_confidence": 85,
    "orientation_margin": 8,
    "skew_range": 5,
    "skew_step": 0.25,
}


class ReviewRequired(IntegrityError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def key_for(config):
    return sha(canonical(config))[:32]


@lru_cache(maxsize=4)
def engine_config(fmt):
    def version(args):
        r = subprocess.run(args, capture_output=True, timeout=15, check=False)
        line = (r.stdout + r.stderr).decode(errors="replace").splitlines()[0]
        if r.returncode and not (
            args[0] == "ddjvu"
            and r.returncode == 1
            and line.startswith("DDJVU --- DjVuLibre-")
        ):
            raise IntegrityError("cannot identify OCR renderer")
        return line

    langs = subprocess.run(
        ["tesseract", "--list-langs"], capture_output=True, timeout=15, check=True
    )
    match = re.search(r'in "([^"]+)"', langs.stdout.decode())
    if not match:
        raise IntegrityError("cannot identify OCR language data")
    lang = Path(match[1]) / "eng.traineddata"
    return {
        **SETTINGS,
        "engine": version(["tesseract", "--version"]),
        "renderer": version(
            ["pdftoppm", "-v"] if fmt == "PDF" else ["ddjvu", "--help"]
        ),
        "language": "eng",
        "language_sha256": digest_file(lang)[0],
        "pillow": pillow_version,
        "numpy": np.__version__,
    }


def recognize(image, folder, runner, timeout):
    require_ocr_limits()
    image.save(folder / "input.png")
    raw = runner(
        ["tesseract", folder / "input.png", "stdout", "-l", "eng", "--psm", "3", "tsv"],
        timeout=timeout,
    )
    words = []
    lines = {}
    try:
        for row in csv.DictReader(
            io.StringIO(raw.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
        ):
            word = (row.get("text") or "").strip()
            if row.get("level") != "5" or not word:
                continue
            conf = float(row["conf"])
            if not np.isfinite(conf) or not 0 <= conf <= 100:
                raise ValueError("invalid confidence")
            words.append(
                {
                    "text": word,
                    "confidence": conf,
                    "width": int(row["width"]),
                    "height": int(row["height"]),
                }
            )
            line = tuple(row[k] for k in ("block_num", "par_num", "line_num"))
            lines.setdefault(line, []).append(word)
    except (ValueError, KeyError, UnicodeError):
        raise IntegrityError("invalid OCR output") from None
    mean = sum(w["confidence"] * len(w["text"]) for w in words) / max(
        1, sum(len(w["text"]) for w in words)
    )
    return {
        "text": "\n".join(" ".join(w) for w in lines.values()),
        "words": words,
        "mean_confidence": mean,
    }


def deskew(image):
    """Projection-profile search: rotate derived pixels only, expand to avoid clipping."""
    small = image.convert("L")
    small.thumbnail((900, 900))
    pixels = np.asarray(small)
    # Otsu's between-class variance for unevenly lit scans; never alter OCR pixels here.
    hist = np.bincount(pixels.ravel(), minlength=256).astype(float)
    weights = np.cumsum(hist)
    means = np.cumsum(hist * np.arange(256))
    variance = (means[-1] * weights - means * weights[-1]) ** 2 / np.maximum(
        weights * (weights[-1] - weights), 1
    )
    threshold = int(np.argmax(variance[:-1]))
    mask = Image.fromarray((pixels <= threshold).astype("uint8") * 255)

    def score(angle):
        rotated = mask.rotate(
            float(angle), resample=Image.Resampling.NEAREST, expand=True, fillcolor=0
        )
        rows = np.asarray(rotated, dtype=float).sum(axis=1) / 255
        return float(np.sum(np.diff(rows) ** 2))

    angles = np.arange(
        -SETTINGS["skew_range"], SETTINGS["skew_range"] + 0.01, SETTINGS["skew_step"]
    )
    scores = [score(a) for a in angles]
    best = int(np.argmax(scores))
    angle = float(angles[best])
    zero = score(0)
    gain = scores[best] / max(zero, 1)
    if gain < 1.15 or abs(angle) < 0.25:
        angle = 0.0
    corrected = (
        image.rotate(
            angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
        )
        if angle
        else image.copy()
    )
    corrected.thumbnail((2500, 2500))
    return corrected, angle, gain


def assess(result, *, orientation_margin, skew_angle, blank=False):
    if blank:
        return []
    reasons = []
    words = result["words"]
    if not words:
        return ["no_text_on_nonblank_page"]
    if result["mean_confidence"] < SETTINGS["minimum_confidence"]:
        reasons.append("low_mean_confidence")
    low = sum(w["confidence"] < SETTINGS["low_word_confidence"] for w in words) / len(
        words
    )
    if low > SETTINGS["maximum_low_fraction"]:
        reasons.append("many_uncertain_words")
    if any(
        re.search(r"[\d¼½¾⅓⅔⅛⅜⅝⅞]", w["text"])
        and w["confidence"] < SETTINGS["quantity_confidence"]
        for w in words
    ):
        reasons.append("uncertain_quantity")
    if len(words) < 4:
        reasons.append("sparse_text")
    if orientation_margin < SETTINGS["orientation_margin"]:
        reasons.append("ambiguous_orientation")
    if abs(skew_angle) >= SETTINGS["skew_range"]:
        reasons.append("skew_search_limit")
    return reasons


def process_image(image: Image.Image, folder: Path, runner, *, timeout=90):
    require_ocr_limits()
    image = image.convert("RGB")
    probe = image.copy()
    probe.thumbnail((1600, 1600))
    gray = np.asarray(probe.convert("L"))
    blank = float(np.mean(gray < 245)) < 0.00001
    if blank:
        result = {"text": "", "words": [], "mean_confidence": 100.0}
        corrected = image.copy()
        rotation = 0
        skew = 0.0
        margin = 100.0
        gain = 1.0
    else:
        candidates = []
        for rotation in (0, 90, 180, 270):
            candidate = recognize(
                probe.rotate(rotation, expand=True), folder, runner, timeout
            )
            # Confidence weighted by recognized word count limits tiny high-confidence false matches.
            long_words = [w for w in candidate["words"] if len(w["text"]) >= 3]
            horizontal = sum(w["width"] > w["height"] * 1.15 for w in long_words) / max(
                1, len(long_words)
            )
            score = (
                candidate["mean_confidence"]
                * min(1, len(candidate["words"]) / 8)
                * horizontal
            )
            candidates.append((score, rotation, candidate))
        candidates.sort(key=lambda c: (c[0], -c[1]), reverse=True)
        _, rotation, _ = candidates[0]
        margin = candidates[0][0] - candidates[1][0]
        corrected, skew, gain = deskew(image.rotate(rotation, expand=True))
        result = recognize(corrected, folder, runner, timeout)
    result.update(
        rotation_ccw=rotation,
        deskew_ccw=skew,
        orientation_margin=margin,
        skew_gain=gain,
        blank=blank,
    )
    result["reasons"] = assess(
        result, orientation_margin=margin, skew_angle=skew, blank=blank
    )
    image.save(folder / "original.png")
    corrected.save(folder / "corrected.png")
    result["original_image_sha256"] = digest_file(folder / "original.png")[0]
    result["corrected_image_sha256"] = digest_file(folder / "corrected.png")[0]
    return result


def load_record(cache, review_id):
    if not re.fullmatch("[a-f0-9]{32}", review_id):
        raise IntegrityError("invalid review ID")
    record = json.loads((cache / "v2" / review_id / "result.json").read_bytes())
    payload = record["payload"]
    if (
        sha(canonical(payload)) != record["result_sha256"]
        or key_for(payload["config"]) != review_id
    ):
        raise IntegrityError("OCR cache mismatch")
    for name in ("original", "corrected"):
        if (
            digest_file(cache / "v2" / review_id / (name + ".png"))[0]
            != payload["result"][name + "_image_sha256"]
        ):
            raise IntegrityError("OCR review image mismatch")
    return record


def effective(record, cache, review_id):
    result = record["payload"]["result"]
    text = result["text"]
    decision = None
    path = cache / "reviews" / (review_id + ".json")
    if path.exists():
        d = json.loads(path.read_bytes())
        if d["result_sha256"] == record["result_sha256"]:
            if d["decision"] not in ("accept", "correct", "nontext"):
                raise IntegrityError("invalid OCR decision")
            if d["decision"] == "correct":
                text = d["text"]
            if d["decision"] == "nontext":
                text = ""
            decision = {k: v for k, v in d.items() if k != "text"}
            if d["decision"] == "correct":
                decision["corrected_text_sha256"] = sha(text.encode())
    return {
        "review_id": review_id,
        "result_sha256": record["result_sha256"],
        "source_sha256": record["payload"]["config"]["sha256"],
        "physical_page": record["payload"]["config"]["page"],
        "policy": POLICY,
        "text": text,
        "text_sha256": sha(text.encode()),
        "reasons": result["reasons"],
        "pending": bool(result["reasons"]) and decision is None,
        "decision": decision,
        "rotation_ccw": result["rotation_ccw"],
        "deskew_ccw": result["deskew_ccw"],
        "mean_confidence": result["mean_confidence"],
    }


def ocr_page(path, fmt, ordinal, cache, source_hash, render, runner, *, timeout=90):
    require_ocr_limits()
    config = {
        **engine_config(fmt),
        "format": fmt,
        "page": ordinal,
        "sha256": source_hash,
    }
    review_id = key_for(config)
    directory = cache / "v2" / review_id
    with file_lock(cache / ".ocr.lock"):
        if not (directory / "result.json").exists():
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.TemporaryDirectory(dir=directory) as tmp:
                folder = Path(tmp)
                render(path, fmt, ordinal, folder / "source.png", 2500)
                with Image.open(folder / "source.png") as im:
                    result = process_image(im, folder, runner, timeout=timeout)
                payload = {"config": config, "result": result}
                for name in ("original.png", "corrected.png"):
                    (folder / name).replace(directory / name)
                atomic_write(
                    directory / "result.json",
                    canonical(
                        {"payload": payload, "result_sha256": sha(canonical(payload))}
                    ),
                )
        return effective(load_record(cache, review_id), cache, review_id)


def decide(cache, review_id, result_sha256, decision, text=None):
    """Called only on explicit human action; no automatic approval of flagged output."""
    with file_lock(cache / ".ocr.lock"):
        record = load_record(cache, review_id)
        if record["result_sha256"] != result_sha256:
            raise IntegrityError("stale OCR review")
        if decision not in ("accept", "correct", "nontext"):
            raise IntegrityError("invalid OCR decision")
        if decision == "correct" and (
            not isinstance(text, str) or not text.strip() or len(text) > 1000000
        ):
            raise IntegrityError("correction text required")
        d = {
            "review_id": review_id,
            "result_sha256": result_sha256,
            "decision": decision,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        if decision == "correct":
            d["text"] = text
        atomic_write(cache / "reviews" / (review_id + ".json"), canonical(d))
    return effective(record, cache, review_id)


def write_review_page(cache, items, output):
    cards = []
    pages = output.parent / (output.stem + "-pages")
    pages.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in items:
        record = load_record(cache, item["review_id"])
        e = effective(record, cache, item["review_id"])
        if not e["pending"]:
            continue
        directory = (cache / "v2" / e["review_id"]).resolve()
        # Inline bytes make the report portable, script-free and independent of file URL permissions.
        import base64

        def image(name):
            return (
                "data:image/png;base64,"
                + base64.b64encode((directory / name).read_bytes()).decode()
            )

        title = html.escape(item.get("book_title", "Source page"))
        command = (
            "PYTHONPATH=src uv run python -m cookbook.cli review-ocr --ocr-cache "
            + shlex.quote(str(cache.resolve()))
            + " --id "
            + e["review_id"]
            + " --result-sha256 "
            + e["result_sha256"]
        )
        card = f'''<article><h2>{title} — Physical page {e["physical_page"]}</h2><p>Source SHA-256: <code>{e["source_sha256"]}</code></p>
        <p>Reasons: {html.escape(", ".join(e["reasons"]))}</p><p>Counterclockwise correction: {e["rotation_ccw"]}° + {e["deskew_ccw"]}° deskew</p>
        <div class="images"><figure><figcaption>Original page</figcaption><img src="{image("original.png")}"></figure><figure><figcaption>Corrected OCR copy</figcaption><img src="{image("corrected.png")}"></figure></div>
        <pre>{html.escape(e["text"])}</pre><p>Review ID: <code>{e["review_id"]}</code><br>Result SHA-256: <code>{e["result_sha256"]}</code></p><p>After inspecting this exact result, run one command from the project directory:</p>
        <p>Accept the recognized text:</p><pre>{html.escape(command + " --decision accept")}</pre>
        <p>Mark as illustration/blank (no searchable OCR text):</p><pre>{html.escape(command + " --decision nontext")}</pre>
        <p>For a correction use <code>--decision correct --text-file /absolute/path/to/corrected-text.txt</code> with the same command prefix.</p></article>'''
        atomic_write(
            pages / (e["review_id"] + ".html"),
            (
                """<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><style>body{font:16px system-ui;margin:24px}.images{display:flex}figure{width:50%;margin:8px}img{max-width:100%}pre{white-space:pre-wrap}code{overflow-wrap:anywhere}</style>"""
                + card
            ).encode(),
        )
        cards.append(
            f'<p><a href="{pages.name}/{e["review_id"]}.html">{title} — Physical page {e["physical_page"]} — {html.escape(", ".join(e["reasons"]))}</a><br><small>Source {e["source_sha256"]}</small></p>'
        )
    page = (
        """<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Cookbook OCR review</title><style>body{font:16px system-ui;margin:32px;max-width:1500px;background:#faf9f5;color:#222}article{border-top:1px solid #bbb;padding:24px 0}.images{display:flex;gap:16px}figure{margin:0;width:50%}img{max-width:100%}pre{white-space:pre-wrap;background:white;padding:20px}code{overflow-wrap:anywhere}</style><h1>OCR pages awaiting your review</h1><p>Compare quantities, words and page orientation. Use review-ocr to accept, supply corrected text, or mark a page as non-text. Each action requires the exact result hash below. No approval is submitted by this report.</p>"""
        + "".join(cards)
    )
    atomic_write(output, page.encode())
    return len(cards)
