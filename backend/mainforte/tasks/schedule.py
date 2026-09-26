"""P4 task recurrence. A recurring `Task` is a template row (`status="scheduled"`); each firing
clones `plan`/`persona_id`/`thread_id` into a **new** run row (fresh id/correlation_id) rather than
resetting the template in place, so each run's event history (and the QA windowing in
`events/task_qa.py`) stays unambiguous per-row -- the same reasoning `Widget.version` bumps on
refresh instead of the widget getting a new row each time (a widget refresh is a data blob update;
a task run is a discrete execution with its own audit trail).

`schedule` shape (JSONB on the template row): {"kind": "interval"|"cron",
"interval_seconds"|"cron": ..., "next_run_at": iso_ts, "active": true, "consecutive_failures": 0}.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from celery.schedules import crontab
from sqlalchemy.orm import Session

from mainforte.db.base import utcnow
from mainforte.db.models import Task
from mainforte.events import emit, on

MAX_CONSECUTIVE_FAILURES = 3


def _parse_crontab(spec: str) -> crontab:
    """`spec` is a standard 5-field cron string ("minute hour day-of-month month day-of-week"),
    the same field order `crontab` itself takes positionally."""
    minute, hour, dom, month, dow = spec.split()
    return crontab(minute=minute, hour=hour, day_of_month=dom, month_of_year=month, day_of_week=dow)


def compute_next_run_at(schedule: dict[str, Any], *, after: datetime | None = None) -> datetime:
    after = after or utcnow()
    if schedule["kind"] == "interval":
        return after + timedelta(seconds=schedule["interval_seconds"])
    if schedule["kind"] == "cron":
        c = _parse_crontab(schedule["cron"])
        return after + c.remaining_estimate(after)
    raise ValueError(f"unknown schedule kind {schedule['kind']!r}")


def set_task_schedule(db: Session, task: Task, schedule_in: dict[str, Any]) -> None:
    """Shared by the schedule routes and `create_task`'s optional `schedule` field. Validates just
    enough to compute `next_run_at`; a bad `cron` string surfaces as a plain ValueError, which the
    route layer turns into a 422."""
    kind = schedule_in["kind"]
    if kind not in ("interval", "cron"):
        raise ValueError(f"schedule.kind must be 'interval' or 'cron', got {kind!r}")
    if kind == "interval" and not schedule_in.get("interval_seconds"):
        raise ValueError("schedule.interval_seconds is required for kind='interval'")
    if kind == "cron" and not schedule_in.get("cron"):
        raise ValueError("schedule.cron is required for kind='cron'")

    schedule = {
        "kind": kind,
        "active": True,
        "consecutive_failures": 0,
    }
    if kind == "interval":
        schedule["interval_seconds"] = schedule_in["interval_seconds"]
    else:
        schedule["cron"] = schedule_in["cron"]
    schedule["next_run_at"] = compute_next_run_at(schedule).isoformat()

    task.schedule = schedule
    task.status = "scheduled"


def _disable_schedule(task: Task) -> None:
    schedule = dict(task.schedule or {})
    schedule["active"] = False
    task.schedule = schedule


def _record_run_outcome(db: Session, *, template: Task, ok: bool) -> None:
    """Advances the template's `next_run_at` on success (resetting the failure streak); on failure,
    increments `consecutive_failures` and disables the recurrence once `MAX_CONSECUTIVE_FAILURES` is
    hit, emitting `task.disabled` -- a silently-repeating broken recurring task is worse than one
    that surfaces via chat and stops."""
    schedule = dict(template.schedule or {})
    if not schedule.get("active"):
        return
    if ok:
        schedule["consecutive_failures"] = 0
        schedule["next_run_at"] = compute_next_run_at(schedule).isoformat()
        template.schedule = schedule
        return

    schedule["consecutive_failures"] = schedule.get("consecutive_failures", 0) + 1
    if schedule["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
        schedule["active"] = False
        template.schedule = schedule
        emit(db, "task.disabled", ws_id=template.ws_id, actor=("system", None),
             correlation_id=template.correlation_id,
             payload={"task_id": template.id, "thread_id": template.thread_id,
                      "reason": f"{schedule['consecutive_failures']} consecutive failures"})
    else:
        schedule["next_run_at"] = compute_next_run_at(schedule).isoformat()
        template.schedule = schedule


def _template_for_run(db: Session, run_task_id: str) -> Task | None:
    """A fired run row carries `result.schedule_template_id` back to its template (see
    `fire_scheduled_task`) -- `task.completed`/`task.failed` only name the run's own id, not the
    template's, so this is how the feedback handlers below find their way back."""
    run = db.get(Task, run_task_id)
    if run is None or not run.result:
        return None
    template_id = run.result.get("schedule_template_id")
    if not template_id:
        return None
    return db.get(Task, template_id)


@on("task.completed", queue="system")
def _on_scheduled_run_completed(event: dict[str, Any]) -> None:
    from mainforte.db.session import db_session

    payload = event.get("payload") or {}
    task_id = payload.get("task_id")
    if not task_id:
        return
    with db_session() as db:
        template = _template_for_run(db, task_id)
        if template is not None:
            _record_run_outcome(db, template=template, ok=True)


@on("task.failed", queue="system")
def _on_scheduled_run_failed(event: dict[str, Any]) -> None:
    from mainforte.db.session import db_session

    payload = event.get("payload") or {}
    task_id = payload.get("task_id")
    if not task_id:
        return
    with db_session() as db:
        template = _template_for_run(db, task_id)
        if template is not None:
            _record_run_outcome(db, template=template, ok=False)
