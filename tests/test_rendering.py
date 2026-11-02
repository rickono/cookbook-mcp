"""Real subprocess enforcement with synthetic decoders, no PDF parser or OCR."""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from cookbook import rendering

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux serving limits")


def decoder(tmp_path, monkeypatch, body):
    executable = tmp_path / "pdftoppm"
    executable.write_text(f"#!{sys.executable}\n" + body)
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    return tmp_path / "page.png"


def render(output):
    rendering.render_page(output.parent / "synthetic.pdf", "PDF", 1, output, 2400)


def test_decoder_inherits_hard_limits_and_renders(tmp_path, monkeypatch):
    output = decoder(
        tmp_path,
        monkeypatch,
        """
import json,resource,sys
from pathlib import Path
from PIL import Image
p=Path(sys.argv[-1])
p.with_suffix('.limits').write_text(json.dumps({str(k):resource.getrlimit(k) for k in [resource.RLIMIT_AS,resource.RLIMIT_CPU,resource.RLIMIT_FSIZE,resource.RLIMIT_CORE]}))
Image.new('RGB',(80,100),'red').save(p.with_suffix('.png'))
""",
    )
    render(output)
    import resource

    limits = json.loads(output.with_suffix(".limits").read_text())
    assert limits[str(resource.RLIMIT_AS)] == [rendering.ADDRESS_BYTES] * 2
    assert limits[str(resource.RLIMIT_CPU)] == [rendering.CPU_SECONDS] * 2
    assert limits[str(resource.RLIMIT_FSIZE)] == [rendering.FILE_BYTES] * 2
    assert limits[str(resource.RLIMIT_CORE)] == [0, 0]


@pytest.mark.parametrize(
    "body",
    [
        "a=bytearray(256*1024**2)\n",  # exceeds inherited address-space limit
        "import sys\nopen(sys.argv[-1]+'.png','wb').write(b'x'*(17*1024**2))\n",
        # Some decoders signal partial/blank output only through stderr, with exit 0.
        "import sys\nfrom PIL import Image\nImage.new('RGB',(10,10)).save(sys.argv[-1]+'.png')\nsys.stderr.write('allocation failed')\n",
    ],
)
def test_resource_failure_or_warning_is_never_an_image_success(
    tmp_path, monkeypatch, body
):
    output = decoder(tmp_path, monkeypatch, body)
    with pytest.raises(rendering.RenderError):
        render(output)


@pytest.mark.parametrize("parent_exits", [False, True])
def test_deadline_and_exited_parent_clean_up_descendants(
    tmp_path, monkeypatch, parent_exits
):
    output = decoder(
        tmp_path,
        monkeypatch,
        f"""
import subprocess,sys,time
from pathlib import Path
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
Path(sys.argv[-1]+'.pid').write_text(str(p.pid))
{"sys.exit(1)" if parent_exits else "time.sleep(30)"}
""",
    )
    monkeypatch.setattr(rendering, "WALL_SECONDS", 0.4)
    started = time.monotonic()
    with pytest.raises(rendering.RenderError):
        render(output)
    assert time.monotonic() - started < 2
    pid = int(output.with_suffix(".pid").read_text())
    # A reparented zombie has stopped executing and holds no memory/resources.
    state = Path(f"/proc/{pid}/stat")
    for _ in range(20):
        if not state.exists() or state.read_text().split()[2] == "Z":
            break
        time.sleep(0.01)
    else:
        pytest.fail("render descendant still running after cleanup")
