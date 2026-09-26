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

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mainforte.aiproxy.keys import get_or_mint
from mainforte.celery_app import celery
from mainforte.config import get_settings
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.events.task_qa import run_qa_sync
from mainforte.homes import sync_home, stage_home
from mainforte.ids import new_id
from mainforte.sandbox import get_sandbox

log = logging.getLogger(__name__)


def _job_dir(job_id: str) -> Path:
    root = Path(get_settings().sandbox_work_root)
    d = root / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _home_owner(ws_id: str) -> str | None:
    """The user id whose S3 home a workspace's jobs stage/sync against. A workspace is a
    family/household/small-team unit (`Workspace.__doc__`) with one shared browsing identity, not
    one home per member — `owner_id` is the existing, non-nullable FK that answers this."""
    from mainforte.db.models import Workspace

    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        return ws.owner_id if ws is not None else None


def _run_sandboxed(*, tool_name: str, tool_input: dict[str, Any], workspace: Path,
                    ws_id: str) -> dict[str, Any]:
    """Stages the workspace's owning user's S3 home into `workspace/home/` before running the
    tool, and syncs it back after — always, success or failure, per PLAN.md's "our own insurance"
    framing (`finally`, not just the happy path). Delegates the actual isolated execution to
    `sandbox.get_sandbox()` (P4 §4: v1 runuser-subprocess locally, v2 Docker-via-launcherd in
    production) — this function only owns orchestration that's the same regardless of backend."""
    settings = get_settings()
    home_dir = workspace / "home"
    user_id = _home_owner(ws_id)

    if user_id is not None:
        stage_home(user_id, home_dir)
        with db_session() as db:
            emit(db, "worker.home.staged", ws_id=ws_id, actor=("system", None), correlation_id=None,
                 payload={"user_id": user_id})

    try:
        return get_sandbox().run(
            tool_name=tool_name, tool_input=tool_input, workspace=workspace, ws_id=ws_id,
            home_dir=home_dir, timeout_seconds=settings.sandbox_timeout_seconds,
        )
    finally:
        if user_id is not None:
            sync_home(user_id, home_dir)
            with db_session() as db:
                emit(db, "worker.home.synced", ws_id=ws_id, actor=("system", None), correlation_id=None,
                     payload={"user_id": user_id})


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
        result = _run_sandboxed(tool_name=tool_name, tool_input=tool_input, workspace=workspace, ws_id=ws_id)
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
                     thread_id: str | None, persona_id: str | None, task_id: str) -> dict[str, Any]:
    """Runs one stage's tool call, sandboxed-or-not exactly like the chat router does, but
    in-process on the `work` queue (this function only ever runs from inside `run_task_stage`,
    itself already a `work`-queue task — no further dispatch/poll indirection needed).

    In-process (non-sandboxed) handlers also receive the executing run's own `task_id` — a stage's
    literal `input` dict is cloned verbatim on every recurring firing (see `fire_scheduled_task`),
    so it can never itself name the run's id; a tool that needs to know "which run am I" (e.g. to
    look up its own template's prior runs) must accept it as an injected kwarg instead."""
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
            result = _run_sandboxed(tool_name=tool_name, tool_input=tool_input, workspace=workspace, ws_id=ws_id)
        except Exception as e:
            outcome: dict[str, Any] = {"ok": False, "error": str(e)}
        else:
            outcome = {"ok": True, "result": result}
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    else:
        try:
            outcome = {"ok": True, "result": tool.handler(**tool_input, task_id=task_id)}
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
        if task.status not in ("approved", "running", "retrying"):
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

    if stage_type == "qa":
        with db_session() as db:
            task = db.get(Task, task_id)
            from mainforte.db.models import Workspace

            ws = db.get(Workspace, ws_id)
            api_key = get_or_mint(db, ws) if ws is not None else None
            result = run_qa_sync(db, ws_id=ws_id, base_corr=base_corr, api_key=api_key,
                                  first_stage=task.last_qa_stage, last_stage=task.current_stage)
            if result["passed"]:
                emit(db, "task.qa.passed", ws_id=ws_id, actor=("system", None), correlation_id=stage_corr,
                     payload={"task_id": task_id, "stage_index": stage_index, "thread_id": thread_id,
                              "checked_stages": result["checked_stages"]})
                task.last_qa_stage = task.current_stage
                emit(db, "task.stage.ended", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                     payload={"task_id": task_id, "stage_index": stage_index, "ok": True, "thread_id": thread_id})
                task.current_stage = stage_index + 1
                advance = task.current_stage < len(task.plan)
                if not advance:
                    task.status = "completed"
                    emit(db, "task.completed", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                         payload={"task_id": task_id, "thread_id": thread_id})
            else:
                emit(db, "task.qa.failed", ws_id=ws_id, actor=("system", None), correlation_id=stage_corr,
                     payload={"task_id": task_id, "stage_index": stage_index, "thread_id": thread_id,
                              "checked_stages": result["checked_stages"], "unverified": result["unverified"]})
                task.status = "qa_failed"
                emit(db, "task.stage.ended", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                     payload={"task_id": task_id, "stage_index": stage_index, "ok": False, "thread_id": thread_id})
                advance = False
        if advance:
            run_task_stage.delay(task_id=task_id, ws_id=ws_id)
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
        correlation_id=stage_corr, thread_id=thread_id, persona_id=persona_id, task_id=task_id,
    )

    if not outcome["ok"] and not stage.get("continue_on_error"):
        from mainforte.tasks.healing import MAX_STAGE_RETRIES, is_retryable_stage_error

        error_message = outcome.get("error", "stage failed")
        retryable = is_retryable_stage_error(error_message=error_message)
        with db_session() as db:
            task = db.get(Task, task_id)
            emit(db, "task.stage.ended", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                 payload={"task_id": task_id, "stage_index": stage_index, "ok": False, "thread_id": thread_id})
            if retryable and task.attempt < MAX_STAGE_RETRIES:
                task.attempt += 1
                task.status = "retrying"
                attempt = task.attempt
            else:
                task.status = "failed"
                emit(db, "task.failed", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                     payload={"task_id": task_id, "stage_index": stage_index, "thread_id": thread_id,
                              "message": error_message})
                attempt = None
        if attempt is not None:
            raise self.retry(countdown=min(2 ** attempt * 5, 300))
        return

    with db_session() as db:
        task = db.get(Task, task_id)
        emit(db, "task.stage.ended", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
             payload={"task_id": task_id, "stage_index": stage_index, "ok": outcome["ok"], "thread_id": thread_id})
        task.current_stage = stage_index + 1
        task.attempt = 0
        advance = task.current_stage < len(task.plan)
        if not advance:
            task.status = "completed"
            emit(db, "task.completed", ws_id=ws_id, actor=("system", None), correlation_id=base_corr,
                 payload={"task_id": task_id, "thread_id": thread_id})

    if advance:
        run_task_stage.delay(task_id=task_id, ws_id=ws_id)


