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
from mainforte.db.models import AgentWorker, AuthToken, Event, Memory, Workspace
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
