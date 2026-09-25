"""Default handlers. Every namespace has at least a no-op so the wiring is exercised from day one.
Real behaviour (persona router, billing meter, ...) is added in later phases next to its feature.
"""
from __future__ import annotations

import logging
from typing import Any

from mainforte.events.registry import on

log = logging.getLogger(__name__)


@on("*", sync=True)
def _trace(event: dict[str, Any]) -> None:
    log.info("event %s %s ws=%s actor=%s", event["id"], event["type"], event.get("ws_id"), event["actor"])


@on("chat.message.created", queue="chat")
def route_personas(event: dict[str, Any]) -> None:
    from mainforte.personas.router import route_message

    route_message(event)


@on("agent.work.ended", queue="system")
def meter_usage(event: dict[str, Any]) -> None:
    """P3: record usage against the workspace. P0: no-op."""
    return None


@on("*.error", queue="system")
def record_error(event: dict[str, Any]) -> None:
    from mainforte.db.models import ApiError
    from mainforte.db.session import db_session

    with db_session() as db:
        db.add(ApiError(type=event["type"], message=str(event["payload"].get("message", ""))[:4000],
                        user_id=event.get("user_id"), ws_id=event.get("ws_id"),
                        context={"event_id": event["id"], **{k: v for k, v in event["payload"].items() if k != "message"}}))
