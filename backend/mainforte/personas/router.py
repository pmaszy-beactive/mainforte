"""Decides which persona(s) reply to a chat message, and drives the streamed reply.

Runs as a Celery task on the `chat` queue (no filesystem, no sandbox — just an LLM round trip).
Cancellation: `chat/routes.py:cancel` sets `cancel:{ws}:{target}` in Redis; we poll it between
chunks and between personas so a cancel takes effect within one network read, not after the
whole reply finishes.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from mainforte.aiproxy import client as aiproxy
from mainforte.aiproxy.keys import get_or_mint
from mainforte.aiproxy.pricing import estimate_cost_usd
from mainforte.db.models import Persona, Workspace
from mainforte.db.session import db_session
from mainforte.events import emit, emit_ephemeral
from mainforte.events.stream import sync_redis
from mainforte.ids import new_id
from mainforte.personas import catalog
from mainforte.personas.memory import build_system_prompt, recent_thread_messages
from mainforte.personas.service import list_active

log = logging.getLogger(__name__)

MAX_REPLY_TOKENS = 1024
MENTION_RE = re.compile(r"@(\w+)")


def _cancel_key(ws_id: str, target: str) -> str:
    return f"cancel:{ws_id}:{target}"


def _is_canceled(ws_id: str, thread_id: str | None, correlation_id: str | None) -> bool:
    r = sync_redis()
    for target in filter(None, (correlation_id, thread_id, "*")):
        if r.exists(_cancel_key(ws_id, target)):
            return True
    return False


def _pick_personas(text: str, roster: list[Persona]) -> list[Persona]:
    """@mentions win outright; otherwise the Concierge (always present) takes it and routes
    in its own reply. Multi-persona group planning is a P2 concern; this keeps P1 simple and correct."""
    mentioned = {m.lower() for m in MENTION_RE.findall(text)}
    if mentioned:
        hits = [p for p in roster if p.slug in mentioned or p.name.lower().split()[0] in mentioned]
        if hits:
            return hits[:2]
    concierge = next((p for p in roster if p.slug == "concierge"), None)
    return [concierge] if concierge else roster[:1]


def _fallback_text(persona: Persona, user_text: str) -> str:
    return (
        f"({persona.name} — no AI backend configured yet, echoing) "
        f"I heard: {user_text.strip()[:400]}"
    )


async def run_reply(*, ws_id: str, thread_id: str | None, correlation_id: str, persona: Persona,
                     api_key: str | None, history: list[dict[str, Any]], user_text: str) -> None:
    arche = catalog.get(persona.slug)
    base = arche.system_prompt if arche else "You are a helpful assistant."
    with db_session() as db:
        system = build_system_prompt(db, ws_id=ws_id, persona=persona, base=base)
    started = emit_ephemeral(
        "persona.reply.started", ws_id=ws_id, actor=("persona", persona.slug), user_id=None,
        correlation_id=correlation_id, payload={"thread_id": thread_id, "persona_id": persona.id},
    )
    log.info("persona.reply.started %s persona=%s thread=%s", started["id"], persona.slug, thread_id)

    full = ""
    error: str | None = None
    canceled = False
    usage_sink: dict[str, int] = {}
    try:
        if api_key is None:
            full = _fallback_text(persona, user_text)
            if _is_canceled(ws_id, thread_id, correlation_id):
                canceled = True
            else:
                emit_ephemeral("persona.reply.delta", ws_id=ws_id, actor=("persona", persona.slug), user_id=None,
                              correlation_id=correlation_id, payload={"thread_id": thread_id, "text": full})
        else:
            async for chunk in aiproxy.stream_reply(
                api_key=api_key, model=persona.model, system=system, messages=history, max_tokens=MAX_REPLY_TOKENS,
                usage_sink=usage_sink,
            ):
                if _is_canceled(ws_id, thread_id, correlation_id):
                    canceled = True
                    break
                full += chunk
                emit_ephemeral("persona.reply.delta", ws_id=ws_id, actor=("persona", persona.slug), user_id=None,
                              correlation_id=correlation_id, payload={"thread_id": thread_id, "text": chunk})
    except aiproxy.AiProxyError as e:
        error = str(e)
        log.warning("persona reply error persona=%s: %s", persona.slug, error)
    except Exception as e:  # never let one persona's failure break the router task
        error = str(e)
        log.exception("persona reply unexpected error persona=%s", persona.slug)

    with db_session() as db:
        if error:
            emit(db, "persona.reply.error", ws_id=ws_id, actor=("persona", persona.slug),
                 correlation_id=correlation_id, payload={"thread_id": thread_id, "persona_id": persona.id, "message": error})
        elif canceled:
            emit(db, "persona.reply.canceled", ws_id=ws_id, actor=("persona", persona.slug),
                 correlation_id=correlation_id, payload={"thread_id": thread_id, "persona_id": persona.id, "text": full})
        else:
            emit(db, "persona.reply.ended", ws_id=ws_id, actor=("persona", persona.slug),
                 correlation_id=correlation_id, payload={"thread_id": thread_id, "persona_id": persona.id, "text": full})

        if usage_sink.get("input_tokens") or usage_sink.get("output_tokens"):
            in_tok = usage_sink.get("input_tokens", 0)
            out_tok = usage_sink.get("output_tokens", 0)
            emit(db, "billing.usage.recorded", ws_id=ws_id, actor=("persona", persona.slug),
                 correlation_id=correlation_id,
                 payload={"thread_id": thread_id, "persona_id": persona.id, "model": persona.model,
                          "input_tokens": in_tok, "output_tokens": out_tok,
                          "cost_usd": estimate_cost_usd(persona.model, in_tok, out_tok)})


def route_message(event: dict[str, Any]) -> None:
    """Handler for chat.message.created. Sync entry point (Celery), drives async work internally."""
    if event["actor"]["type"] != "user":
        return  # personas don't reply to each other here; persona.help.requested handles that (P2)
    ws_id = event.get("ws_id")
    if not ws_id:
        return
    payload = event["payload"]
    thread_id = payload.get("thread_id")
    user_text = payload.get("text") or ""
    correlation_id = event.get("correlation_id") or thread_id or new_id()

    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            return
        roster = list_active(db, ws_id=ws_id)
        if not roster:
            return
        targets = _pick_personas(user_text, roster)
        api_key = get_or_mint(db, ws)
        current = {"role": "user", "content": user_text.strip() or "(attachment only)"}
        history = [*recent_thread_messages(db, thread_id=thread_id), current]

    async def _run_all() -> None:
        for persona in targets:
            if _is_canceled(ws_id, thread_id, correlation_id):
                break
            await run_reply(ws_id=ws_id, thread_id=thread_id, correlation_id=correlation_id, persona=persona,
                             api_key=api_key, history=history, user_text=user_text)

    asyncio.run(_run_all())
