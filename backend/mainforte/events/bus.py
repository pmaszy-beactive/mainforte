"""emit(): the single write path for events.

Transactional outbox:
1. Insert into Postgres `events` inside the caller's transaction (audit log, replay source of truth).
2. AFTER COMMIT: XADD to the workspace Redis stream, run sync handlers, enqueue async handlers as Celery
   tasks, then mark `dispatched_at`. If the process dies in between, `sweep_outbox` (beat, every 30s)
   re-dispatches anything older than 60s with `dispatched_at IS NULL`. Handlers are therefore at-least-once
   and MUST be idempotent (key on event id).
"""
from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from mainforte.db.base import utcnow
from mainforte.db.models import Event
from mainforte.events import stream
from mainforte.events.registry import handlers_for, run_sync_handlers
from mainforte.events.types import is_known
from mainforte.ids import new_id

log = logging.getLogger(__name__)
_PENDING_KEY = "_mf_pending_events"


def build_event(
    type: str,
    *,
    ws_id: str | None = None,
    user_id: str | None = None,
    actor: tuple[str, str | None] = ("system", None),
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> Event:
    if not is_known(type):
        log.warning("emitting unknown event type %s (add it to events/types.py)", type)
    return Event(
        id=new_id(), ts=utcnow(), type=type, ws_id=ws_id, user_id=user_id,
        actor_type=actor[0], actor_id=actor[1], correlation_id=correlation_id,
        causation_id=causation_id, payload=payload or {},
    )


def to_dict(ev: Event) -> dict[str, Any]:
    return {
        "id": ev.id,
        "ts": ev.ts.astimezone(UTC).isoformat(),
        "type": ev.type,
        "ws_id": ev.ws_id,
        "user_id": ev.user_id,
        "actor": {"type": ev.actor_type, "id": ev.actor_id},
        "correlation_id": ev.correlation_id,
        "causation_id": ev.causation_id,
        "payload": ev.payload,
    }


def emit(db: Session, type: str, **kw: Any) -> dict[str, Any]:
    """Write inside the caller's transaction; publish + dispatch after commit. Returns the event dict."""
    ev = build_event(type, **kw)
    db.add(ev)
    db.flush()
    d = to_dict(ev)
    db.info.setdefault(_PENDING_KEY, []).append(d)
    return d


def emit_ephemeral(d_type: str, *, ws_id: str | None, actor: tuple[str, str | None], payload: dict[str, Any],
                   correlation_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Stream-only event (no Postgres row): used for high-frequency deltas like persona.reply.delta.
    Not replayable; the terminal event (e.g. persona.reply.ended) must carry the full content."""
    d = {
        "id": new_id(), "ts": utcnow().isoformat(), "type": d_type, "ws_id": ws_id, "user_id": user_id,
        "actor": {"type": actor[0], "id": actor[1]}, "correlation_id": correlation_id, "causation_id": None,
        "payload": payload, "ephemeral": True,
    }
    stream.publish(d)
    return d


def dispatch(d: dict[str, Any]) -> bool:
    """Publish + enqueue handlers for one event dict. Returns True if fully dispatched."""
    ok = True
    try:
        stream.publish(d)
    except Exception:
        ok = False
        log.exception("stream publish failed for %s", d["id"])
    run_sync_handlers(d)
    regs = [r for r in handlers_for(d["type"]) if not r.sync]
    if regs:
        try:
            from mainforte.tasks.events import dispatch_handler
            for r in regs:
                dispatch_handler.apply_async(args=[r.name, d], queue=r.queue)
        except Exception:
            ok = False
            log.exception("handler dispatch failed for %s", d["id"])
    return ok


def _mark_dispatched(ids: list[str]) -> None:
    from mainforte.db.session import get_sessionmaker
    db = get_sessionmaker()()
    try:
        db.query(Event).filter(Event.id.in_(ids)).update({Event.dispatched_at: utcnow()}, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("could not mark events dispatched")
    finally:
        db.close()


@sa_event.listens_for(Session, "after_commit")
def _flush_pending(session: Session) -> None:
    pending: list[dict[str, Any]] = session.info.pop(_PENDING_KEY, [])
    if not pending:
        return
    done = [d["id"] for d in pending if dispatch(d)]
    if done:
        _mark_dispatched(done)


@sa_event.listens_for(Session, "after_rollback")
def _drop_pending(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
