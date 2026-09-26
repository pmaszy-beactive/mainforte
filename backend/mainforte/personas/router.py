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
from mainforte.events.governor import _extract_claims, ground_action_claims
from mainforte.events.stream import sync_redis
from mainforte.ids import new_id
from mainforte.personas import catalog
from mainforte.personas.memory import build_system_prompt, recent_thread_messages
from mainforte.personas.service import list_active
from mainforte.tasks.work import run_tool
from mainforte.tools.catalog import TOOLS, to_anthropic_schema

log = logging.getLogger(__name__)

MAX_REPLY_TOKENS = 1024
MAX_TOOL_ROUNDTRIPS = 5
MENTION_RE = re.compile(r"@(\w+)")

# All catalog tools are now offered to the model: non-sandboxed ones run in-process below,
# sandboxed ones (bash, browser_*) dispatch to the `work` queue via _run_sandboxed_tool — never
# run in-process in this chat-queue task.
_ALL_TOOLS = to_anthropic_schema(TOOLS)


def _cancel_key(ws_id: str, target: str) -> str:
    return f"cancel:{ws_id}:{target}"


def _is_canceled(ws_id: str, thread_id: str | None, correlation_id: str | None) -> bool:
    r = sync_redis()
    for target in filter(None, (correlation_id, thread_id, "*")):
        if r.exists(_cancel_key(ws_id, target)):
            return True
    return False


SANDBOX_POLL_SECONDS = 0.5
SANDBOX_MAX_WAIT_SECONDS = 90


async def _run_sandboxed_tool(*, tool_name: str, tool_input: dict[str, Any], ws_id: str,
                               correlation_id: str, thread_id: str | None, persona_id: str,
                               tool_use_id: str) -> dict[str, Any]:
    """Dispatches to the `work` queue and polls the Celery result backend (Redis) rather than
    blocking this chat-queue worker thread — same non-blocking-poll rhythm as `_is_canceled`."""
    async_result = run_tool.delay(
        tool_name=tool_name, tool_input=tool_input, ws_id=ws_id, correlation_id=correlation_id,
        thread_id=thread_id, persona_id=persona_id, tool_use_id=tool_use_id,
    )
    waited = 0.0
    while not async_result.ready():
        if waited >= SANDBOX_MAX_WAIT_SECONDS:
            return {"ok": False, "error": f"tool {tool_name!r} did not complete within "
                                           f"{SANDBOX_MAX_WAIT_SECONDS}s", "tool_use_id": tool_use_id}
        await asyncio.sleep(SANDBOX_POLL_SECONDS)
        waited += SANDBOX_POLL_SECONDS
    # already ready() above — this can't block. disable_sync_subtasks=False opts out of
    # Celery's blanket "never call .get() inside a task" guard, which fires on any in-task
    # call regardless of readiness.
    return async_result.get(disable_sync_subtasks=False)


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


async def _run_one_reply_round(*, api_key: str, system: str, convo: list[dict[str, Any]],
                                persona: Persona, ws_id: str, thread_id: str | None,
                                correlation_id: str, usage_sink: dict[str, int]) -> str:
    """One LLM round-trip with no tool use expected (used for the single post-hoc correction
    round) — streams the reply, appends it to `convo`, and returns the text. Tool calls in this
    round are dropped: a correction round asks the persona to restate or call a tool, and if it
    calls one, that's real work the *next* turn's grounding will see via a fresh correlation_id,
    not this one — keeping this round's own semantics simple and bounded to exactly one pass."""
    round_usage: dict[str, int] = {}
    tool_use_sink: list[aiproxy.ToolUseBlock] = []
    stop_reason_sink: dict[str, str] = {}
    text = ""
    async for chunk in aiproxy.stream_reply(
        api_key=api_key, model=persona.model, system=system, messages=convo,
        max_tokens=MAX_REPLY_TOKENS, usage_sink=round_usage, tools=_ALL_TOOLS or None,
        tool_use_sink=tool_use_sink, stop_reason_sink=stop_reason_sink,
    ):
        text += chunk
        emit_ephemeral("persona.reply.delta", ws_id=ws_id, actor=("persona", persona.slug), user_id=None,
                      correlation_id=correlation_id, payload={"thread_id": thread_id, "text": chunk})
    usage_sink["input_tokens"] = usage_sink.get("input_tokens", 0) + round_usage.get("input_tokens", 0)
    usage_sink["output_tokens"] = usage_sink.get("output_tokens", 0) + round_usage.get("output_tokens", 0)
    convo.append({"role": "assistant", "content": text})
    return text


