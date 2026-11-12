"""Model adapter for the EDA review pilot. It lives outside the pipeline repo and is used for measurement only.

generate(prompt, schema, image_paths) -> dict calls the codex CLI once, with the same arguments the pipeline provider uses
(ctxcomp/providers.py), a strict JSON schema and one --image per figure. It does not go through the pipeline gateway or
ContextBuilder, so every call is logged here instead: review_calls.jsonl gets one line per call (prompt hash, images,
seconds, token usage when the CLI reports it, outcome). A hard call budget stops a runaway loop.

Environment: EDA_REVIEW_CODEX (path to codex.exe; default PATH, then %LOCALAPPDATA%\\OpenAI\\Codex\\bin\\*\\codex.exe), EDA_REVIEW_MODEL (default gpt-6.1-terra), EDA_REVIEW_EFFORT (default high), EDA_REVIEW_MAX_CALLS (default 22),
EDA_REVIEW_CALL_LOG (default ./review_calls.jsonl), EDA_REVIEW_TIMEOUT seconds (default 1800).
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

MODEL = os.environ.get("EDA_REVIEW_MODEL", "gpt-6.1-terra")
EFFORT = os.environ.get("EDA_REVIEW_EFFORT", "high")
MAX_CALLS = int(os.environ.get("EDA_REVIEW_MAX_CALLS", "22"))
LOG = Path(os.environ.get("EDA_REVIEW_CALL_LOG", "review_calls.jsonl"))
TIMEOUT = int(os.environ.get("EDA_REVIEW_TIMEOUT", "1800"))
_calls = 0


def _usage(stdout):
    """Token usage from the CLI's JSON event stream, when present."""
    use = None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        for k in ("usage", "token_usage"):
            u = ev.get(k) or (ev.get("msg") or {}).get(k) or (ev.get("info") or {}).get(k) if isinstance(ev, dict) else None
            if isinstance(u, dict):
                use = u
    return use


def generate(prompt, schema, image_paths):
    global _calls
    if _calls >= MAX_CALLS:
        raise RuntimeError(f"call budget reached ({MAX_CALLS}); raise EDA_REVIEW_MAX_CALLS to continue")
    _calls += 1
    exe = os.environ.get("EDA_REVIEW_CODEX") or shutil.which("codex") or shutil.which("codex.cmd")
    if not exe:
        cands = sorted(Path(os.environ.get("LOCALAPPDATA", "")).glob("OpenAI/Codex/bin/*/codex.exe"), key=lambda x: x.stat().st_mtime)
        exe = str(cands[-1]) if cands else None
    if not exe:
        raise RuntimeError("codex CLI not found on PATH")
    rec = {"n": _calls, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "prompt_bytes": len(prompt.encode("utf-8")),
           "images": [Path(p).name for p in image_paths], "model": MODEL, "effort": EFFORT, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sp, rp = Path(tmp) / "response.schema.json", Path(tmp) / "response.json"
            sp.write_text(json.dumps(schema), encoding="utf-8")
            cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only", "--ignore-user-config",
                   "-c", 'approval_policy="never"', "--color", "never", "--json", "--output-schema", str(sp),
                   "--output-last-message", str(rp), "--model", MODEL, "-c", f'model_reasoning_effort="{EFFORT}"']
            for p in image_paths:
                cmd += ["--image", str(p)]
            cmd.append("-")
            r = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, cwd=tmp, timeout=TIMEOUT)
            out = r.stdout.decode("utf-8", "replace")
            rec.update(returncode=r.returncode, usage=_usage(out))
            if r.returncode != 0 or not rp.is_file():
                rec["stderr_tail"] = r.stderr.decode("utf-8", "replace")[-800:]
                raise RuntimeError(f"codex exec failed (return code {r.returncode})")
            ans = json.loads(rp.read_text(encoding="utf-8-sig"))
        rec["outcome"] = "OK"
        return ans
    except Exception as exc:
        rec.setdefault("outcome", f"ERROR {type(exc).__name__}: {exc}")
        raise
    finally:
        rec["seconds"] = round(time.time() - t0, 1)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
