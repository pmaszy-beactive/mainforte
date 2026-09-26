from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import timedelta

from mainforte.aiproxy import client as aiproxy
from mainforte.aiproxy.keys import get_or_mint
from mainforte.celery_app import celery
from mainforte.db.base import utcnow
from mainforte.db.models import AgentWorker, AuthToken, Event, Memory, Setting, Task, Widget, Workspace
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.events.bus import dispatch, to_dict

log = logging.getLogger(__name__)

WORKER_ID = os.environ.get("MAINFORTE_WORKER_ID") or f"w-{socket.gethostname()}"
ROLLUP_MODEL = "claude-haiku-4-5-20251001"


@celery.task(name="mainforte.tasks.system.worker_heartbeat")
def worker_heartbeat() -> None:
    """Beat-driven self-registration so the admin Workers page sees backbone's standard worker as #1."""
    with db_session() as db:
        w = db.query(AgentWorker).filter_by(container_name=WORKER_ID).first()
        if not w:
            w = AgentWorker(container_name=WORKER_ID, node=os.environ.get("NODE_NAME"), status="online")
            db.add(w)
        w.status = "online"
        w.last_heartbeat = utcnow()
        w.stats = {"pid": os.getpid()}


@celery.task(name="mainforte.tasks.system.sweep_outbox")
def sweep_outbox() -> int:
    """Re-dispatch events that were committed but never published/enqueued (process died mid-dispatch,
    Redis/RabbitMQ blip, redeploy). Runs every 30s; only touches events older than 60s."""
    cutoff = utcnow() - timedelta(seconds=60)
    with db_session() as db:
        rows = (db.query(Event).filter(Event.dispatched_at.is_(None), Event.ts < cutoff)
                .order_by(Event.id.asc()).limit(500).all())
        n = 0
        for ev in rows:
            if dispatch(to_dict(ev)):
                ev.dispatched_at = utcnow()
                n += 1
    return n


@celery.task(name="mainforte.tasks.system.sweep_auth_tokens")
def sweep_auth_tokens() -> int:
    with db_session() as db:
        n = db.query(AuthToken).filter(AuthToken.expires_at < utcnow()).delete()
    return n


async def _summarize(*, api_key: str, transcript: str) -> str:
    system = ("Summarize this chat thread's activity into 2-4 sentences of durable, useful notes "
              "(preferences stated, decisions made, open items). Skip small talk.")
    full = ""
    async for chunk in aiproxy.stream_reply(
        api_key=api_key, model=ROLLUP_MODEL, system=system,
        messages=[{"role": "user", "content": transcript}], max_tokens=400,
    ):
        full += chunk
    return full.strip()


@celery.task(name="mainforte.tasks.system.rollup_threads")
def rollup_threads() -> int:
    """Daily: for each thread with chat.message.created events older than 24h and no existing
    rollup_day Memory row for that thread+day, summarize via ai-proxy and write one Memory row,
    then emit chat.thread.rolled_up."""
    cutoff = utcnow() - timedelta(hours=24)
    n = 0
    with db_session() as db:
        thread_ids = [
            row[0] for row in db.query(Event.correlation_id).distinct()
            .filter(Event.type == "chat.message.created", Event.ts < cutoff, Event.correlation_id.isnot(None))
            .all()
        ]
        for thread_id in thread_ids:
            already = db.query(Memory).filter_by(kind="rollup_day", thread_id=thread_id).first()
            if already:
                continue
            msgs = (
                db.query(Event)
                .filter(Event.correlation_id == thread_id,
                        Event.type.in_(("chat.message.created", "persona.reply.ended")))
                .order_by(Event.id.asc()).limit(200).all()
            )
            if not msgs:
                continue
            ws = db.get(Workspace, msgs[0].ws_id)
            if ws is None:
                continue
            api_key = get_or_mint(db, ws)
            if api_key is None:
                continue
            transcript = "\n".join(
                f"{'User' if ev.type == 'chat.message.created' else 'Persona'}: {ev.payload.get('text', '')}"
                for ev in msgs if ev.payload.get("text")
            )
            if not transcript.strip():
                continue
            try:
                summary = asyncio.run(_summarize(api_key=api_key, transcript=transcript))
            except aiproxy.AiProxyError:
                log.exception("rollup summarize failed for thread %s", thread_id)
                continue
            if not summary:
                continue
            mem = Memory(ws_id=ws.id, kind="rollup_day", thread_id=thread_id, source="rollup", text=summary)
            db.add(mem)
            db.flush()
            emit(db, "chat.thread.rolled_up", ws_id=ws.id, actor=("system", None),
                 payload={"thread_id": thread_id, "memory_id": mem.id, "period": "day"})
            n += 1
    return n


@celery.task(name="mainforte.tasks.system.refresh_due_widgets")
def refresh_due_widgets() -> int:
    """Beat-driven sweep (P2 phase 7): dispatches `refresh_widget` for every active widget that
    carries a `refresh_spec`. Runs every 5min; `refresh_spec` itself owns *when* a given widget is
    actually due (checked inside `refresh_widget`, not here) so this sweep stays a cheap fan-out."""
    with db_session() as db:
        ids = [row[0] for row in db.query(Widget.id)
               .filter(Widget.status == "active", Widget.refresh_spec.isnot(None)).all()]
    for widget_id in ids:
        refresh_widget_task.delay(widget_id=widget_id)
    return len(ids)


