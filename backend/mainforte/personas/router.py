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
from mainforte.db.models import Persona, User, Workspace
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


def _emit_reply_debug(*, ws_id: str, thread_id: str | None, correlation_id: str, persona: Persona,
                       model: str | None, system: str | None, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]] | None, text: str,
                       tool_use: list[aiproxy.ToolUseBlock] | None = None,
                       stop_reason: str | None = None, usage: dict[str, int] | None = None,
                       fallback: bool = False) -> None:
    """Durable capture of one LLM round-trip (or the echo fallback in its place) for admin
    debugging (`GET /api/admin/work/{correlation_id}`). Emitted via `emit()`, not
    `emit_ephemeral` — unlike `persona.reply.delta`, this must survive to be inspectable after the
    fact. `messages` is stored as sent (already-bounded by MAX_REPLY_TOKENS/model context, so this
    is acceptable JSONB size); `tools` is recorded as a count only, not the full schema, since the
    schema is static and available from `tools/catalog.py`."""
    with db_session() as db:
        emit(db, "persona.reply.debug", ws_id=ws_id, actor=("persona", persona.slug), user_id=None,
             correlation_id=correlation_id,
             payload={
                 "thread_id": thread_id, "persona_id": persona.id, "model": model, "fallback": fallback,
                 "request": {"system": system, "messages": messages, "tools_count": len(tools or [])},
                 "response": {
                     "text": text,
                     "tool_use": [{"id": tu.id, "name": tu.name, "input": tu.input} for tu in (tool_use or [])],
                     "stop_reason": stop_reason,
                     "usage": usage or {},
                 },
             })


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
    messages_sent = list(convo)
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
    _emit_reply_debug(ws_id=ws_id, thread_id=thread_id, correlation_id=correlation_id, persona=persona,
                       model=persona.model, system=system, messages=messages_sent, tools=_ALL_TOOLS,
                       text=text, tool_use=tool_use_sink, stop_reason=stop_reason_sink.get("stop_reason"),
                       usage=round_usage)
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


def _commit_dirty_site_scratches(ws_id: str, correlation_id: str) -> None:
    """Turn-end hook for the Sites live-editing flow (PLAN.md's "Live editing: revised design",
    sites/source.py's module docstring): if this turn's tool calls left a local scratch checkout
    under /tmp/sites/*/{correlation_id}/ (write_site_file creates it lazily on first write — see
    tools/catalog.py's `_scratch_file_path`), validate it, ship it into the running container, and
    only on success commit it back to S3 as the new master + bump `Site.source_version`. A build
    failure or a crash-on-restart is fed back as a plain `site.error`-style event rather than
    raised — this always runs from the same final `with db_session()` block as
    persona.reply.ended/.error, after the reply itself is already decided, so a sync failure here
    must never turn a successful chat reply into a failed one; it's reported as its own event, and
    the site's `last_error` is set for the persona's *next* turn to notice and explain in plain
    language (never this turn's already-streamed reply).

    Scans SCRATCH_ROOT for `*/{correlation_id}` dirs rather than tracking "which sites did this
    turn touch" through the dispatch loop above — simpler than threading extra state through every
    tool call, and correct since correlation_id is unique per turn (sites/source.py's
    `_scratch_path` keys on it for exactly this reason)."""
    from mainforte.db.models import Site
    from mainforte.sites import service as site_service
    from mainforte.sites import source as site_source

    if not site_source.SCRATCH_ROOT.is_dir():
        return
    for site_dir in site_source.SCRATCH_ROOT.iterdir():
        scratch_dir = site_dir / correlation_id
        if not scratch_dir.is_dir():
            continue
        site_id = site_dir.name
        with db_session() as db:
            site = db.get(Site, site_id)
            if site is None or site.ws_id != ws_id:
                # Not this workspace's site (shouldn't happen — _load_site already scoped every
                # tool call — but never sync/commit something we can't re-verify ownership of).
                site_source.discard_scratch(site_id, correlation_id)
                continue
            scratch = site_source.TurnScratch(site_id=site_id, version=site.source_version, path=scratch_dir)
            try:
                build_error = site_source.validate_scratch(scratch)
                ship_error = build_error or site_source.ship_to_container(db, site, scratch)
                if ship_error:
                    site_service.mark_error(db, site, error=build_error or ship_error)
                    emit(db, "build.failed", ws_id=ws_id, actor=("persona", None),
                         correlation_id=correlation_id, payload={"site_id": site_id})
                    emit(db, "site.error", ws_id=ws_id, actor=("persona", None), correlation_id=correlation_id,
                         payload={"site_id": site_id, "message": "edit_failed"})
                    continue
                new_version = site_source.commit_turn(site_id, correlation_id, scratch)
                site.source_version = new_version
                # Generic build.* namespace, not a parallel site.build.* — matches
                # provisioning.py's handle_callback convention (see events/types.py's comment on
                # the site.* block) and site.file.changed already emitted per-write above covers
                # the site-specific "what changed" signal; this event is just "the build ran ok".
                emit(db, "build.succeeded", ws_id=ws_id, actor=("persona", None),
                     correlation_id=correlation_id, payload={"site_id": site_id, "version": new_version})
            except Exception as e:
                log.exception("site scratch commit failed site=%s corr=%s", site_id, correlation_id)
                site_service.mark_error(db, site, error=str(e))
                emit(db, "build.failed", ws_id=ws_id, actor=("persona", None),
                     correlation_id=correlation_id, payload={"site_id": site_id})
                emit(db, "site.error", ws_id=ws_id, actor=("persona", None), correlation_id=correlation_id,
                     payload={"site_id": site_id, "message": "edit_exception"})
            finally:
                site_source.discard_scratch(site_id, correlation_id)


