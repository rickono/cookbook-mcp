"""Read only the five approved fixtures; assess representative pages without publishing."""

import argparse
import json
from pathlib import Path
import sqlite3
import time
from cookbook.extract import epub, ocr_page
from cookbook.ocr import write_review_page
from cookbook.storage import atomic_write, canonical, digest_file

p = argparse.ArgumentParser()
p.add_argument("--build", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--ocr-cache", type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True, mode=0o700)
inputs = {
    k: Path(v) for k, v in json.loads((a.build / "inputs.json").read_bytes()).items()
}
db = sqlite3.connect(
    inputs["runtime/index.sqlite"].resolve().as_uri() + "?mode=ro&immutable=1", uri=True
)
db.row_factory = sqlite3.Row
books = db.execute(
    "select b.calibre_id,b.title,s.* from books b join sources s on s.id=b.source_id"
).fetchall()
assert {b["calibre_id"] for b in books} == {5, 40, 6, 9, 45}
start = time.monotonic()
report = {"pages": [], "epubs": []}
items = []
for book in books:
    source = inputs[book["original_path"]]
    before = digest_file(source)
    assert before[0] == book["sha256"]
    if book["format"] == "EPUB":
        sections, images, toc = epub(
            source, book["id"], lambda data: "ephemeral-evaluation"
        )
        item = {
            "calibre_id": book["calibre_id"],
            "sections": len(sections),
            "recipe_sections": sum(s["kind"] == "recipe" for s in sections),
            "toc_entries": len(toc),
            "unresolved_toc": sum(t.get("section_id") is None for t in toc),
            "images": len(images),
        }
        report["epubs"].append(item)
        print(json.dumps({"event": "epub_evaluated", **item}), flush=True)
    else:
        pages = {20}
        for provenance in ("ocr", "native+ocr-empty"):
            row = db.execute(
                "select ordinal from sections where source_id=? and provenance=? and ordinal>=9 order by ordinal limit 1",
                (book["id"], provenance),
            ).fetchone()
            if row:
                pages.add(row[0] + 1)
        for page in sorted(pages):
            result = ocr_page(source, book["format"], page, a.ocr_cache, book["sha256"])
            item = {
                "calibre_id": book["calibre_id"],
                "format": book["format"],
                "physical_page": page,
                **{k: v for k, v in result.items() if k != "text"},
            }
            report["pages"].append(item)
            items.append(
                {
                    **result,
                    "book_title": book["title"],
                    "calibre_id": book["calibre_id"],
                }
            )
            print(
                json.dumps(
                    {
                        "event": "page_evaluated",
                        "calibre_id": book["calibre_id"],
                        "physical_page": page,
                        "pending": result["pending"],
                        "reasons": result["reasons"],
                        "rotation_ccw": result["rotation_ccw"],
                        "deskew_ccw": result["deskew_ccw"],
                    }
                ),
                flush=True,
            )
    assert digest_file(source) == before
report["pending_pages"] = write_review_page(
    a.ocr_cache, items, a.output / "review.html"
)
report["elapsed_seconds"] = time.monotonic() - start
atomic_write(a.output / "evaluation.json", canonical(report))
print(
    json.dumps(
        {
            "event": "finished",
            "evaluated_pages": len(items),
            "pending_pages": report["pending_pages"],
            "elapsed_seconds": report["elapsed_seconds"],
        }
    )
)
