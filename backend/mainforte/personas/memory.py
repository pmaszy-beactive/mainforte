"""Workspace/persona memory injection: shared notes + rollups appended to the system prompt,
and thread lookback built from the durable event log (no separate history table needed)."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from mainforte.db.models import Event, Memory, Persona, User

MEMORY_LIMIT = 20
HISTORY_LIMIT = 20


def build_system_prompt(db: Session, *, ws_id: str, persona: Persona, base: str, user: User | None = None) -> str:
    rows = (
        db.query(Memory)
        .filter(
            Memory.ws_id == ws_id,
            or_(
                Memory.kind.in_(("workspace", "rollup_day")),
                (Memory.kind == "persona") & (Memory.persona_id == persona.id),
            ),
        )
        .order_by(Memory.created_at.desc())
        .limit(MEMORY_LIMIT)
        .all()
    )
    out = base
    if rows:
        notes = "\n".join(f"- {r.text}" for r in reversed(rows))
        out = f"{out}\n\n## Workspace memory\n{notes}"

    flavor = (persona.settings or {}).get("personality_flavor")
    if flavor:
        out = f"{out}\n\n## Personality\n{flavor}"

    if user and user.prefs:
        lines = []
        cname = user.prefs.get("concierge_name")
        if cname and persona.slug == "concierge":
            lines.append(f'This member calls you "{cname}".')
        style = user.prefs.get("interaction_style")
        if style:
            lines.append(f"Preferred interaction style: {style}")
        if lines:
            out = f"{out}\n\n## This member's preferences\n" + "\n".join(f"- {l}" for l in lines)

    return out


def recent_thread_messages(db: Session, *, thread_id: str | None, limit: int = HISTORY_LIMIT) -> list[dict[str, str]]:
    if not thread_id:
        return []
    rows = (
        db.query(Event)
        .filter(
            Event.correlation_id == thread_id,
            Event.type.in_(("chat.message.created", "persona.reply.ended", "persona.reply.canceled")),
        )
        .order_by(Event.id.asc())
        .limit(limit)
        .all()
    )
    out: list[dict[str, str]] = []
    for ev in rows:
        if ev.type == "chat.message.created":
            text = ev.payload.get("text") or ""
            if text.strip():
                out.append({"role": "user", "content": text})
        else:
            text = ev.payload.get("text") or ""
            if text.strip():
                out.append({"role": "assistant", "content": text})
    return out[-limit:]
