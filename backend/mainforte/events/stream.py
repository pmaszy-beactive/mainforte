"""Redis Streams fan-out. One stream per workspace: ws:{id}. Global (no workspace) events go to ws:_global."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import redis
import redis.asyncio as aioredis

from mainforte.config import get_settings


def stream_key(ws_id: str | None) -> str:
    return f"ws:{ws_id or '_global'}"


@lru_cache
def sync_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


@lru_cache
def async_redis() -> aioredis.Redis:
    # socket_timeout must exceed the XREAD block we use in read_after, or blocking reads get cut off client-side.
    return aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_timeout=30, socket_keepalive=True)


async def last_id(ws_id: str | None) -> str:
    """Current tail position of the stream ("0-0" if empty). Capture this BEFORE replaying from Postgres."""
    r = async_redis()
    entries = await r.xrevrange(stream_key(ws_id), count=1)
    return entries[0][0] if entries else "0-0"


def publish(event: dict[str, Any]) -> None:
    r = sync_redis()
    # We use the event ULID as the stream entry id ordering key inside the payload; Redis assigns its own id.
    r.xadd(stream_key(event.get("ws_id")), {"e": json.dumps(event, default=str)},
           maxlen=get_settings().event_stream_maxlen, approximate=True)


async def read_after(ws_id: str | None, last_redis_id: str, block_ms: int = 5_000) -> list[tuple[str, dict[str, Any]]]:
    r = async_redis()
    res = await r.xread({stream_key(ws_id): last_redis_id}, block=block_ms, count=200)
    out: list[tuple[str, dict[str, Any]]] = []
    for _key, entries in res:
        for rid, fields in entries:
            out.append((rid, json.loads(fields["e"])))
    return out
