"""The Governor (PLAN.md §1.5a): checks LLM output against reality instead of trusting it outright.

P1 slice only: claim extraction + fact/memory contradiction checks. No tool/agent-work events exist
yet, so action-claim grounding and the hold-and-reprompt loop are P2 (see governor.reply.held /
.corrected, unused until then). Runs on the `system` queue, after the reply is already durable —
this is a check on a reply that has been emitted, not a gate in front of the client (see PLAN.md
open items: latency/cost is measured before this is moved earlier in the pipeline).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mainforte.aiproxy import client as aiproxy
from mainforte.aiproxy.keys import get_or_mint
from mainforte.aiproxy.pricing import estimate_cost_usd
from mainforte.db.models import Event, Memory, Workspace
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.events.registry import on

log = logging.getLogger(__name__)

CLAIM_MODEL = "claude-haiku-4-5-20251001"

EXTRACT_SYSTEM = (
    "You extract checkable claims from an AI assistant's reply. A claim is checkable if it asserts "
    "a completed action (\"I sent...\", \"I booked...\", \"I found...\") or a concrete fact (a number, "
    "date, name, or policy detail stated with confidence). Ignore small talk, questions, and hedged "
    "or speculative statements (\"I could...\", \"you might want to...\").\n\n"
    "Respond with ONLY a JSON array (no prose, no markdown fences). Each item: "
    '{"type": "action"|"fact", "text": "<the claim, quoted or closely paraphrased>"}. '
    "Empty array if there are no checkable claims."
)

VERIFY_SYSTEM = (
    "You are a skeptical fact-checker. You will be given a claim and some workspace context "
    "(memory notes and recent thread history). Decide if the claim is SUPPORTED, CONTRADICTED, or "
    "UNKNOWN based only on the given context — do not use outside knowledge.\n\n"
    'Respond with ONLY JSON (no prose): {"verdict": "SUPPORTED"|"CONTRADICTED"|"UNKNOWN", "reason": "<one sentence>"}.'
)


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _parse_claims(raw: str) -> list[dict[str, str]]:
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("type") in ("action", "fact") and item.get("text"):
            out.append({"type": item["type"], "text": str(item["text"])[:500]})
    return out


def _record_usage(*, ws_id: str, correlation_id: str | None, purpose: str, usage: dict[str, int]) -> None:
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    if not in_tok and not out_tok:
        return
    with db_session() as db:
        emit(db, "billing.usage.recorded", ws_id=ws_id, actor=("system", None), correlation_id=correlation_id,
             payload={"purpose": purpose, "model": CLAIM_MODEL, "input_tokens": in_tok, "output_tokens": out_tok,
                      "cost_usd": estimate_cost_usd(CLAIM_MODEL, in_tok, out_tok)})


async def _extract_claims(*, api_key: str, reply_text: str, ws_id: str,
                           correlation_id: str | None) -> list[dict[str, str]]:
    raw, usage = await aiproxy.complete(
        api_key=api_key, model=CLAIM_MODEL, system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": reply_text}], max_tokens=400,
    )
    _record_usage(ws_id=ws_id, correlation_id=correlation_id, purpose="governor.extract", usage=usage)
    return _parse_claims(raw)


async def _verify_fact_llm(*, api_key: str, claim_text: str, context: str, ws_id: str,
                            correlation_id: str | None) -> tuple[str, str]:
    raw, usage = await aiproxy.complete(
        api_key=api_key, model=CLAIM_MODEL, system=VERIFY_SYSTEM,
        messages=[{"role": "user", "content": f"Claim: {claim_text}\n\nContext:\n{context}"}],
        max_tokens=200,
    )
    _record_usage(ws_id=ws_id, correlation_id=correlation_id, purpose="governor.verify", usage=usage)
    try:
        d = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        return "UNKNOWN", "verifier returned unparseable output"
    verdict = d.get("verdict") if d.get("verdict") in ("SUPPORTED", "CONTRADICTED", "UNKNOWN") else "UNKNOWN"
    return verdict, str(d.get("reason", ""))[:300]


def _deterministic_context(db, *, ws_id: str, thread_id: str | None) -> str:
    """Memory rows + recent thread events, plain text, for the verifier LLM and for the cheap
    substring cross-check. No LLM involved in building this — only in judging against it."""
    mem_rows = (
        db.query(Memory).filter(Memory.ws_id == ws_id)
        .order_by(Memory.created_at.desc()).limit(30).all()
    )
    lines = [f"memory: {r.text}" for r in mem_rows]
    if thread_id:
        ev_rows = (
            db.query(Event)
            .filter(Event.correlation_id == thread_id,
                    Event.type.in_(("chat.message.created", "persona.reply.ended")))
            .order_by(Event.id.desc()).limit(30).all()
        )
        for ev in reversed(ev_rows):
            text = ev.payload.get("text") or ""
            if text.strip():
                lines.append(f"thread: {text[:300]}")
    return "\n".join(lines)


async def _govern(*, ws_id: str, thread_id: str | None, correlation_id: str | None,
                   persona_id: str | None, reply_text: str) -> None:
    if not reply_text.strip():
        return
    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            return
        api_key = get_or_mint(db, ws)
        if api_key is None:
            return  # no ai-proxy backend configured (local dev): nothing to govern with
        context = _deterministic_context(db, ws_id=ws_id, thread_id=thread_id)

    try:
        claims = await _extract_claims(api_key=api_key, reply_text=reply_text, ws_id=ws_id,
                                        correlation_id=correlation_id)
    except aiproxy.AiProxyError:
        log.exception("governor claim extraction failed ws=%s corr=%s", ws_id, correlation_id)
        return

    if not claims:
        return

    with db_session() as db:
        for claim in claims:
            emit(db, "governor.claim.extracted", ws_id=ws_id, actor=("system", None),
                 correlation_id=correlation_id,
                 payload={"thread_id": thread_id, "persona_id": persona_id, **claim})

        needs_verification = False
        for claim in claims:
            if claim["type"] == "action":
                # P2: no tool.*/agent.work.* events exist yet to ground against, so every action
                # claim today is unverified by construction. Annotate, don't hold — nothing to hold
                # for, since no tool call could have produced a false claim yet either.
                emit(db, "governor.claim.unverified", ws_id=ws_id, actor=("system", None),
                     correlation_id=correlation_id,
                     payload={"thread_id": thread_id, "persona_id": persona_id, **claim,
                              "reason": "no tool/agent-work events to ground against (P2)"})
                needs_verification = True
                continue

            claim_lower = claim["text"].lower()
            if any(claim_lower in line.lower() or line.lower() in claim_lower
                   for line in context.splitlines() if line.strip()):
                emit(db, "governor.claim.verified", ws_id=ws_id, actor=("system", None),
                     correlation_id=correlation_id,
                     payload={"thread_id": thread_id, "persona_id": persona_id, **claim,
                              "method": "deterministic"})
                continue

            try:
                verdict, reason = await _verify_fact_llm(api_key=api_key, claim_text=claim["text"], context=context,
                                                          ws_id=ws_id, correlation_id=correlation_id)
            except aiproxy.AiProxyError:
                log.exception("governor fact verification failed ws=%s corr=%s", ws_id, correlation_id)
                verdict, reason = "UNKNOWN", "verifier call failed"

            if verdict == "SUPPORTED":
                emit(db, "governor.claim.verified", ws_id=ws_id, actor=("system", None),
                     correlation_id=correlation_id,
                     payload={"thread_id": thread_id, "persona_id": persona_id, **claim,
                              "method": "llm", "reason": reason})
            elif verdict == "CONTRADICTED":
                emit(db, "governor.claim.contradicted", ws_id=ws_id, actor=("system", None),
                     correlation_id=correlation_id,
                     payload={"thread_id": thread_id, "persona_id": persona_id, **claim, "reason": reason})
                needs_verification = True
            else:
                emit(db, "governor.claim.unverified", ws_id=ws_id, actor=("system", None),
                     correlation_id=correlation_id,
                     payload={"thread_id": thread_id, "persona_id": persona_id, **claim, "reason": reason})
                needs_verification = True

        emit(db, "governor.reply.released", ws_id=ws_id, actor=("system", None),
             correlation_id=correlation_id,
             payload={"thread_id": thread_id, "persona_id": persona_id, "needs_verification": needs_verification})


@on("persona.reply.ended", queue="system")
def govern_persona_reply(event: dict[str, Any]) -> None:
    ws_id = event.get("ws_id")
    payload = event.get("payload") or {}
    text = payload.get("text") or ""
    if not ws_id or not text.strip():
        return
    asyncio.run(_govern(
        ws_id=ws_id, thread_id=payload.get("thread_id"), correlation_id=event.get("correlation_id"),
        persona_id=payload.get("persona_id"), reply_text=text,
    ))


@on("chat.thread.rolled_up", queue="system")
def govern_rollup(event: dict[str, Any]) -> None:
    ws_id = event.get("ws_id")
    payload = event.get("payload") or {}
    memory_id = payload.get("memory_id")
    if not ws_id or not memory_id:
        return
    with db_session() as db:
        mem = db.get(Memory, memory_id)
        text = mem.text if mem else ""
    if not text.strip():
        return
    asyncio.run(_govern(
        ws_id=ws_id, thread_id=payload.get("thread_id"), correlation_id=payload.get("thread_id"),
        persona_id=None, reply_text=text,
    ))
