"""Concierge onboarding: greets a fresh workspace, runs a short in-chat interview to learn the
member's name for the Concierge and their preferred interaction style, and seeds initial
workspace memory.

Subscribes to workspace.created rather than hooking auth/service.create_user directly, so both
call sites (signup, explicit workspace creation) are covered for free. `run_onboarding` is a
plain callable (not just the event handler) so workspaces/service.py's reset flow can re-run the
exact same interview without faking a workspace.created event.

The interview itself has no hand-rolled state machine — it's one prompt-engineered opening
message from the Concierge. Once the member replies in chat, personas/onboarding_extract.py picks
the answer up (via the normal route_message path) and writes it to User.prefs.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from mainforte.aiproxy.keys import get_or_mint
from mainforte.db.models import Memory, Persona, User, Workspace
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.events.registry import on
from mainforte.ids import new_id
from mainforte.personas.router import run_reply

log = logging.getLogger(__name__)

ONBOARDING_TASK = (
    "(onboarding) A new household just joined. Greet {member_name} warmly as the Concierge, "
    "in 2-4 sentences. Ask what they'd like to call you, and ask how they like to interact — "
    "terse and to the point, or more conversational — so you can match their style going "
    "forward. Mention they can also bring in PM, CFO, Architect, Marketer, Coder, or Executor "
    "whenever they need one. Keep it warm and brief; this is a first impression, not a form."
)


def run_onboarding(ws_id: str, *, user_id: str | None = None) -> None:
    """Runs (or re-runs, after a reset) the onboarding interview for a workspace. Synchronous;
    callers already run on a worker (Celery event handler or the reset endpoint's own task)."""
    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        concierge = db.query(Persona).filter_by(ws_id=ws_id, slug="concierge", status="active").one_or_none()
        if ws is None or concierge is None:
            return
        user = db.get(User, user_id) if user_id else None
        member_name = user.name if user and user.name else "the new member"
        thread_id = new_id()
        emit(db, "chat.thread.created", ws_id=ws_id, actor=("system", None),
             payload={"thread_id": thread_id, "kind": "global"})
        db.add(Memory(ws_id=ws_id, kind="workspace", source="concierge",
                      text=f"New workspace '{ws.name}'. No preferences recorded yet."))
        emit(db, "memory.noted", ws_id=ws_id, actor=("system", None), payload={"kind": "workspace"})
        api_key = get_or_mint(db, ws)
        concierge_id = concierge.id
        task_text = ONBOARDING_TASK.format(member_name=member_name)

    asyncio.run(run_reply(
        ws_id=ws_id, thread_id=thread_id, correlation_id=thread_id, persona=concierge,
        api_key=api_key, history=[{"role": "user", "content": task_text}],
        user_text=task_text, user=user,
    ))
    log.info("run_onboarding ws=%s thread=%s concierge=%s", ws_id, thread_id, concierge_id)


@on("workspace.created", queue="chat")
def onboard_workspace(event: dict[str, Any]) -> None:
    ws_id = event.get("ws_id")
    if not ws_id:
        return
    run_onboarding(ws_id, user_id=event.get("user_id"))
