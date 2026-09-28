from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Numeric, case, func
from sqlalchemy.orm import Session

from mainforte import __version__
from mainforte.auth.deps import Identity, require_superuser
from mainforte.db.base import utcnow
from mainforte.db.models import (
    AgentWorker,
    ApiError,
    Event,
    Membership,
    Persona,
    Price,
    Setting,
    Subscription,
    Task,
    User,
    Workspace,
)
from mainforte.db.session import get_db
from mainforte.db_settings import BASTION_JENKINS_FIELDS, bastion_jenkins_status, set_bastion_jenkins_config
from mainforte.events.bus import to_dict
from mainforte.events.types import EVENT_TYPES

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_superuser)])


@router.get("/users")
def users(q: str = "", limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    query = db.query(User)
    if q:
        query = query.filter(User.email.ilike(f"%{q}%") | User.name.ilike(f"%{q}%"))
    rows = query.order_by(User.created_at.desc()).limit(limit).all()
    plans = dict(db.query(Membership.user_id, func.max(Workspace.plan)).join(Workspace, Workspace.id == Membership.workspace_id)
                 .filter(Membership.user_id.in_([u.id for u in rows])).group_by(Membership.user_id).all()) if rows else {}
    return {"users": [{"id": u.id, "email": u.email, "name": u.name, "role": u.role, "created_at": u.created_at.isoformat(),
                       "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                       "locale": u.locale, "plan": plans.get(u.id, "trial")} for u in rows]}


@router.get("/finances")
def finances(db: Session = Depends(get_db)):
    # mrr/active_subscriptions/failed_payments read subscriptions.status, the real gating source
    # of truth (never Workspace.plan) — kept in sync by the webhook + hourly/on-login reconcile job.
    plan_counts = dict(db.query(Workspace.plan, func.count()).group_by(Workspace.plan).all())

    monthly_amount = case(
        (Price.interval == "year", Price.amount_cents / 12.0),
        else_=Price.amount_cents,
    )
    mrr_cents = (
        db.query(func.coalesce(func.sum(monthly_amount), 0))
        .select_from(Subscription)
        .join(Price, Price.id == Subscription.price_id)
        .filter(Subscription.status == "active")
        .scalar()
    )
    active_subscriptions = db.query(func.count()).filter(Subscription.status == "active").scalar() or 0
    failed_payments = (
        db.query(func.count()).filter(Subscription.status.in_(["past_due", "unpaid"])).scalar() or 0
    )

    cost_expr = func.sum(func.cast(Event.payload["cost_usd"].astext, Numeric))
    in_tok_expr = func.sum(func.cast(Event.payload["input_tokens"].astext, Numeric))
    out_tok_expr = func.sum(func.cast(Event.payload["output_tokens"].astext, Numeric))
    usage_rows = (
        db.query(Event.ws_id, Workspace.name, in_tok_expr, out_tok_expr, cost_expr)
        .join(Workspace, Workspace.id == Event.ws_id)
        .filter(Event.type == "billing.usage.recorded")
        .group_by(Event.ws_id, Workspace.name)
        .order_by(cost_expr.desc())
        .all()
    )
    usage_by_workspace = [
        {"ws_id": ws_id, "ws_name": ws_name, "input_tokens": int(in_tok or 0), "output_tokens": int(out_tok or 0),
         "cost_usd": float(cost or 0.0)}
        for ws_id, ws_name, in_tok, out_tok, cost in usage_rows
    ]
    ai_cost_usd = sum(row["cost_usd"] for row in usage_by_workspace)

    return {"mrr_cents": int(round(mrr_cents)), "active_subscriptions": active_subscriptions,
            "failed_payments": failed_payments, "ai_cost_usd": ai_cost_usd, "ai_charged_usd": 0.0,
            "workspaces_by_plan": plan_counts, "usage_by_workspace": usage_by_workspace}


@router.get("/errors")
def errors(limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    rows = db.query(ApiError).order_by(ApiError.ts.desc()).limit(limit).all()
    return {"errors": [{"id": e.id, "ts": e.ts.isoformat(), "type": e.type, "message": e.message, "user_id": e.user_id,
                        "ws_id": e.ws_id, "path": e.path} for e in rows]}


@router.get("/jobs")
def jobs():
    from mainforte.celery_app import celery, queue_depths

    running: list[dict] = []
    try:
        insp = celery.control.inspect(timeout=1.0)
        for worker, tasks in (insp.active() or {}).items():
            for t in tasks:
                running.append({"id": t["id"], "name": t["name"], "queue": t.get("delivery_info", {}).get("routing_key"),
                                "started_at": t.get("time_start"), "worker": worker,
                                "workspace_id": (t.get("kwargs") or {}).get("ws_id")})
    except Exception:
        pass
    return {"queues": [{"name": n, "depth": d} for n, d in queue_depths().items()], "running": running}


@router.get("/scheduled-jobs")
def scheduled_jobs():
    """The real cron/interval jobs — read directly off `celery.conf.beat_schedule` so this view can
    never drift from what's actually configured (see celery_app.py). Distinct from `/jobs`, which is
    a live, ephemeral snapshot of whatever happens to be running right now on any queue."""
    from mainforte.celery_app import celery

    schedule = celery.conf.beat_schedule or {}
    return {
        "jobs": [
            {"name": name, "task": entry["task"], "schedule": str(entry["schedule"]),
             "queue": (celery.conf.task_routes or {}).get(entry["task"], {}).get("queue")}
            for name, entry in schedule.items()
        ]
    }


@router.post("/scheduled-jobs/{name}/run")
def run_scheduled_job(name: str):
    """Run-now for a beat_schedule entry: enqueues the same task Celery would fire on schedule, via
    the real broker (not an in-process call), so it lands on a real worker exactly like the
    scheduled firing would. Pausing isn't available yet — beat_schedule is static config, and true
    pause/resume needs a DB-backed enabled flag consulted by a custom scheduler (follow-up)."""
    from mainforte.celery_app import celery

    schedule = celery.conf.beat_schedule or {}
    entry = schedule.get(name)
    if entry is None:
        raise HTTPException(404, "no such scheduled job")
    result = celery.send_task(entry["task"])
    return {"queued": True, "task": entry["task"], "task_id": result.id}


def _task_summary(t: Task, ws_name: str | None, persona_name: str | None) -> dict:
    return {"id": t.id, "ws_id": t.ws_id, "ws_name": ws_name, "persona_id": t.persona_id,
            "persona_name": persona_name, "status": t.status, "current_stage": t.current_stage,
            "plan_len": len(t.plan or []), "attempt": t.attempt, "schedule": t.schedule,
            "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat()}


@router.get("/tasks")
def tasks(status: str | None = None, workspace_id: str | None = None,
          limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    q = db.query(Task, Workspace.name, Persona.name).join(Workspace, Workspace.id == Task.ws_id) \
        .outerjoin(Persona, Persona.id == Task.persona_id)
    if status:
        q = q.filter(Task.status == status)
    if workspace_id:
        q = q.filter(Task.ws_id == workspace_id)
    rows = q.order_by(Task.created_at.desc()).limit(limit).all()
    return {"tasks": [_task_summary(t, ws_name, persona_name) for t, ws_name, persona_name in rows]}


@router.get("/tasks/{task_id}")
def task_detail(task_id: str, db: Session = Depends(get_db)):
    row = db.query(Task, Workspace.name, Persona.name).join(Workspace, Workspace.id == Task.ws_id) \
        .outerjoin(Persona, Persona.id == Task.persona_id).filter(Task.id == task_id).first()
    if row is None:
        raise HTTPException(404, "task not found")
    t, ws_name, persona_name = row
    base_corr = t.correlation_id or t.id
    events = (
        db.query(Event)
        .filter((Event.correlation_id == base_corr) | (Event.correlation_id.like(f"{base_corr}:%")))
        .order_by(Event.id.asc())
        .all()
    )
    task_out = _task_summary(t, ws_name, persona_name)
    task_out.update({"plan": t.plan, "result": t.result, "correlation_id": t.correlation_id, "thread_id": t.thread_id})
    return {"task": task_out, "events": [to_dict(e) for e in events]}


WORK_START_TYPES = (
    "chat.message.created",
    "billing.reconcile.ran",
    "worker.job.picked",
    "agent.work.queued",
    "task.planned",
    "browser.session.opened",
    "build.started",
)
WORK_END_TYPES = (
    "persona.reply.ended", "persona.reply.error", "persona.reply.canceled",
    "agent.work.ended", "agent.work.error",
    "task.completed", "task.failed", "task.canceled",
    "build.succeeded", "build.failed",
    "browser.session.closed",
)
WORK_ERROR_TYPES = ("persona.reply.error", "agent.work.error", "task.failed", "build.failed", "tool.error")
WORK_IN_FLIGHT_STALE_AFTER = timedelta(minutes=15)


@router.get("/work-log")
def work_log(limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    """Every deferred unit of work in the system, regardless of source (chat turn, Stripe
    reconcile, agent-worker dispatch, browser session, build), grouped by its base correlation_id.
    A "unit of work" starts at one of WORK_START_TYPES; sub-steps use `{base}:...` correlation_ids
    (same convention as task_detail/chat_turn_detail) and roll up into the same row. See plan part
    B.2. This is a summary list; click through to GET /api/admin/work/{correlation_id} for detail."""
    starts = (
        db.query(Event)
        .filter(Event.type.in_(WORK_START_TYPES))
        .order_by(Event.id.desc())
        .limit(limit)
        .all()
    )
    if not starts:
        return {"items": []}

    # Sub-steps of a unit of work share a "{base}:suffix" correlation_id (same convention as
    # task_detail/chat_turn_detail). Pull every event whose correlation_id is one of our bases, or
    # is prefixed by one, in a single pass — cheaper than one LIKE query per row.
    bases = {e.correlation_id for e in starts if e.correlation_id}
    all_events = (
        db.query(Event)
        .filter(Event.correlation_id.isnot(None))
        .filter(
            Event.correlation_id.in_(bases)
            | func.split_part(Event.correlation_id, ":", 1).in_(bases)
        )
        .all()
    )
    by_base: dict[str, list[Event]] = {b: [] for b in bases}
    for e in all_events:
        base = e.correlation_id.split(":", 1)[0] if e.correlation_id else None
        if base in by_base:
            by_base[base].append(e)

    now = utcnow()
    items = []
    for start in starts:
        base = start.correlation_id
        if not base:
            continue
        group = sorted(by_base.get(base, [start]), key=lambda e: e.id)
        if not group:
            group = [start]
        last = group[-1]
        error_event = next((e for e in group if e.type in WORK_ERROR_TYPES), None)
        ended = next((e for e in reversed(group) if e.type in WORK_END_TYPES), None)
        if error_event:
            status = "error"
        elif ended:
            status = "ended"
        elif last.ts and (now - last.ts) > WORK_IN_FLIGHT_STALE_AFTER:
            status = "stalled"
        else:
            status = "in_flight"
        items.append({
            "correlation_id": base,
            "kind": start.type,
            "ws_id": start.ws_id,
            "started_at": start.ts.isoformat() if start.ts else None,
            "ended_at": last.ts.isoformat() if ended and last.ts else None,
            "event_count": len(group),
            "status": status,
        })
    items.sort(key=lambda i: i["started_at"] or "", reverse=True)
    return {"items": items}


@router.get("/work/{correlation_id}")
def work_item_detail(correlation_id: str, db: Session = Depends(get_db)):
    """Everything captured for one unit of deferred work (a chat turn, a Stripe reconcile run, an
    agent-worker dispatch, ...) — see `persona.reply.debug` in events/types.py for the chat-specific
    payload shape. Same correlation_id-scoped query as `task_detail()`. Generic over correlation_id,
    so it's also the detail view opened from the Work Log tab (see plan part B.2)."""
    events = (
        db.query(Event)
        .filter((Event.correlation_id == correlation_id) | (Event.correlation_id.like(f"{correlation_id}:%")))
        .order_by(Event.id.asc())
        .all()
    )
    if not events:
        raise HTTPException(404, "no events found for this correlation_id")
    debug_events = [e for e in events if e.type == "persona.reply.debug"]
    ended = next((e for e in reversed(events) if e.type in WORK_END_TYPES), None)
    error_event = next((e for e in events if e.type in WORK_ERROR_TYPES), None)
    return {
        "correlation_id": correlation_id,
        "ws_id": events[0].ws_id,
        "started_at": events[0].ts.isoformat() if events[0].ts else None,
        "ended_at": ended.ts.isoformat() if ended and ended.ts else None,
        "status": "error" if error_event else ("canceled" if any(e.type == "persona.reply.canceled" for e in events)
                                                else ("ended" if ended else "in_flight")),
        "rounds": len(debug_events),
        "debug": [to_dict(e) for e in debug_events],
        "events": [to_dict(e) for e in events],
    }


class DesiredIn(BaseModel):
    count: int = Field(ge=0, le=100)


@router.get("/workers")
def workers(db: Session = Depends(get_db)):
    from mainforte.db_settings import get_bastion_jenkins_config
    from mainforte.jenkins_ssh import _is_configured
    from mainforte.tasks.system import get_pool_desired_counts

    stale = utcnow() - timedelta(seconds=90)
    rows = db.query(AgentWorker).order_by(AgentWorker.last_heartbeat.desc().nullslast()).all()
    pools = get_pool_desired_counts(db)

    return {"desired": pools["full"],  # back-compat: existing UI reads this as the default pool's count
            "pools": pools,
            "reconciler_configured": _is_configured(get_bastion_jenkins_config(db)),
            "app_version": __version__,
            "workers": [{"id": w.id, "status": ("offline" if (w.last_heartbeat or stale) <= stale and w.status == "online" else w.status),
                         "node": w.node, "container_name": w.container_name, "version": w.version,
                         "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
                         "current_job": w.current_job, "stats": w.stats} for w in rows]}


@router.post("/workers/desired")
def set_desired(body: DesiredIn, ident: Identity = Depends(require_superuser), db: Session = Depends(get_db)):
    return _set_pool_desired(db, "full", body.count, ident)


@router.post("/workers/desired/sandbox")
def set_desired_sandbox(body: DesiredIn, ident: Identity = Depends(require_superuser), db: Session = Depends(get_db)):
    return _set_pool_desired(db, "sandbox", body.count, ident)


def _set_pool_desired(db: Session, pool_field: str, count: int, ident: Identity) -> dict:
    from mainforte.tasks.system import WORKERS_DESIRED_KEY, get_pool_desired_counts

    current = get_pool_desired_counts(db)
    current[pool_field] = count
    row = db.get(Setting, WORKERS_DESIRED_KEY)
    value = {**current, "by": ident.real_user.email}
    if row:
        row.value = value
    else:
        db.add(Setting(key=WORKERS_DESIRED_KEY, value=value))
    # reconcile_agent_workers (tasks/system.py, beat every 60s) converges live count → desired via Jenkins up/down jobs.
    return {"desired": count}


@router.get("/events")
def events(type: str | None = None, workspace_id: str | None = None, user_id: str | None = None,
           after: str | None = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    q = db.query(Event)
    if type:
        q = q.filter(Event.type.like(type.replace("*", "%")))
    if workspace_id:
        q = q.filter(Event.ws_id == workspace_id)
    if user_id:
        q = q.filter(Event.user_id == user_id)
    if after:
        q = q.filter(Event.id > after)
    rows = q.order_by(Event.id.desc()).limit(limit).all()
    return {"events": [to_dict(e) for e in rows]}


@router.get("/event-types")
def event_types():
    return {"types": EVENT_TYPES}


# attr (config.py-style field name, used by the frontend) -> Setting key
_BASTION_JENKINS_ATTR_TO_KEY = {attr: setting_key for setting_key, (attr, _) in BASTION_JENKINS_FIELDS.items()}


class BastionJenkinsSettingsIn(BaseModel):
    bastion_host: str | None = None
    bastion_port: int | None = None
    bastion_username: str | None = None
    bastion_ssh_key: str | None = None  # PEM text; omitted/blank keeps the existing stored key
    jenkins_host: str | None = None
    jenkins_port: int | None = None
    jenkins_username: str | None = None
    jenkins_ssh_key: str | None = None  # PEM text; omitted/blank keeps the existing stored key
    jenkins_provision_job: str | None = None
    jenkins_destroy_job: str | None = None
    worker_api_url: str | None = None


@router.get("/settings/bastion-jenkins")
def get_bastion_jenkins_settings(db: Session = Depends(get_db)):
    return bastion_jenkins_status(db)


@router.put("/settings/bastion-jenkins")
def put_bastion_jenkins_settings(body: BastionJenkinsSettingsIn, db: Session = Depends(get_db)):
    updates = {
        _BASTION_JENKINS_ATTR_TO_KEY[attr]: value
        for attr, value in body.model_dump().items()
        if value is not None
    }
    set_bastion_jenkins_config(db, updates)
    return bastion_jenkins_status(db)