@celery.task(name="mainforte.tasks.work.fire_scheduled_task")
def fire_scheduled_task(*, task_id: str) -> str | None:
    """Fires one occurrence of a recurring `Task` template (`status="scheduled"`): clones
    `plan`/`persona_id`/`thread_id` into a fresh run row rather than resetting the template in
    place (see `tasks/schedule.py`'s module docstring for why). The run row carries
    `result.schedule_template_id` back to the template so `tasks/schedule.py`'s `task.completed`/
    `task.failed` handlers can find their way back and update `next_run_at`/`consecutive_failures`.
    Recurring runs skip the per-occurrence approval gate -- the human approved the recurrence
    itself when they attached the schedule -- so the new row starts `status="approved"`."""
    from mainforte.db.models import Task

    with db_session() as db:
        template = db.get(Task, task_id)
        if template is None or template.status != "scheduled" or not (template.schedule or {}).get("active"):
            return None
        run_id = new_id()
        run = Task(
            id=run_id, ws_id=template.ws_id, thread_id=template.thread_id, persona_id=template.persona_id,
            status="approved", plan=template.plan, current_stage=0,
            result={"schedule_template_id": task_id}, correlation_id=run_id,
        )
        db.add(run)
        emit(db, "task.scheduled", ws_id=template.ws_id, actor=("system", None), correlation_id=template.correlation_id,
             payload={"task_id": run_id, "template_task_id": task_id, "thread_id": template.thread_id})

    run_task_stage.delay(task_id=run_id, ws_id=template.ws_id)
    return run_id
