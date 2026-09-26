"""P4 self-healing: classifies a task stage's failure as retryable or terminal, and sweeps tasks
whose worker died mid-stage (redelivery didn't happen because the worker itself, not just the
task, is gone -- e.g. a redeploy that outpaces Celery's own `acks_late` redelivery window; an
ordinary stage crash already goes through `run_task_stage`'s own retry/terminal path and never
needs this sweep).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from mainforte.celery_app import celery
from mainforte.db.base import utcnow
from mainforte.db.models import Event, Task
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.events.registry import on

log = logging.getLogger(__name__)

MAX_STAGE_RETRIES = 5
STUCK_TASK_STALENESS = timedelta(minutes=10)

# A stage failure whose error text matches one of these is treated as transient (worth retrying
# with backoff). Anything else -- broken stage config, unknown tool name, bad input -- is terminal:
# retrying an identical stage against identical config just reproduces the identical failure.
_TRANSIENT_ERROR_MARKERS = ("timed out", "timeout", "connection", "temporarily unavailable",
                            "econnreset", "econnrefused", "sandbox exec failed", "broken pipe")


def is_retryable_stage_error(*, error_message: str | None) -> bool:
    """Tool-stage failure classification, used by `run_task_stage`'s tool-stage branch before it
    decides between `self.retry(...)` and a terminal `task.failed`. QA failures never reach this --
    they have their own policy below, since a QA failure means a claim didn't ground against real
    events, not that a tool call raised an exception."""
    if not error_message:
        return False
    text = error_message.lower()
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


@on("task.qa.failed", queue="system")
def apply_qa_failure_policy(event: dict[str, Any]) -> None:
    """QA failures are terminal by default: a grounding failure means the stage's own claim didn't
    match its own tool result, and re-running the identical stage reproduces the identical claim,
    so retrying doesn't help. `stage.get("qa_retryable")` is a narrow opt-in for a task author who
    knows a specific check is flaky (e.g. an eventual-consistency lookup) -- not a categorical
    retry-all-QA-failures switch. Idempotent: only acts while the task is still `"qa_failed"`."""
    ws_id = event.get("ws_id")
    payload = event.get("payload") or {}
    task_id = payload.get("task_id")
    stage_index = payload.get("stage_index")
    if not ws_id or not task_id:
        return
    with db_session() as db:
        task = db.get(Task, task_id)
        if task is None or task.ws_id != ws_id or task.status != "qa_failed":
            return
        plan_index = stage_index if isinstance(stage_index, int) and stage_index < len(task.plan) else None
        stage = task.plan[plan_index] if plan_index is not None else {}
        if stage.get("qa_retryable"):
            return
        task.status = "failed"
        emit(db, "task.failed", ws_id=ws_id, actor=("system", None), correlation_id=task.correlation_id,
             payload={"task_id": task_id, "stage_index": stage_index, "thread_id": task.thread_id,
                      "message": "QA failed and stage is not marked qa_retryable"})


@celery.task(name="mainforte.tasks.healing.sweep_stuck_tasks")
def sweep_stuck_tasks() -> int:
    """Beat-driven (parallel to `sweep_outbox`): finds tasks stuck in `"running"` with no
    `task.stage.*` event in the staleness window, implying the worker that owned the in-flight
    stage died before Celery's own redelivery could fire. Re-dispatches `run_task_stage` and emits
    `task.resumed` first, so a resume is visibly distinct in the event log from an ordinary
    retry-driven re-attempt (those already show up as repeated `task.stage.started`/
    `task.stage.ended{ok:false}` pairs)."""
    cutoff = utcnow() - STUCK_TASK_STALENESS
    resumed: list[Task] = []
    with db_session() as db:
        candidates = db.query(Task).filter(Task.status == "running", Task.updated_at < cutoff).all()
        for task in candidates:
            base_corr = task.correlation_id or task.id
            recent = (
                db.query(Event.id)
                .filter(Event.correlation_id == base_corr, Event.type.like("task.stage.%"), Event.ts >= cutoff)
                .first()
            )
            if recent is not None:
                continue
            emit(db, "task.resumed", ws_id=task.ws_id, actor=("system", None), correlation_id=base_corr,
                 payload={"task_id": task.id, "stage_index": task.current_stage, "thread_id": task.thread_id})
            resumed.append(task)

    from mainforte.tasks.work import run_task_stage

    for task in resumed:
        run_task_stage.delay(task_id=task.id, ws_id=task.ws_id)
    return len(resumed)
