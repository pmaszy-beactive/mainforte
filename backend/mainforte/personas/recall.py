"""Searchable memory (Part 1 of the searchable-memory/text-to-action plan): merges FTS hits from
the durable events log, workspace memory/rollups, and extracted attachment text into one ranked
list, for injection into a reply's system prompt as a "Relevant history" block distinct from
`personas/memory.py`'s recency-curated notes block.

Reuses `events/governor.py::search_interaction_log` rather than reimplementing event search; adds
the same `ts_rank`/`plainto_tsquery` idiom (migration 0010's pattern) for `memories.text_fts` and
`memory_chunks.text_fts` (migration 0017)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from mainforte.events.governor import search_interaction_log

DEFAULT_LIMIT = 5
MIN_RANK = 0.01  # below this, plainto_tsquery matches are noise-level; skip rather than force into every prompt


def _search_memories(db: Session, *, ws_id: str, query: str, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        sa_text(
            """
            select id, kind, created_at, text,
                   ts_rank(text_fts, plainto_tsquery('english', :query)) as rank
            from memories
            where ws_id = :ws_id
              and text_fts @@ plainto_tsquery('english', :query)
            order by rank desc, id desc
            limit :limit
            """
        ),
        {"query": query, "ws_id": ws_id, "limit": limit},
    ).all()
    return [
        {"id": r.id, "source": "memory", "kind": r.kind, "ts": r.created_at,
         "text": r.text[:500], "rank": float(r.rank)}
        for r in rows
    ]


def _search_memory_chunks(db: Session, *, ws_id: str, query: str, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        sa_text(
            """
            select id, source_type, source_id, occurred_at, text,
                   ts_rank(text_fts, plainto_tsquery('english', :query)) as rank
            from memory_chunks
            where ws_id = :ws_id
              and text_fts @@ plainto_tsquery('english', :query)
            order by rank desc, id desc
            limit :limit
            """
        ),
        {"query": query, "ws_id": ws_id, "limit": limit},
    ).all()
    return [
        {"id": r.id, "source": "upload", "kind": r.source_type, "ts": r.occurred_at,
         "text": r.text[:500], "rank": float(r.rank)}
        for r in rows
    ]


def search_memory(db: Session, *, ws_id: str, query: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Ranked, merged hits across events (`search_interaction_log`, bounded by event retention),
    `memories` (rollups + notes, survive past retention), and `memory_chunks` (attachment text).
    Returns up to `limit` hits sorted by rank descending; empty if nothing clears `MIN_RANK`."""
    if not query.strip():
        return []

    event_hits = [
        {"id": h["event_id"], "source": "event", "kind": h["type"], "ts": h["ts"],
         "text": h["text"], "rank": h["rank"]}
        for h in search_interaction_log(db, ws_id=ws_id, query=query, limit=limit)
    ]
    memory_hits = _search_memories(db, ws_id=ws_id, query=query, limit=limit)
    chunk_hits = _search_memory_chunks(db, ws_id=ws_id, query=query, limit=limit)

    merged = [h for h in (*event_hits, *memory_hits, *chunk_hits) if h["rank"] >= MIN_RANK]
    merged.sort(key=lambda h: h["rank"], reverse=True)
    return merged[:limit]


def format_relevant_history(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    lines = []
    for h in hits:
        ts = h["ts"]
        date = ts.strftime("%Y-%m-%d") if isinstance(ts, datetime) else str(ts)
        lines.append(f'- ({date}) "{h["text"]}"')
    return "## Relevant history\n" + "\n".join(lines)
