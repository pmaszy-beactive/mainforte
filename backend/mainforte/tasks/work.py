"""Sandboxed tool execution on the `work` queue (P2 phase 3), plus the task-stage pipeline
(P2 phase 5). A sandboxed tool call (bash, read/write/list/grep/glob, browser_*) never runs
in-process inside the `chat`-queue router — it's dispatched here as `run_tool.delay(...)`, which:

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

`run_task_stage` (bottom of this file) drives a `Task` row's `plan` one stage at a time, on this
same `work` queue: a `tool` stage calls a catalog tool via the same path as `run_tool` above
(reused directly, not duplicated), a `wait`/`await_input` stage emits `task.blocked` and stops the
chain for a human to resume via the tasks API. Each stage's own tool call gets a fresh
`correlation_id` derived from the task id, so the Governor (P2 phase 4) can ground stage-level
action claims exactly the way it grounds chat-turn claims.
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


# ---------------------------------------------------------------- task stage pipeline (P2 phase 5)


def _run_stage_tool(*, tool_name: str, tool_input: dict[str, Any], ws_id: str, correlation_id: str,
                     thread_id: str | None, persona_id: str | None) -> dict[str, Any]:
    """Runs one stage's tool call, sandboxed-or-not exactly like the chat router does, but
    in-process on the `work` queue (this function only ever runs from inside `run_task_stage`,
    itself already a `work`-queue task — no further dispatch/poll indirection needed)."""
    from mainforte.tools.catalog import TOOLS

    tool = TOOLS.get(tool_name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool {tool_name!r}"}
    with db_session() as db:
        emit(db, "tool.started", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
             payload={"thread_id": thread_id, "persona_id": persona_id, "name": tool_name, "input": tool_input})
    if tool.sandboxed:
        job_id = new_id()
        workspace = _job_dir(job_id)
        try:
            result = _run_sandboxed(tool_name=tool_name, tool_input=tool_input, workspace=workspace)
        except Exception as e:
            outcome: dict[str, Any] = {"ok": False, "error": str(e)}
        else:
            outcome = {"ok": True, "result": result}
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    else:
        try:
            outcome = {"ok": True, "result": tool.handler(**tool_input)}
        except Exception as e:
            outcome = {"ok": False, "error": str(e)}
    with db_session() as db:
        if outcome["ok"]:
            emit(db, "tool.ended", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
                 payload={"thread_id": thread_id, "persona_id": persona_id, "name": tool_name,
                          "result": outcome["result"]})
        else:
            emit(db, "tool.error", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
                 payload={"thread_id": thread_id, "persona_id": persona_id, "name": tool_name,
                          "message": outcome["error"]})
    return outcome


@celery.task(name="mainforte.tasks.work.run_task_stage", bind=True, acks_late=True,
             reject_on_worker_lost=True)
def run_task_stage(self, *, task_id: str, ws_id: str) -> None:
    """Advances one `Task` row by exactly one stage, then either chains itself for the next stage,
    or stops (blocked/completed/failed). Never runs two stages in one invocation — each stage gets
    its own `tool.*`/`agent.work.*` events under a stage-scoped `correlation_id`
    (`{task.correlation_id}:{stage_index}`) so the Governor can ground each stage's claims
    independently, and so a redelivered/retried invocation re-touches only the stage it names."""
    from mainforte.db.models import Task

    with db_session() as db:
        task = db.get(Task, task_id)
        if task is None or task.ws_id != ws_id:
            log.warning("run_task_stage: task %s not found in ws %s", task_id, ws_id)
            return
        if task.status not in ("approved", "running"):
            log.info("run_task_stage: task %s status=%s, not runnable, skipping", task_id, task.status)
            return
        if task.current_stage >= len(task.plan):
            task.status = "completed"
            emit(db, "task.completed", ws_id=ws_id, actor=("system", None), correlation_id=task.correlation_id,
                 payload={"task_id": task_id, "thread_id": task.thread_id})
            return
        stage = task.plan[task.current_stage]
        stage_index = task.current_stage
        task.status = "running"
        base_corr = task.correlation_id or task_id
        thread_id = task.thread_id
        persona_id = task.persona_id
        stage_corr = f"{base_corr}:{stage_index}"
        emit(db, "task.stage.started", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
             payload={"task_id": task_id, "stage_index": stage_index, "stage": stage, "thread_id": thread_id})

    stage_type = stage.get("type", "tool")

    if stage_type == "await_input":
        with db_session() as db:
            task = db.get(Task, task_id)
            task.status = "blocked"
            emit(db, "task.blocked", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                 payload={"task_id": task_id, "stage_index": stage_index, "thread_id": thread_id,
                          "reason": stage.get("prompt", "This task needs your input to continue.")})
        return

    if stage_type != "tool":
        with db_session() as db:
            task = db.get(Task, task_id)
            task.status = "failed"
            emit(db, "task.failed", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                 payload={"task_id": task_id, "stage_index": stage_index, "thread_id": thread_id,
                          "message": f"unknown stage type {stage_type!r}"})
        return

    outcome = _run_stage_tool(
        tool_name=stage["tool"], tool_input=stage.get("input", {}), ws_id=ws_id,
        correlation_id=stage_corr, thread_id=thread_id, persona_id=persona_id,
    )

    with db_session() as db:
        task = db.get(Task, task_id)
        if not outcome["ok"] and not stage.get("continue_on_error"):
            task.status = "failed"
            emit(db, "task.stage.ended", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                 payload={"task_id": task_id, "stage_index": stage_index, "ok": False, "thread_id": thread_id})
            emit(db, "task.failed", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                 payload={"task_id": task_id, "stage_index": stage_index, "thread_id": thread_id,
                          "message": outcome.get("error", "stage failed")})
            return
        emit(db, "task.stage.ended", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
             payload={"task_id": task_id, "stage_index": stage_index, "ok": outcome["ok"], "thread_id": thread_id})
        task.current_stage = stage_index + 1
        advance = task.current_stage < len(task.plan)
        if not advance:
            task.status = "completed"
            emit(db, "task.completed", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                 payload={"task_id": task_id, "thread_id": thread_id})

    if advance:
        run_task_stage.delay(task_id=task_id, ws_id=ws_id)
