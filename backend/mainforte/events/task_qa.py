"""P4 task QA stage: grounds a task's own tool calls the same way the chat Governor grounds a
persona reply, but with claims derived deterministically instead of LLM-extracted from free text.

A task stage's claims are already structured — one per successful `stage["tool"]` call in
`plan` — so there's no free-text reply to run `_extract_claims` on. `run_qa` below builds claims
directly from the `tool.ended`/`agent.work.ended` events emitted by the stages in
`[last_qa_stage, current_stage)`, then reuses `ground_action_claims` unmodified.
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.orm import Session

from mainforte.db.models import Event
from mainforte.events.governor import ground_action_claims


def _stage_claims(db: Session, *, base_corr: str, first_stage: int,
                   last_stage: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One action claim per successful tool call in stages `[first_stage, last_stage)`, phrased so
    `ground_action_claims`'s substring/LLM check can match it against that same stage's own
    `tool.ended`/`agent.work.ended` event text (`name=<tool> result=<result>`). Also returns any
    `tool.error` events found in the window: a `continue_on_error` stage lets `run_task_stage`
    advance past a failed tool call with no `tool.ended` claim to ground — silently, unless QA
    itself treats that hole as a failure, so it's surfaced here as an unconditional QA failure
    rather than the vacuous "no claims, so it passed" a missing tool.ended would otherwise imply."""
    claims: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for stage_index in range(first_stage, last_stage):
        stage_corr = f"{base_corr}:{stage_index}"
        rows = (
            db.query(Event)
            .filter(Event.correlation_id == stage_corr,
                    Event.type.in_(("tool.ended", "agent.work.ended", "tool.error")))
            .order_by(Event.id.asc()).all()
        )
        for ev in rows:
            name = ev.payload.get("name") or ev.payload.get("tool") or "tool"
            if ev.type == "tool.error":
                errors.append({
                    "stage_index": stage_index, "stage_corr": stage_corr,
                    "text": f"name={name} message={ev.payload.get('message')}",
                })
                continue
            result = ev.payload.get("result")
            claims.append({
                "type": "action", "text": f"name={name} result={result}",
                "stage_index": stage_index, "stage_corr": stage_corr,
            })
    return claims, errors


async def run_qa(db: Session, *, ws_id: str, base_corr: str, api_key: str | None,
                  first_stage: int, last_stage: int) -> dict[str, Any]:
    """Grounds every claim in `[first_stage, last_stage)` against that stage's own events. Returns
    `{"passed": bool, "checked_stages": [...], "unverified": [...]}`. No claims and no tool errors
    to check (e.g. a window of only `await_input` stages) counts as passed."""
    claims, errors = _stage_claims(db, base_corr=base_corr, first_stage=first_stage, last_stage=last_stage)
    checked_stages = list(range(first_stage, last_stage))
    if errors:
        unverified = [{"stage_index": e["stage_index"], "claim": e["text"],
                       "reason": "stage tool call errored (continue_on_error let it advance)"}
                      for e in errors]
        return {"passed": False, "checked_stages": checked_stages, "unverified": unverified}
    if not claims:
        return {"passed": True, "checked_stages": checked_stages, "unverified": []}

    # ground_action_claims groups all claims under one correlation_id for its event lookup — call
    # it once per stage so each claim is only matched against its own stage's events, not the
    # whole window's (a later stage's tool.ended must not "cover for" an earlier stage's claim).
    unverified: list[dict[str, Any]] = []
    for stage_index in checked_stages:
        stage_claims = [c for c in claims if c["stage_index"] == stage_index]
        if not stage_claims:
            continue
        stage_corr = f"{base_corr}:{stage_index}"
        results = await ground_action_claims(
            db, ws_id=ws_id, correlation_id=stage_corr, api_key=api_key,
            claims=[{"type": c["type"], "text": c["text"]} for c in stage_claims],
        )
        for claim, result in zip(stage_claims, results):
            if not result["verified"]:
                unverified.append({"stage_index": stage_index, "claim": claim["text"], "reason": result["reason"]})

    return {"passed": not unverified, "checked_stages": checked_stages, "unverified": unverified}


def run_qa_sync(db: Session, *, ws_id: str, base_corr: str, api_key: str | None,
                 first_stage: int, last_stage: int) -> dict[str, Any]:
    return asyncio.run(run_qa(db, ws_id=ws_id, base_corr=base_corr, api_key=api_key,
                               first_stage=first_stage, last_stage=last_stage))
