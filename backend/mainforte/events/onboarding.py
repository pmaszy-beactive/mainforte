"""Concierge onboarding: greets a fresh workspace and seeds initial workspace memory.

Subscribes to workspace.created rather than hooking auth/service.create_user directly, so both
call sites (signup, explicit workspace creation) are covered for free.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from mainforte.aiproxy.keys import get_or_mint
from mainforte.db.models import Memory, Persona, Workspace
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.events.registry import on
from mainforte.ids import new_id
from mainforte.personas.router import run_reply

log = logging.getLogger(__name__)

ONBOARDING_TASK = (
    "(onboarding) A new household just joined. Greet them warmly as the Concierge, "
    "in 2-3 sentences, and mention they can bring in PM, CFO, Architect, Marketer, "
    "Coder, or Executor whenever they need one."
)


@on("workspace.created", queue="chat")
def onboard_workspace(event: dict[str, Any]) -> None:
    ws_id = event.get("ws_id")
    if not ws_id:
        return
    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        concierge = db.query(Persona).filter_by(ws_id=ws_id, slug="concierge", status="active").one_or_none()
        if ws is None or concierge is None:
            return
        thread_id = new_id()
        emit(db, "chat.thread.created", ws_id=ws_id, actor=("system", None),
             payload={"thread_id": thread_id, "kind": "global"})
        db.add(Memory(ws_id=ws_id, kind="workspace", source="concierge",
                      text=f"New workspace '{ws.name}'. No preferences recorded yet."))
        emit(db, "memory.noted", ws_id=ws_id, actor=("system", None), payload={"kind": "workspace"})
        api_key = get_or_mint(db, ws)
        concierge_id = concierge.id

    asyncio.run(run_reply(
        ws_id=ws_id, thread_id=thread_id, correlation_id=thread_id, persona=concierge,
        api_key=api_key, history=[{"role": "user", "content": ONBOARDING_TASK}],
        user_text=ONBOARDING_TASK,
    ))
    log.info("onboard_workspace ws=%s thread=%s concierge=%s", ws_id, thread_id, concierge_id)
