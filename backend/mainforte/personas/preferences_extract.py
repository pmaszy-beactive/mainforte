"""Generalized want/preference extraction (Part 2 of the searchable-memory/text-to-action plan) —
a sibling to `onboarding_extract.py`, not a modification of it. Onboarding stays narrow (2 fixed
keys, capped to a workspace's first few messages, written to User.prefs). This module runs on
every message, unbounded, and classifies whether the member stated a durable want or preference
(travel, product, recurring need) worth remembering as a standing thing rather than an onboarding
field. Same "cheap, tolerant-of-failure LLM call" pattern as events/governor.py's
`_extract_claims` and onboarding_extract.py's `_extract` — most messages aren't preferences, and
that's an expected, fail-open outcome, not an error."""
from __future__ import annotations

import asyncio
import json
import logging

from mainforte.aiproxy import client as aiproxy
from mainforte.aiproxy.keys import get_or_mint
from mainforte.db.models import Preference, Workspace
from mainforte.db.session import db_session
from mainforte.events.governor import CLAIM_MODEL, _strip_json_fence

log = logging.getLogger(__name__)

EXTRACT_SYSTEM = (
    "You'll be given one chat message a member sent to their household concierge. Decide whether "
    "it states a durable want or preference worth remembering long-term — a travel wish, a "
    "product they want, a recurring need, a standing dislike. Do NOT extract one-off requests "
    '("what\'s the weather", "book me a table tonight") or small talk.\n\n'
    'Respond with ONLY {"preference": "<a short, normalized one-line statement, e.g. '
    '\'wants to visit Istanbul\'>"} if one is present, or {"preference": null} if not. No prose, '
    "no markdown fences."
)


def _parse(raw: str) -> str | None:
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    val = data.get("preference")
    if isinstance(val, str) and val.strip():
        return val.strip()[:300]
    return None


async def _extract(*, api_key: str, user_text: str) -> str | None:
    raw, _usage = await aiproxy.complete(
        api_key=api_key, model=CLAIM_MODEL, system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": user_text}], max_tokens=200,
    )
    return _parse(raw)


def maybe_extract_preference(*, ws_id: str, user_id: str | None, user_text: str, source_event_id: str) -> None:
    if not user_text.strip():
        return
    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            return
        api_key = get_or_mint(db, ws)
        if api_key is None:
            return

    try:
        extracted = asyncio.run(_extract(api_key=api_key, user_text=user_text))
    except aiproxy.AiProxyError:
        log.warning("preference extraction failed ws=%s user=%s", ws_id, user_id)
        return
    if not extracted:
        return

    with db_session() as db:
        db.add(Preference(ws_id=ws_id, user_id=user_id, text=extracted,
                           source_event_id=source_event_id, status="noted"))

    log.info("preference noted ws=%s user=%s text=%r", ws_id, user_id, extracted)