async def run_reply(*, ws_id: str, thread_id: str | None, correlation_id: str, persona: Persona,
                     api_key: str | None, history: list[dict[str, Any]], user_text: str,
                     user: User | None = None) -> None:
    arche = catalog.get(persona.slug)
    base = arche.system_prompt if arche else "You are a helpful assistant."
    with db_session() as db:
        system = build_system_prompt(db, ws_id=ws_id, persona=persona, base=base, user=user)
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
            _emit_reply_debug(ws_id=ws_id, thread_id=thread_id, correlation_id=correlation_id, persona=persona,
                               model=persona.model, system=system, messages=convo, tools=_ALL_TOOLS,
                               text=full, fallback=True)
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
                messages_sent = list(convo)
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
                _emit_reply_debug(ws_id=ws_id, thread_id=thread_id, correlation_id=correlation_id, persona=persona,
                                   model=persona.model, system=system, messages=messages_sent, tools=_ALL_TOOLS,
                                   text=round_text, tool_use=tool_use_sink,
                                   stop_reason=stop_reason_sink.get("stop_reason"), usage=round_usage)
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
                        call_input = dict(tu.input)
                        if tu.name == "create_task":
                            call_input.update(ws_id=ws_id, thread_id=thread_id, persona_id=persona.id,
                                               correlation_id=correlation_id)
                        elif tu.name == "create_widget":
                            # Pre-existing gap: create_widget's handler requires ws_id/owner_id but
                            # its input_schema never asks the model for them (there's no way for
                            # the LLM to know a workspace/user id) — inject ws_id from the request
                            # context, same as create_task above; the handler itself resolves
                            # owner_id from ws_id (Workspace.owner_id), same collapse-to-one-user
                            # convention tasks/work.py's _home_owner already uses.
                            call_input.update(ws_id=ws_id, correlation_id=correlation_id)
                        elif tu.name == "create_site":
                            call_input.update(ws_id=ws_id, thread_id=thread_id, correlation_id=correlation_id)
                        elif tu.name in ("read_site_file", "write_site_file", "list_site_files", "read_site_logs"):
                            # Sites tools (PLAN.md Sites section): scoped to the calling workspace
                            # so a persona can never reach a site outside it, mirroring create_task
                            # and create_widget above.
                            call_input.update(ws_id=ws_id, correlation_id=correlation_id)
                        result = tool.handler(**call_input)
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

    # Sites live-editing turn-end hook (PLAN.md's "Live editing: revised design") — runs after the
    # reply itself is fully decided and emitted above, in its own db_session (not nested in the one
    # above: _commit_dirty_site_scratches opens a fresh session per dirty site, and a sync failure
    # here must never affect the already-emitted persona.reply.* event). No-op if this turn never
    # called write_site_file (the scratch-dir scan below finds nothing and returns immediately).
    try:
        _commit_dirty_site_scratches(ws_id, correlation_id)
    except Exception:
        log.exception("site scratch commit sweep failed ws=%s corr=%s", ws_id, correlation_id)


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
    user_id = event.get("user_id")

    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            return
        roster = list_active(db, ws_id=ws_id)
        if not roster:
            return
        targets = _pick_personas(user_text, roster)
        api_key = get_or_mint(db, ws)
        user = db.get(User, user_id) if user_id else None
        current = {"role": "user", "content": user_text.strip() or "(attachment only)"}
        history = [*recent_thread_messages(db, thread_id=thread_id), current]

    async def _run_all() -> None:
        for persona in targets:
            if _is_canceled(ws_id, thread_id, correlation_id):
                break
            await run_reply(ws_id=ws_id, thread_id=thread_id, correlation_id=correlation_id, persona=persona,
                             api_key=api_key, history=history, user_text=user_text, user=user)

    asyncio.run(_run_all())

    if user_id:
        from mainforte.personas.onboarding_extract import maybe_extract_prefs
        maybe_extract_prefs(ws_id=ws_id, user_id=user_id, user_text=user_text)
