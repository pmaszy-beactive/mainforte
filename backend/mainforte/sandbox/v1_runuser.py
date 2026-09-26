"""Isolation v1: today's `runuser`-wrapped subprocess, moved verbatim from `tasks/work.py`. Default
backend everywhere except production — local dev has neither `runuser` nor Docker Desktop
guaranteed, and this is the only backend that degrades gracefully (loudly) rather than failing hard
when the privilege-drop tool is missing."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from mainforte.config import get_settings

log = logging.getLogger(__name__)

_RUNUSER = shutil.which("runuser")
if _RUNUSER is None:
    log.warning(
        "runuser not found on this host — sandboxed tools will run WITHOUT a uid drop. "
        "This is expected on local macOS dev; it must never be true inside Dockerfile.worker."
    )

# `runuser` drops the uid but does not sanitize the environment, so the sandboxed process would
# otherwise inherit every secret in the worker's own env (DB url, API keys, JWT signing secrets —
# see config.py's Settings). Pass an explicit minimal env instead of the parent's full environment.
_SANDBOX_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL")


def _minimal_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _SANDBOX_ENV_ALLOWLIST}


class RunuserSandbox:
    def run(self, *, tool_name: str, tool_input: dict[str, Any], workspace: Path, ws_id: str,
            home_dir: Path, timeout_seconds: int) -> dict[str, Any]:
        settings = get_settings()
        spec = json.dumps({"tool": tool_name, "input": tool_input, "workspace": str(workspace)})
        argv = [sys.executable, "-m", "mainforte.tools.sandbox_exec"]
        if _RUNUSER is not None:
            argv = [_RUNUSER, "-u", str(settings.sandbox_uid), "--", *argv]
        proc = subprocess.run(
            argv, input=spec, capture_output=True, text=True, timeout=timeout_seconds,
            env=_minimal_env(),
        )

        if proc.returncode != 0 and not proc.stdout.strip():
            raise RuntimeError(f"sandbox_exec exited {proc.returncode}: {proc.stderr[-2000:]}")
        try:
            out = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            raise RuntimeError(f"sandbox_exec produced no valid JSON: stdout={proc.stdout[-1000:]!r} "
                                f"stderr={proc.stderr[-1000:]!r}") from None
        if not out.get("ok"):
            raise RuntimeError(out.get("error", "sandboxed tool failed with no error message"))
        return out["result"]
