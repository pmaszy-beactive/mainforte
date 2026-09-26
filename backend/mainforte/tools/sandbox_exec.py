"""Runs ONE tool call inside a job's workspace. Invoked as a subprocess
(`python -m mainforte.tools.sandbox_exec`) by `tasks/work.py`, wrapped in `runuser -u sandbox --`
so this process itself runs as the throwaway uid — never imported and called in-process from the
`chat`-queue router (that's precisely the boundary Phase 2 drew between sandboxed and
non-sandboxed tools).

Protocol: job spec as JSON on stdin (`{"tool": str, "input": dict, "workspace": str}`); a single
JSON object on stdout (`{"ok": true, "result": ...}` or `{"ok": false, "error": str}`). Anything
on stderr is diagnostic only. `workspace` is an absolute path already created by the caller
(`/work/<job_id>`) — every path-taking tool below resolves relative to it and refuses to escape it,
since this is the one thing that must hold even if the uid-drop is somehow ineffective.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


class ToolExecError(RuntimeError):
    pass


# Defense in depth: even though the caller (v1_runuser.py) now launches this whole process with a
# scrubbed env, `_bash` runs arbitrary LLM-directed shell commands — it must never rely on the
# caller having done that, since an inherited full env (worker secrets: DB url, API keys, JWT
# signing secrets) would otherwise be trivially readable via `env`/`printenv` from inside the job.
_BASH_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL")


def _minimal_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _BASH_ENV_ALLOWLIST}


def _resolve(workspace: Path, rel: str) -> Path:
    """A path relative to workspace that cannot escape it, symlinks included."""
    candidate = (workspace / rel).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError:
        raise ToolExecError(f"path {rel!r} escapes the workspace root") from None
    return candidate


def _bash(workspace: Path, *, command: str, **_: Any) -> dict[str, Any]:
    proc = subprocess.run(
        ["/bin/sh", "-c", command], cwd=workspace, capture_output=True, text=True, timeout=30,
        env=_minimal_env(),
    )
    return {"exit_code": proc.returncode, "stdout": proc.stdout[-20_000:], "stderr": proc.stderr[-4_000:]}


def _read_file(workspace: Path, *, path: str, **_: Any) -> dict[str, Any]:
    p = _resolve(workspace, path)
    if not p.is_file():
        raise ToolExecError(f"no such file: {path}")
    return {"content": p.read_text(errors="replace")[:200_000]}


def _write_file(workspace: Path, *, path: str, content: str, **_: Any) -> dict[str, Any]:
    p = _resolve(workspace, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return {"bytes_written": len(content.encode())}


def _list_dir(workspace: Path, *, path: str = ".", **_: Any) -> dict[str, Any]:
    p = _resolve(workspace, path)
    if not p.is_dir():
        raise ToolExecError(f"no such directory: {path}")
    entries = sorted(f"{e.name}/" if e.is_dir() else e.name for e in p.iterdir())
    return {"entries": entries}


def _grep(workspace: Path, *, pattern: str, path: str = ".", **_: Any) -> dict[str, Any]:
    root = _resolve(workspace, path)
    rx = re.compile(pattern)
    hits: list[dict[str, Any]] = []
    files = [root] if root.is_file() else [f for f in root.rglob("*") if f.is_file()]
    for f in files:
        try:
            for i, line in enumerate(f.read_text(errors="replace").splitlines(), start=1):
                if rx.search(line):
                    hits.append({"path": str(f.relative_to(workspace)), "line": i, "text": line[:500]})
                    if len(hits) >= 200:
                        return {"matches": hits, "truncated": True}
        except (UnicodeDecodeError, OSError):
            continue
    return {"matches": hits, "truncated": False}


def _glob(workspace: Path, *, pattern: str, **_: Any) -> dict[str, Any]:
    matches = [str(p.relative_to(workspace)) for p in workspace.rglob("*")
               if fnmatch.fnmatch(str(p.relative_to(workspace)), pattern)]
    return {"matches": sorted(matches)[:500]}


def _browser_home(workspace: Path) -> Path:
    """Where the persistent Chromium profile state lives within a job's workspace — under
    `home/browser/`, the subtree `tasks/work.py` stages from and syncs back to S3 (P2 phase 6),
    rather than directly in the job root, which is thrown away with the rest of the workspace."""
    d = workspace / "home" / "browser"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _browser_navigate(workspace: Path, *, url: str, **_: Any) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    if not re.match(r"^https?://", url):
        raise ToolExecError("url must be http(s)")
    home = _browser_home(workspace)
    state_path = home / "_browser_state.json"
    last_url_path = home / "_browser_last_url.txt"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=str(state_path) if state_path.exists() else None)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        title = page.title()
        final_url = page.url
        ctx.storage_state(path=str(state_path))
        browser.close()
    last_url_path.write_text(final_url)
    return {"title": title, "url": final_url}


def _browser_extract_text(workspace: Path, **_: Any) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    home = _browser_home(workspace)
    state_path = home / "_browser_state.json"
    last_url_path = home / "_browser_last_url.txt"
    if not state_path.exists() or not last_url_path.exists():
        raise ToolExecError("no active browser session — call browser_navigate first")
    last_url = last_url_path.read_text().strip()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=str(state_path))
        page = ctx.new_page()
        # storage_state carries cookies/localStorage only, not "current page" — a fresh page
        # from it starts at about:blank, so we re-navigate to the last URL browser_navigate
        # visited (persisted alongside the state) before reading the DOM.
        page.goto(last_url, wait_until="domcontentloaded", timeout=20_000)
        text = page.evaluate("document.body ? document.body.innerText : ''")
        browser.close()
    return {"text": text[:50_000]}


HANDLERS = {
    "bash": _bash,
    "read_file": _read_file,
    "write_file": _write_file,
    "list_dir": _list_dir,
    "grep": _grep,
    "glob": _glob,
    "browser_navigate": _browser_navigate,
    "browser_extract_text": _browser_extract_text,
}


def main() -> int:
    spec = json.loads(sys.stdin.read())
    tool_name = spec["tool"]
    tool_input = spec.get("input") or {}
    workspace = Path(spec["workspace"]).resolve()
    handler = HANDLERS.get(tool_name)
    out: dict[str, Any]
    if handler is None:
        out = {"ok": False, "error": f"unknown sandboxed tool: {tool_name!r}"}
    else:
        try:
            out = {"ok": True, "result": handler(workspace, **tool_input)}
        except ToolExecError as e:
            out = {"ok": False, "error": str(e)}
        except subprocess.TimeoutExpired:
            out = {"ok": False, "error": "command timed out"}
        except Exception as e:  # the parent process must always get valid JSON back
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
