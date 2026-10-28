"""Bounded serving renderer. Offline ingestion keeps its separate OCR guard."""

import os
import signal
import subprocess
import sys
from pathlib import Path

if __name__ != "__main__":
    from .storage import IntegrityError
else:
    IntegrityError = RuntimeError

# Below the existing Machine/VM ceilings. These are serving admission limits,
# not a replacement for the OCR sandbox or an increase to its resource budget.
ADDRESS_BYTES = 128 * 1024**2
FILE_BYTES = 16 * 1024**2
CPU_SECONDS = 10
WALL_SECONDS = 15


class RenderError(IntegrityError):
    pass


def render_page(path, fmt, page, destination, edge=1600):
    if fmt not in {"PDF", "DJVU"} or page < 1 or not 256 <= edge <= 2400:
        raise RenderError("invalid render request")
    if sys.platform != "linux":
        raise RenderError("bounded serving renderer requires Linux")
    process = None
    try:
        errors = Path(destination).with_suffix(".stderr")
        with errors.open("wb") as error_output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    str(path),
                    fmt,
                    str(page),
                    str(destination),
                    str(edge),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=error_output,
                start_new_session=True,
            )
        if process.wait(timeout=WALL_SECONDS) != 0 or errors.stat().st_size:
            raise RenderError("render unavailable within serving limits")
        from PIL import Image

        with Image.open(destination) as im:
            if max(im.size) > edge or im.format != "PNG":
                raise RenderError("invalid rendered image")
            im.verify()
    except (OSError, subprocess.SubprocessError, ValueError):
        raise RenderError("render unavailable within serving limits") from None
    finally:
        if process is not None:
            # Also remove descendants after a failed or unexpectedly exited parent.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def worker():
    # No preexec_fn: the caller is a multithreaded service. Limits are installed
    # in this fresh interpreter, before loading a document or starting a decoder.
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_BYTES, ADDRESS_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_BYTES, FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    path, fmt, page, destination, edge = sys.argv[1:]
    if fmt == "PDF":
        os.execvp(
            "pdftoppm",
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
                str(Path(destination).with_suffix("")),
            ],
        )
    else:
        # Keep PPM output on disk rather than an unbounded captured pipe.
        ppm = Path(destination).with_suffix(".ppm")
        with ppm.open("wb") as out:
            subprocess.run(
                ["ddjvu", "-format=ppm", f"-page={page}", f"-size={edge}x{edge}", path],
                stdout=out,
                check=True,
            )
        from PIL import Image

        with Image.open(ppm) as im:
            if max(im.size) > int(edge):
                raise ValueError("render exceeded pixel limit")
            im.save(destination, "PNG")


if __name__ == "__main__":
    worker()