@celery.task(name="mainforte.tasks.system.refresh_due_tasks")
def refresh_due_tasks() -> int:
    """Beat-driven sweep (P4 recurrence), parallel to `refresh_due_widgets`: fans out
    `fire_scheduled_task` for every `scheduled` template whose `schedule.next_run_at` has passed.
    Runs every 60s -- more time-sensitive than widgets' 300s, since a task recurrence is often
    wall-clock-meaningful (e.g. "every morning at 8") in a way a data-refresh cadence isn't.
    `next_run_at` is stored as an ISO-8601 UTC string inside the `schedule` JSONB; string comparison
    against another ISO-8601 UTC string sorts identically to a timestamp comparison, so this stays a
    plain JSONB text match rather than needing a cast."""
    from mainforte.tasks.work import fire_scheduled_task

    now_iso = utcnow().isoformat()
    with db_session() as db:
        ids = [
            row[0] for row in db.query(Task.id)
            .filter(Task.status == "scheduled",
                    Task.schedule["active"].astext == "true",
                    Task.schedule["next_run_at"].astext <= now_iso)
            .all()
        ]
    for task_id in ids:
        fire_scheduled_task.delay(task_id=task_id)
    return len(ids)


AGENT_WORKER_PREFIX = "mainforte-agent-worker-"
AGENT_WORKER_MAX_PROVISION_PER_TICK = 2  # cap Jenkins job bursts, mirrors backbone's vexa_spare_pool.py


@celery.task(name="mainforte.tasks.system.reconcile_agent_workers")
def reconcile_agent_workers() -> dict:
    """Converges live AgentWorker count to admin-set desired count via Jenkins provision/destroy
    jobs over SSH-through-bastion (PLAN.md §1.8). Scoped ONLY to rows whose container_name carries
    this reconciler's own `mainforte-agent-worker-N` naming convention — the only names it ever
    assigns via its own Jenkins-triggered deploy calls. Worker #1 (backbone's fixed worker,
    self-registered by `worker_heartbeat` under an arbitrary MAINFORTE_WORKER_ID/hostname-derived
    name) is excluded by construction, never by fragile "is this worker #1" detection.

    Fails soft (never raises) when Jenkins/bastion settings are unset, matching jenkins_ssh's own
    not_configured convention -- this task runs on every beat tick regardless of whether the
    reconciler has been set up for this environment yet."""
    from mainforte.config import get_settings
    from mainforte.jenkins_ssh import _is_configured, trigger_jenkins_build

    s = get_settings()
    if not _is_configured(s):
        return {"ok": False, "reason": "not_configured"}

    with db_session() as db:
        desired_row = db.get(Setting, "workers.desired")
        desired = desired_row.value.get("count", 1) if desired_row else 1

        managed = (
            db.query(AgentWorker)
            .filter(AgentWorker.container_name.like(f"{AGENT_WORKER_PREFIX}%"))
            .order_by(AgentWorker.container_name.asc())
            .all()
        )
        live = len(managed)

        if live == desired:
            return {"ok": True, "live": live, "desired": desired, "action": "none"}

        if live < desired:
            to_add = min(desired - live, AGENT_WORKER_MAX_PROVISION_PER_TICK)
            used = {w.container_name for w in managed}
            n = 0
            idx = 1
            while n < to_add:
                name = f"{AGENT_WORKER_PREFIX}{idx}"
                idx += 1
                if name in used:
                    continue
                result = trigger_jenkins_build(s.jenkins_provision_job, {"WORKER_NAME": name})
                if not result.get("ok"):
                    log.warning("reconcile_agent_workers: provision trigger failed for %s: %s", name, result.get("reason"))
                    break
                emit(db, "worker.provisioning", ws_id=None, actor=("system", None),
                     payload={"container_name": name})
                n += 1
            return {"ok": True, "live": live, "desired": desired, "action": "provision", "triggered": n}

        # live > desired: destroy the newest-named workers first, never worker #1 (excluded above)
        to_remove = min(live - desired, AGENT_WORKER_MAX_PROVISION_PER_TICK)
        victims = list(reversed(managed))[:to_remove]
        n = 0
        for w in victims:
            result = trigger_jenkins_build(s.jenkins_destroy_job, {"WORKER_NAME": w.container_name})
            if not result.get("ok"):
                log.warning("reconcile_agent_workers: destroy trigger failed for %s: %s", w.container_name, result.get("reason"))
                continue
            emit(db, "worker.destroying", ws_id=None, actor=("system", None),
                 payload={"container_name": w.container_name})
            n += 1
        return {"ok": True, "live": live, "desired": desired, "action": "destroy", "triggered": n}


@celery.task(name="mainforte.tasks.system.refresh_widget")
def refresh_widget_task(*, widget_id: str) -> None:
    """Re-runs `refresh_spec`'s tool to get fresh data, rewrites the widget's data.json (bumping
    version), and emits `widget.updated`. `refresh_spec` shape: {"tool": <name in tools.catalog.TOOLS>,
    "input": {...}, "due": {...}} — `due` is interpreted here (e.g. a next-run timestamp updated
    after each successful refresh) so this task, not the sweep, owns cadence."""
    from mainforte.tools.catalog import TOOLS
    from mainforte.widgets import refresh_widget as _refresh

    with db_session() as db:
        widget = db.get(Widget, widget_id)
        if not widget or widget.status != "active" or not widget.refresh_spec:
            return
        spec = widget.refresh_spec
        tool = TOOLS.get(spec.get("tool", ""))
        if tool is None or tool.sandboxed:
            log.warning("widget %s refresh_spec names unusable tool %r", widget_id, spec.get("tool"))
            return
        try:
            data = tool.handler(**spec.get("input", {}))
        except Exception:
            log.exception("widget %s refresh failed", widget_id)
            return
        _refresh(widget, data if isinstance(data, dict) else {"result": data})
        emit(db, "widget.updated", ws_id=widget.ws_id, actor=("system", None), correlation_id=None,
             payload={"widget_id": widget.id, "version": widget.version})
