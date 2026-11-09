"""Rebuild pinned reader assets with npm; never runs at reader startup."""

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1] / "src/cookbook/book_vendor"
FILES = {
    "pdfjs-dist": {
        "build/pdf.mjs",
        "build/pdf.worker.mjs",
        "web/pdf_viewer.mjs",
        "web/pdf_viewer.css",
        "LICENSE",
    },
    "epubjs": {"dist/epub.min.js", "license"},
    "jszip": {"dist/jszip.min.js", "LICENSE.markdown"},
}
PREFIXES = ("standard_fonts/", "cmaps/", "wasm/", "web/images/")


def main():
    pins = json.loads((ROOT / "packages.json").read_text())
    if {pin["name"] for pin in pins} != set(FILES):
        raise ValueError("unexpected reader dependency")
    with tempfile.TemporaryDirectory(prefix="cookbook-reader-vendor-") as directory:
        temporary = Path(directory)
        packed = subprocess.run(
            [
                "npm",
                "pack",
                *(pin["name"] + "@" + pin["version"] for pin in pins),
                "--pack-destination",
                directory,
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        packages = json.loads(packed.stdout)
        for pin in pins:
            package = next(p for p in packages if p["name"] == pin["name"])
            if (
                package["version"] != pin["version"]
                or package["integrity"] != pin["integrity"]
            ):
                raise ValueError("reader dependency integrity mismatch")
            with tarfile.open(temporary / package["filename"]) as archive:
                for member in archive.getmembers():
                    name = member.name.removeprefix("package/")
                    if (
                        not member.isfile()
                        or ".." in PurePosixPath(name).parts
                        or name.startswith("/")
                    ):
                        continue
                    if name in FILES[pin["name"]] or (
                        pin["name"] == "pdfjs-dist" and name.startswith(PREFIXES)
                    ):
                        path = temporary / "prepared" / pin["name"] / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(archive.extractfile(member).read())
        assets = {
            str(path.relative_to(temporary / "prepared")): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in (temporary / "prepared").rglob("*")
            if path.is_file()
        }
        bundle = temporary / "assets.zip"
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(assets):
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                archive.writestr(entry, (temporary / "prepared" / name).read_bytes())
        shutil.copyfile(bundle, ROOT / "assets.zip")
        (ROOT / "assets.json").write_text(
            json.dumps(assets, sort_keys=True, indent=2) + "\n"
        )
        for pin in pins:
            target = ROOT / pin["name"]
            if target.exists():
                shutil.rmtree(target)
            print(pin["name"] + " " + pin["version"])


if __name__ == "__main__":
    main()
