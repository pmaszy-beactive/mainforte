"""Pulls structured preferences (Concierge name, interaction style) out of a member's reply to
the onboarding interview (see events/onboarding.py) and lands them on User.prefs.

The interview itself is just prompt-engineered into the Concierge's system prompt for a brand-new
workspace — there's no hand-rolled multi-turn state machine. This module is the other half: once
the member answers in a normal chat message, `route_message` (personas/router.py) calls
`maybe_extract_prefs` after the reply completes. One cheap, tolerant-of-failure LLM call (same
pattern as events/governor.py's `_extract_claims`) turns free text into
`{"concierge_name": ..., "interaction_style": ...}`, merged into `User.prefs`. If a name was
given, the Concierge is renamed to match.
"""
from __future__ import annotations

import asyncio
import json
import logging

from mainforte.aiproxy import client as aiproxy
from mainforte.aiproxy.keys import get_or_mint
from mainforte.db.models import Event, Persona, User, Workspace
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.events.governor import CLAIM_MODEL, _strip_json_fence
from mainforte.personas.service import rename

log = logging.getLogger(__name__)

# Only worth checking while the workspace is brand new — a handful of messages in, either the
# member already answered (prefs are set) or they skipped past it, and re-checking every message
# forever would be wasted latency/cost for no benefit.
MAX_MESSAGES_TO_CHECK = 6

EXTRACT_SYSTEM = (
    "The household's Concierge just asked a new member what to call it and how they like to "
    "interact (terse vs. conversational, etc.). You'll be given the member's reply. Extract, if "
    'present: {"concierge_name": "<name they want to use, or null>", '
    '"interaction_style": "<a short phrase describing their preference, or null>"}.\n\n'
    "Respond with ONLY that JSON object (no prose, no markdown fences). Use null for anything not "
    "actually stated — never guess or invent a value."
)


def _parse(raw: str) -> dict[str, str]:
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key in ("concierge_name", "interaction_style"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()[:200]
    return out


async def _extract(*, api_key: str, user_text: str) -> dict[str, str]:
    raw, _usage = await aiproxy.complete(
        api_key=api_key, model=CLAIM_MODEL, system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": user_text}], max_tokens=200,
    )
    return _parse(raw)


def maybe_extract_prefs(*, ws_id: str, user_id: str, user_text: str) -> None:
    if not user_text.strip():
        return
    with db_session() as db:
        user = db.get(User, user_id)
        if user is None:
            return
        if user.prefs.get("concierge_name") and user.prefs.get("interaction_style"):
            return  # already have both — nothing left to extract
        msg_count = (
            db.query(Event)
            .filter(Event.ws_id == ws_id, Event.type == "chat.message.created")
            .count()
        )
        if msg_count > MAX_MESSAGES_TO_CHECK:
            return
        ws = db.get(Workspace, ws_id)
        if ws is None:
            return
        api_key = get_or_mint(db, ws)
        if api_key is None:
            return

    try:
        extracted = asyncio.run(_extract(api_key=api_key, user_text=user_text))
    except aiproxy.AiProxyError:
        log.warning("onboarding prefs extraction failed ws=%s user=%s", ws_id, user_id)
        return
    if not extracted:
        return

    with db_session() as db:
        user = db.get(User, user_id)
        if user is None:
            return
        merged = dict(user.prefs)
        merged.update(extracted)
        user.prefs = merged
        emit(db, "user.prefs.updated", ws_id=ws_id, user_id=user_id, actor=("user", user_id),
             payload={"updated_keys": list(extracted.keys())})

        cname = extracted.get("concierge_name")
        if cname:
            concierge = db.query(Persona).filter_by(ws_id=ws_id, slug="concierge", status="active").one_or_none()
            if concierge and concierge.name != cname:
                rename(db, persona=concierge, name=cname, actor=("user", user_id))

    log.info("onboarding prefs extracted ws=%s user=%s keys=%s", ws_id, user_id, list(extracted.keys()))
