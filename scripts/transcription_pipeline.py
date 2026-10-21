"""Build a private reading prototype from saved, validated scan evidence."""

import argparse
import hashlib
import json
from pathlib import Path

from cookbook.ocr_limits import require_ocr_limits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--boundaries", type=Path)
    parser.add_argument("--revisions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reading", choices=("raw", "review"), default="raw")
    parser.add_argument(
        "--title", default="Scanned transcription — unapproved reading copy"
    )
    args = parser.parse_args()

    # Admission precedes all book-derived input reads and processing imports.
    require_ocr_limits()
    from cookbook.transcription import snapshot_digest
    from cookbook.transcription_boundaries import (
        propose_boundaries,
        validate_boundaries,
    )
    from cookbook.transcription_export import export_epub
    from cookbook.transcription_review import (
        render_review_report,
        review_queue,
        reviewed_view,
    )

    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))

    def encoded(value):
        return (
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")

    if args.output.exists():
        raise ValueError(
            "Output must be a new directory; retained evidence cannot be overwritten"
        )
    snapshot = load(args.snapshot)
    identity = snapshot_digest(snapshot)
    boundaries = (
        load(args.boundaries) if args.boundaries else propose_boundaries(snapshot)
    )
    validate_boundaries(snapshot, boundaries)
    revisions = load(args.revisions) if args.revisions else []
    if not isinstance(revisions, list):
        raise TypeError("Revisions must be a JSON list")
    context = {"revisions": revisions, "selections": boundaries["selections"]}
    view = reviewed_view(snapshot, **context)
    queue = review_queue(snapshot, **context)
    report = render_review_report(snapshot, **context)
    epub = export_epub(
        snapshot,
        boundaries=boundaries,
        revisions=revisions,
        reading=args.reading,
        title=args.title,
    )
    payloads = {
        "snapshot.json": encoded(snapshot),
        "boundaries.json": encoded(boundaries),
        "revisions.json": encoded(revisions),
        "reading-view.json": encoded(view),
        "review-queue.json": encoded(queue),
        "review.html": report.encode("utf-8"),
        "reading.epub": epub,
    }
    manifest = {
        "version": "scanned-transcription-trial.v1",
        "snapshot_sha256": identity,
        "source_sha256": snapshot["edition"]["source_sha256"],
        "reading": args.reading,
        "approval": "none",
        "files": {
            name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in payloads.items()
        },
    }
    # Construct and validate everything before creating the destination.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, content in payloads.items():
        (args.output / name).write_bytes(content)
    (args.output / "manifest.json").write_bytes(encoded(manifest))
    print(
        json.dumps(
            {
                "snapshot_sha256": identity,
                "review_items": len(queue),
                "selections": len(boundaries["selections"]),
                "approval": "none",
            }
        )
    )


if __name__ == "__main__":
    main()
