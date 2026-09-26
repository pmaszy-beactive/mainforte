"""Sandboxed tool execution on the `work` queue (P2 phase 3). A sandboxed tool call (bash,
read/write/list/grep/glob, browser_*) never runs in-process inside the `chat`-queue router —
it's dispatched here as `run_tool.delay(...)`, which:

1. Creates a fresh `/work/<job_id>` directory (throwaway, one per call).
2. Runs `tools/sandbox_exec.py` as a subprocess, dropped to the `sandbox` uid via `runuser` where
   available (the Debian-based worker image; confirmed it ships `util-linux`) — on hosts without
   `runuser` (local macOS dev) it runs unprivileged as the calling user instead, since there is no
   uid to drop to locally; this is a deliberate dev-only fallback, not a security boundary, and is
   logged loudly so it's never mistaken for the real thing.
3. Enforces a wall-clock timeout and always cleans up the job directory.
4. Emits the `agent.work.*` lifecycle in addition to the `tool.*` events already emitted by the
   router for the started/ended/error transitions — a sandboxed call is also "work" per PLAN.md.

The router polls this task's `AsyncResult` (Celery's Redis-backed result backend, already
configured in celery_app.py) rather than blocking the chat worker thread — same rhythm as the
existing `_is_canceled` Redis polling in `personas/router.py`.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from mainforte.celery_app import celery
from mainforte.config import get_settings
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.ids import new_id

log = logging.getLogger(__name__)

_RUNUSER = shutil.which("runuser")
if _RUNUSER is None:
    log.warning(
        "runuser not found on this host — sandboxed tools will run WITHOUT a uid drop. "
        "This is expected on local macOS dev; it must never be true inside Dockerfile.worker."
    )


def _job_dir(job_id: str) -> Path:
    root = Path(get_settings().sandbox_work_root)
    d = root / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run_sandboxed(*, tool_name: str, tool_input: dict[str, Any], workspace: Path) -> dict[str, Any]:
    spec = json.dumps({"tool": tool_name, "input": tool_input, "workspace": str(workspace)})
    settings = get_settings()
    argv = [sys.executable, "-m", "mainforte.tools.sandbox_exec"]
    if _RUNUSER is not None:
        argv = [_RUNUSER, "-u", str(settings.sandbox_uid), "--", *argv]
    proc = subprocess.run(
        argv, input=spec, capture_output=True, text=True, timeout=settings.sandbox_timeout_seconds,
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


@celery.task(name="mainforte.tasks.work.run_tool", bind=True, acks_late=True,
             reject_on_worker_lost=True)
def run_tool(self, *, tool_name: str, tool_input: dict[str, Any], ws_id: str, correlation_id: str,
             thread_id: str | None = None, persona_id: str | None = None,
             tool_use_id: str | None = None) -> dict[str, Any]:
    job_id = new_id()
    with db_session() as db:
        emit(db, "agent.work.queued", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
             payload={"job_id": job_id, "tool": tool_name, "thread_id": thread_id})

    workspace = _job_dir(job_id)
    with db_session() as db:
        emit(db, "agent.work.started", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
             payload={"job_id": job_id, "tool": tool_name})
    try:
        result = _run_sandboxed(tool_name=tool_name, tool_input=tool_input, workspace=workspace)
    except subprocess.TimeoutExpired:
        msg = f"sandboxed tool {tool_name!r} timed out after {get_settings().sandbox_timeout_seconds}s"
        with db_session() as db:
            emit(db, "agent.work.error", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
                 payload={"job_id": job_id, "tool": tool_name, "message": msg})
        return {"ok": False, "error": msg, "tool_use_id": tool_use_id}
    except Exception as e:
        log.exception("run_tool failed job=%s tool=%s", job_id, tool_name)
        with db_session() as db:
            emit(db, "agent.work.error", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
                 payload={"job_id": job_id, "tool": tool_name, "message": str(e)})
        return {"ok": False, "error": str(e), "tool_use_id": tool_use_id}
    else:
        with db_session() as db:
            emit(db, "agent.work.ended", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
                 payload={"job_id": job_id, "tool": tool_name, "result": result})
        return {"ok": True, "result": result, "tool_use_id": tool_use_id}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
