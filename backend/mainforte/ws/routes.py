"""One WebSocket per client. Replays from Postgres after `after`, then tails the Redis stream.

Client → server frames: {"type":"ack","id":...} | {"type":"ping"}
Server → client frames: event dicts, plus {"type":"_hello", ...} and {"type":"_pong"}.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from mainforte.auth.deps import resolve_identity
from mainforte.db.models import Event, Membership
from mainforte.db.session import db_session
from mainforte.events.bus import to_dict
from mainforte.events.stream import last_id, read_after

log = logging.getLogger(__name__)
router = APIRouter()


def _authorize(token: str, workspace_id: str) -> tuple[str, str] | None:
    with db_session() as db:
        ident = resolve_identity(token, db)
        if not ident:
            return None
        m = db.query(Membership).filter_by(workspace_id=workspace_id, user_id=ident.user.id).first()
        if not m and not (ident.real_user.is_superuser and not ident.impersonating):
            return None
        return ident.user.id, ident.real_user.id


def _replay(workspace_id: str, after: str | None, limit: int = 500) -> list[dict]:
    if not after:
        return []
    with db_session() as db:
        rows = (db.query(Event).filter(Event.ws_id == workspace_id, Event.id > after)
                .order_by(Event.id.asc()).limit(limit).all())
        return [to_dict(e) for e in rows]


def _emit_conn(type: str, workspace_id: str, user_id: str, payload: dict) -> None:
    from mainforte.events import emit
    with db_session() as db:
        emit(db, type, ws_id=workspace_id, user_id=user_id, actor=("user", user_id), payload=payload)


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str, workspace_id: str, after: str | None = None):
    auth = await run_in_threadpool(_authorize, token, workspace_id)
    if not auth:
        await websocket.close(code=4401)
        return
    user_id, _real_id = auth
    await websocket.accept()

    # 1. pin the stream position FIRST, then replay the gap from Postgres. Anything appended to the stream
    #    while we replay is picked up by the tail (starting at `stream_pos`) and de-duplicated by event id.
    stream_pos = await last_id(workspace_id)
    replay = await run_in_threadpool(_replay, workspace_id, after)
    last_seen = after
    for ev in replay:
        await websocket.send_text(json.dumps(ev))
        last_seen = ev["id"]
    await websocket.send_text(json.dumps({"type": "_hello", "replayed": len(replay), "last_id": last_seen}))
    await run_in_threadpool(_emit_conn, "connection.resumed" if after else "connection.opened", workspace_id, user_id,
                            {"replayed": len(replay)})

    # 2. tail the redis stream from the pinned position. (One XREAD per socket for now; at scale this becomes
    #    one subscriber per process per workspace fanning out to local sockets.)
    stop = asyncio.Event()

    async def tail() -> None:
        nonlocal last_seen
        rid = stream_pos
        idle = 0
        while not stop.is_set():
            try:
                entries = await read_after(workspace_id, rid, block_ms=5_000)
            except asyncio.CancelledError:
                return
            except Exception:
                log.exception("stream read failed")
                await asyncio.sleep(1)
                continue
            if not entries:
                idle += 1
                if idle >= 4:  # ~20s of silence → server-side heartbeat so the client can detect a dead link
                    idle = 0
                    await websocket.send_text(json.dumps({"type": "_heartbeat", "last_id": last_seen}))
                continue
            idle = 0
            for entry_id, ev in entries:
                rid = entry_id  # advance the stream cursor even for de-duplicated entries
                if last_seen and ev["id"] <= last_seen:
                    continue  # already delivered via replay
                last_seen = ev["id"]
                await websocket.send_text(json.dumps(ev))

    async def inbound() -> None:
        while True:
            msg = await websocket.receive_text()
            try:
                frame = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if frame.get("type") == "ping":
                await websocket.send_text('{"type":"_pong"}')
            # acks are informational for now; clients keep their own last id

    t = asyncio.create_task(tail())
    try:
        await inbound()
    except WebSocketDisconnect:
        pass
    finally:
        stop.set()
        t.cancel()
        await run_in_threadpool(_emit_conn, "connection.closed", workspace_id, user_id, {})
