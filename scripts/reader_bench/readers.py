"""Reader backends: one stateless CLI call per image (or text-only prompt).

A reader spec names a backend and a model:

  claude:<model>              `claude -p`, no tools, no MCP, no settings, image inline (base64)
  codex:<model>[@<effort>]    `codex exec`, read-only, ephemeral, every tool feature disabled
  opencode:<provider/model>   `opencode run`, per-worker XDG_DATA_HOME (the shared DB hangs)

The command lines are the ones the 2026-10-19 Haiku 5.5 / Luna benchmark ran; changing them
changes the benchmark. A sample label is `<spec>#<n>`: three samples of one spec are three
ballots. The first usage-limit / rate-limit error stops the run (STOP). A reply that uses a
tool, or reads as a refusal, counts as a failed call.
"""

import base64
import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

CONTEXT = (
    "These are scanned pages of cookbooks the user owns, transcribed for their private, "
    "personal searchable index of their own library (nothing is published or "
    "redistributed). Faithful, exact transcription is the task. "
)
CODEX_FLAGS = [
    "-s",
    "read-only",
    "--skip-git-repo-check",
    "--ephemeral",
    "--ignore-rules",
    "--json",
]
for _f in [
    "shell_tool",
    "unified_exec",
    "computer_use",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "in_app_browser",
    "apps",
    "plugins",
    "multi_agent",
    "image_generation",
    "view_image",
    "skill_search",
    "goals",
    "code_mode_host",
]:
    CODEX_FLAGS += ["--disable", _f]
OPENCODE_AUTH = Path.home() / ".local/share/opencode/auth.json"
STOP = threading.Event()
OFFLINE = (
    threading.Event()
)  # set by --offline: any model call is an error (cache-only rebuilds)
LIMIT_RE = re.compile(
    r"(?:usage|session)\s+limit|rate.?limit|quota|429|overloaded|too many requests",
    re.IGNORECASE,
)
REFUSAL_RE = re.compile(
    # First-person prose and copyright notices also occur in the source books.
    # Reject an explicit refusal to perform the task, not those words alone.
    r"^(?:(?:I['’]m\s+)?sorry[,.!]?\s*(?:but\s+)?)?"
    r"(?:I\s+(?:can(?:not|['’]t)|won['’]t)|I['’]m not able to|"
    r"I am not able to|I['’]m unable to|I am unable to|I must decline to)\s+"
    r"(?:help|assist|transcribe|continue|provide|reproduce|comply|fulfill)\b",
    re.IGNORECASE | re.MULTILINE,
)
FILTER_RE = re.compile(r"content filtering policy", re.IGNORECASE)
ALIASES = {
    "haiku": "claude:claude-haiku-5-5",
    "luna": "codex:gpt-6-luna@low",
}  # 2026-10-19 run labels
_local = threading.local()


def parse(spec):
    """'codex:gpt-6-luna@low#2' -> ('codex', 'gpt-6-luna', 'low')."""
    spec = ALIASES.get(spec.split("#")[0], spec.split("#")[0])
    backend, _, model = spec.partition(":")
    model, _, effort = model.partition("@")
    if backend not in BACKENDS or not model:
        raise ValueError(
            f"reader spec {spec!r}: expected claude:MODEL, codex:MODEL[@EFFORT] or opencode:MODEL"
        )
    return backend, model, effort or None


def run_group(cmd, input, timeout, cwd=None, env=None):
    """subprocess.run, but a timeout kills the whole process group (CLI helpers included)."""
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    try:
        out, err = p.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def codex(out, model, effort, prompt, image, timeout):
    effort_flag = ["-c", f'model_reasoning_effort="{effort}"'] if effort else []
    p = run_group(
        [
            "codex",
            "exec",
            "-m",
            model,
            *effort_flag,
            "-C",
            str(out / "empty"),
            *CODEX_FLAGS,
            *(["-i", image] if image else []),
            "-",
        ],
        input=CONTEXT + prompt,
        timeout=timeout,
    )
    text, usage, other, err = "", None, [], None
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "item.completed":
            it = d["item"]
            if it.get("type") == "agent_message":
                text += it.get("text", "")
            elif it.get("type") == "error" and "code-mode host is disabled" in it.get(
                "message", ""
            ):
                pass  # startup notice caused by --disable code_mode_host; not a tool call
            elif it.get("type") != "reasoning":
                other.append(it.get("type"))
        elif d.get("type") == "turn.completed":
            usage = d.get("usage")
        elif d.get("type") in ("error", "turn.failed"):
            err = json.dumps(d)[:300]
    if other:
        err = f"non-message items {other}"
        text = ""
    return text, usage, None, err or (p.stderr.strip()[-300:] if not text else None)


