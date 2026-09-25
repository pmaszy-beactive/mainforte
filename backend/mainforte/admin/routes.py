from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from mainforte.auth.deps import Identity, require_superuser
from mainforte.db.base import utcnow
from mainforte.db.models import AgentWorker, ApiError, Event, Membership, Setting, User, Workspace
from mainforte.db.session import get_db
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
    # P3 fills these from the Stripe reconcile + ai-proxy usage tables.
    plan_counts = dict(db.query(Workspace.plan, func.count()).group_by(Workspace.plan).all())
    return {"mrr_cents": 0, "active_subscriptions": 0, "failed_payments": 0, "ai_cost_usd": 0.0, "ai_charged_usd": 0.0,
            "workspaces_by_plan": plan_counts}


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


class DesiredIn(BaseModel):
    count: int = Field(ge=0, le=100)


@router.get("/workers")
def workers(db: Session = Depends(get_db)):
    desired = db.get(Setting, "workers.desired")
    stale = utcnow() - timedelta(seconds=90)
    rows = db.query(AgentWorker).order_by(AgentWorker.created_at.asc()).all()
    return {"desired": (desired.value.get("count") if desired else 1),
            "workers": [{"id": w.id, "status": ("offline" if (w.last_heartbeat or stale) <= stale and w.status == "online" else w.status),
                         "node": w.node, "container_name": w.container_name,
                         "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
                         "current_job": w.current_job, "stats": w.stats} for w in rows]}


@router.post("/workers/desired")
def set_desired(body: DesiredIn, ident: Identity = Depends(require_superuser), db: Session = Depends(get_db)):
    row = db.get(Setting, "workers.desired")
    if row:
        row.value = {"count": body.count, "by": ident.real_user.email}
    else:
        db.add(Setting(key="workers.desired", value={"count": body.count, "by": ident.real_user.email}))
    # P4: a system-queue job converges live count → desired via Jenkins up/down jobs.
    return {"desired": body.count}


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