async def _ground_and_correct(*, api_key: str, ws_id: str, thread_id: str | None, correlation_id: str,
                               persona: Persona, system: str, convo: list[dict[str, Any]], full: str,
                               usage_sink: dict[str, int]) -> str:
    """Extracts action claims from `full` and grounds them against this turn's own tool/agent-work
    events. Ungrounded claims hold the reply and trigger exactly one correction round; a claim
    still ungrounded after that escalates via task.blocked but the corrected text is still
    released (something shown beats nothing shown). Returns the text that should actually be
    released as this persona's reply — `full` unchanged if there was nothing to correct."""
    try:
        claims = await _extract_claims(api_key=api_key, reply_text=full, ws_id=ws_id,
                                        correlation_id=correlation_id)
    except aiproxy.AiProxyError:
        log.exception("governor claim extraction failed (pre-release) ws=%s corr=%s", ws_id, correlation_id)
        return full

    action_claims = [c for c in claims if c.get("type") == "action"]
    if not action_claims:
        return full

    with db_session() as db:
        grounded = await ground_action_claims(db, ws_id=ws_id, correlation_id=correlation_id,
                                               api_key=api_key, claims=action_claims)
        unverified = [g for g in grounded if not g["verified"]]
        for g in grounded:
            if g["verified"]:
                emit(db, "governor.claim.verified", ws_id=ws_id, actor=("system", None),
                     correlation_id=correlation_id,
                     payload={"thread_id": thread_id, "persona_id": persona.id, **g["claim"],
                              "method": g["method"]})
        if not unverified:
            return full

        emit(db, "governor.reply.held", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
             payload={"thread_id": thread_id, "persona_id": persona.id, "text": full,
                      "unverified_claims": [g["claim"] for g in unverified]})

    correction_lines = "\n".join(f"- \"{g['claim']['text']}\"" for g in unverified)
    convo.append({"role": "user", "content": (
        "You made a claim in your last reply that no tool call in this turn actually backs up:\n"
        f"{correction_lines}\n\n"
        "Either call the appropriate tool now to actually do it, or restate your reply without "
        "that claim. Do not repeat the unverified claim."
    )})
    corrected = await _run_one_reply_round(
        api_key=api_key, system=system, convo=convo, persona=persona, ws_id=ws_id,
        thread_id=thread_id, correlation_id=correlation_id, usage_sink=usage_sink,
    )

    try:
        recheck_claims = await _extract_claims(api_key=api_key, reply_text=corrected, ws_id=ws_id,
                                                correlation_id=correlation_id)
    except aiproxy.AiProxyError:
        log.exception("governor claim re-extraction failed ws=%s corr=%s", ws_id, correlation_id)
        recheck_claims = []
    recheck_actions = [c for c in recheck_claims if c.get("type") == "action"]

    with db_session() as db:
        still_unverified: list[dict[str, Any]] = []
        if recheck_actions:
            regrounded = await ground_action_claims(db, ws_id=ws_id, correlation_id=correlation_id,
                                                      api_key=api_key, claims=recheck_actions)
            still_unverified = [g for g in regrounded if not g["verified"]]
            for g in regrounded:
                if g["verified"]:
                    emit(db, "governor.claim.verified", ws_id=ws_id, actor=("system", None),
                         correlation_id=correlation_id,
                         payload={"thread_id": thread_id, "persona_id": persona.id, **g["claim"],
                                  "method": g["method"]})

        if not still_unverified:
            emit(db, "governor.reply.corrected", ws_id=ws_id, actor=("system", None),
                 correlation_id=correlation_id,
                 payload={"thread_id": thread_id, "persona_id": persona.id, "original_text": full,
                          "corrected_text": corrected})
        else:
            emit(db, "task.blocked", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
                 payload={"thread_id": thread_id, "persona_id": persona.id,
                          "reason": "unverified action claim after correction attempt",
                          "original_text": full, "corrected_text": corrected,
                          "unverified_claims": [g["claim"] for g in still_unverified]})
    return corrected


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
    convo = list(history)
    try:
        if api_key is None:
            full = _fallback_text(persona, user_text)
            if _is_canceled(ws_id, thread_id, correlation_id):
                canceled = True
            else:
                emit_ephemeral("persona.reply.delta", ws_id=ws_id, actor=("persona", persona.slug), user_id=None,
                              correlation_id=correlation_id, payload={"thread_id": thread_id, "text": full})
        else:
            for _round in range(MAX_TOOL_ROUNDTRIPS):
                round_usage: dict[str, int] = {}
                tool_use_sink: list[aiproxy.ToolUseBlock] = []
                stop_reason_sink: dict[str, str] = {}
                round_text = ""
                async for chunk in aiproxy.stream_reply(
                    api_key=api_key, model=persona.model, system=system, messages=convo,
                    max_tokens=MAX_REPLY_TOKENS, usage_sink=round_usage, tools=_ALL_TOOLS or None,
                    tool_use_sink=tool_use_sink, stop_reason_sink=stop_reason_sink,
                ):
                    if _is_canceled(ws_id, thread_id, correlation_id):
                        canceled = True
                        break
                    round_text += chunk
                    full += chunk
                    emit_ephemeral("persona.reply.delta", ws_id=ws_id, actor=("persona", persona.slug), user_id=None,
                                  correlation_id=correlation_id, payload={"thread_id": thread_id, "text": chunk})
                usage_sink["input_tokens"] = usage_sink.get("input_tokens", 0) + round_usage.get("input_tokens", 0)
                usage_sink["output_tokens"] = usage_sink.get("output_tokens", 0) + round_usage.get("output_tokens", 0)
                if canceled or not tool_use_sink:
                    break

                assistant_content: list[dict[str, Any]] = []
                if round_text:
                    assistant_content.append({"type": "text", "text": round_text})
                assistant_content += [
                    {"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input} for tu in tool_use_sink
                ]
                convo.append({"role": "assistant", "content": assistant_content})

                tool_results: list[dict[str, Any]] = []
                for tu in tool_use_sink:
                    tool = TOOLS.get(tu.name)
                    with db_session() as db:
                        emit(db, "tool.started", ws_id=ws_id, actor=("persona", persona.slug),
                             correlation_id=correlation_id,
                             payload={"thread_id": thread_id, "persona_id": persona.id, "tool_use_id": tu.id,
                                      "name": tu.name, "input": tu.input})
                    if tool is None:
                        err_msg = f"unknown tool {tu.name!r}"
                        with db_session() as db:
                            emit(db, "tool.error", ws_id=ws_id, actor=("persona", persona.slug),
                                 correlation_id=correlation_id,
                                 payload={"thread_id": thread_id, "persona_id": persona.id, "tool_use_id": tu.id,
                                          "name": tu.name, "message": err_msg})
                        tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "is_error": True,
                                              "content": err_msg})
                        continue
                    if tool.sandboxed:
                        outcome = await _run_sandboxed_tool(
                            tool_name=tu.name, tool_input=tu.input, ws_id=ws_id,
                            correlation_id=correlation_id, thread_id=thread_id, persona_id=persona.id,
                            tool_use_id=tu.id,
                        )
                        if outcome.get("ok"):
                            result = outcome["result"]
                            with db_session() as db:
                                emit(db, "tool.ended", ws_id=ws_id, actor=("persona", persona.slug),
                                     correlation_id=correlation_id,
                                     payload={"thread_id": thread_id, "persona_id": persona.id,
                                              "tool_use_id": tu.id, "name": tu.name, "result": result})
                            tool_results.append({"type": "tool_result", "tool_use_id": tu.id,
                                                  "content": str(result)})
                        else:
                            err_msg = outcome.get("error", "sandboxed tool failed")
                            with db_session() as db:
                                emit(db, "tool.error", ws_id=ws_id, actor=("persona", persona.slug),
                                     correlation_id=correlation_id,
                                     payload={"thread_id": thread_id, "persona_id": persona.id,
                                              "tool_use_id": tu.id, "name": tu.name, "message": err_msg})
                            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "is_error": True,
                                                  "content": err_msg})
                        continue
                    try:
                        result = tool.handler(**tu.input)
                        with db_session() as db:
                            emit(db, "tool.ended", ws_id=ws_id, actor=("persona", persona.slug),
                                 correlation_id=correlation_id,
                                 payload={"thread_id": thread_id, "persona_id": persona.id, "tool_use_id": tu.id,
                                          "name": tu.name, "result": result})
                        tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": str(result)})
                    except Exception as e:
                        log.exception("tool handler error name=%s", tu.name)
                        with db_session() as db:
                            emit(db, "tool.error", ws_id=ws_id, actor=("persona", persona.slug),
                                 correlation_id=correlation_id,
                                 payload={"thread_id": thread_id, "persona_id": persona.id, "tool_use_id": tu.id,
                                          "name": tu.name, "message": str(e)})
                        tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "is_error": True,
                                              "content": str(e)})
                convo.append({"role": "user", "content": tool_results})
            else:
                log.warning("persona=%s hit MAX_TOOL_ROUNDTRIPS=%d without a final reply", persona.slug,
                            MAX_TOOL_ROUNDTRIPS)
    except aiproxy.AiProxyError as e:
        error = str(e)
        log.warning("persona reply error persona=%s: %s", persona.slug, error)
    except Exception as e:  # never let one persona's failure break the router task
        error = str(e)
        log.exception("persona reply unexpected error persona=%s", persona.slug)

    if not error and not canceled and api_key is not None and full.strip():
        try:
            full = await _ground_and_correct(
                api_key=api_key, ws_id=ws_id, thread_id=thread_id, correlation_id=correlation_id,
                persona=persona, system=system, convo=convo, full=full, usage_sink=usage_sink,
            )
        except aiproxy.AiProxyError as e:
            log.warning("governor grounding/correction failed, releasing original reply persona=%s: %s",
                        persona.slug, e)
        except Exception:
            log.exception("governor grounding/correction unexpected error persona=%s", persona.slug)

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