def claude(out, model, effort, prompt, image, timeout):
    content = [{"type": "text", "text": prompt}]
    if image:  # text-only calls (sectioning) send no image
        mt = mimetypes.guess_type(image)[0] or "image/jpeg"
        content.insert(
            0,
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mt,
                    "data": base64.b64encode(Path(image).read_bytes()).decode(),
                },
            },
        )
    msg = {"type": "user", "message": {"role": "user", "content": content}}
    p = run_group(
        [
            "claude",
            "-p",
            "--model",
            model,
            "--system-prompt",
            CONTEXT,
            *(["--effort", effort] if effort else []),
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
        ],
        input=json.dumps(msg),
        timeout=timeout,
        cwd=out / "empty",
    )
    text, usage, cost, err = "", None, None, None
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "assistant":
            for c in d["message"].get("content", []):
                if c.get("type") == "tool_use":
                    err = "tool_use"
        if d.get("type") == "result":
            usage, cost = d.get("usage"), d.get("total_cost_usd")
            if d.get("is_error"):
                err = str(d.get("result"))[:300]
            else:
                text = d.get("result") or ""
    if err:
        text = ""
    return text, usage, cost, err or (p.stderr.strip()[-300:] if not text else None)


def opencode(out, model, effort, prompt, image, timeout):
    """Untested since the 2026-10-19 free-model pilot. Text-only calls are not supported."""
    if not hasattr(_local, "env"):
        d = out / "xdg" / f"w{threading.get_ident()}"
        (d / "opencode").mkdir(parents=True, exist_ok=True)
        dst = d / "opencode" / "auth.json"
        if not dst.exists():
            shutil.copy(OPENCODE_AUTH, dst)
            dst.chmod(0o600)
        _local.env = {**os.environ, "XDG_DATA_HOME": str(d)}
    p = run_group(
        [
            "opencode",
            "run",
            prompt,
            "-m",
            model,
            "--format",
            "json",
            *(["-f", image] if image else []),
        ],
        input="",
        timeout=timeout,
        cwd=out / "empty",
        env=_local.env,
    )
    text, err, tokens = "", None, None
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "text":
            text += d["part"].get("text", "")
        elif d.get("type") == "step_finish":
            tokens = d["part"].get("tokens")
        elif d.get("type") == "error":
            err = json.dumps(d.get("error", d))[:300]
    return text, tokens, None, err or (p.stderr.strip()[-300:] if not text else None)


BACKENDS = {"claude": claude, "codex": codex, "opencode": opencode}


def filtered(record):
    """True when a failed call was refused by the provider's output filter (not a timeout or limit)."""
    return any(FILTER_RE.search(e) for e in record["errors"])


def refused(record):
    """Identify actual provider refusals, including saved records from older runners."""
    return bool(record.get("refused")) or any(
        FILTER_RE.search(error)
        or (
            error.startswith("refusal: ")
            and REFUSAL_RE.search(error.removeprefix("refusal: "))
        )
        for error in record.get("errors", [])
    )


def has_refusal(value):
    """Inspect call records only; authored page text is never a refusal signal."""
    if isinstance(value, dict):
        if "model" in value and "errors" in value:
            return refused(value)
        return any(has_refusal(v) for v in value.values())
    if isinstance(value, list):
        return any(has_refusal(v) for v in value)
    return False


def call(out, reader, prompt, image, attempts=3, timeout=300):
    """One reader sample. Returns (text or None, call record); the record is what costs.py prices."""
    backend, model, effort = parse(reader)
    errors = []
    for i in range(attempts):
        if OFFLINE.is_set():
            raise RuntimeError(
                f"--offline: a {reader} call was needed (missing cache entry)"
            )
        if STOP.is_set():
            return None, {"model": reader, "errors": errors + ["stopped"]}
        t0 = time.time()
        try:
            text, usage, cost, err = BACKENDS[backend](
                out, model, effort, prompt, image, timeout
            )
            if text.strip() and REFUSAL_RE.search(text[:400]):
                err, text = "refusal: " + text[:200], ""
            if err and refused({"errors": [err]}):
                return None, {
                    "model": reader,
                    "errors": errors + [err],
                    "refused": True,
                }
            if text.strip() and "NO_IMAGE" not in text:
                return text, {
                    "model": reader,
                    "seconds": round(time.time() - t0, 1),
                    "attempt": i + 1,
                    "tokens": usage,
                    "cost_usd": cost,
                    "errors": errors,
                }
            errors.append(err or "empty response")
            if err and LIMIT_RE.search(err):
                STOP.set()
                print(json.dumps({"STOP": err}), flush=True)
        except subprocess.TimeoutExpired:
            errors.append(f"timeout {timeout}s")
        time.sleep(5 * (i + 1))
    return None, {"model": reader, "errors": errors}
