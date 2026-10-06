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


def _search_memory_chunks(
    db: Session, *, ws_id: str, query: str, limit: int, thread_id: str | None = None,
    snippet_len: int = 500, headline: bool = False,
) -> list[dict[str, Any]]:
    """`thread_id`, when given, restricts to chunks from attachments shared in that thread (chunks
    from other threads in the same workspace are irrelevant noise for a reply's own context).

    A `memory_chunks` row holds a whole upload's extracted text (an upload isn't split into
    multiple rows), which can be far larger than `snippet_len` -- `text[:snippet_len]` would
    silently return the document's opening and never the part that actually matched (confirmed
    live: a match 45k characters into a 90k-character document was dropped entirely by plain
    prefix truncation). `headline=True` uses Postgres's `ts_headline` instead, which extracts an
    excerpt centered on the matching terms; the general "relevant history" recall path this
    function was originally built for keeps plain prefix truncation (its rows are short
    memories/rollups already, not whole documents, and a short search preview doesn't need
    match-centering)."""
    # StartSel/StopSel default to <b>/</b> (for UI highlighting); stripped in Python below since
    # this snippet goes into an LLM prompt, not rendered HTML.
    headline_sql = (
        "ts_headline('english', text, plainto_tsquery('english', :query), "
        "'MaxFragments=3, MaxWords=120, MinWords=30, FragmentDelimiter= ... ')"
        if headline else "left(text, :snippet_len)"
    )
    rows = db.execute(
        sa_text(
            f"""
            select id, source_type, source_id, occurred_at, {headline_sql} as snippet,
                   ts_rank(text_fts, plainto_tsquery('english', :query)) as rank
            from memory_chunks
            where ws_id = :ws_id
              and text_fts @@ plainto_tsquery('english', :query)
              and (cast(:thread_id as varchar) is null or thread_id = cast(:thread_id as varchar))
            order by rank desc, id desc
            limit :limit
            """
        ),
        {"query": query, "ws_id": ws_id, "limit": limit, "thread_id": thread_id, "snippet_len": snippet_len},
    ).all()
    return [
        {"id": r.id, "source": "upload", "kind": r.source_type, "ts": r.occurred_at,
         "text": r.snippet.replace("<b>", "").replace("</b>", "") if headline else r.snippet,
         "rank": float(r.rank)}
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


ATTACHMENT_SNIPPET_LEN = 4000  # ~1k tokens; bounds each retrieved chunk, not the source document


def search_attachment_chunks(
    db: Session, *, ws_id: str, thread_id: str | None, query: str, limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Top-ranked attachment text chunks for this thread, matched against the current message --
    used to give the model relevant excerpts from shared files without stuffing whole documents
    into the prompt (T02800 follow-up: attachments were never reaching the model at all)."""
    if not query.strip():
        return []
    hits = _search_memory_chunks(
        db, ws_id=ws_id, query=query, limit=limit, thread_id=thread_id,
        snippet_len=ATTACHMENT_SNIPPET_LEN, headline=True,
    )
    return [h for h in hits if h["rank"] >= MIN_RANK]


def format_relevant_history(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    lines = []
    for h in hits:
        ts = h["ts"]
        date = ts.strftime("%Y-%m-%d") if isinstance(ts, datetime) else str(ts)
        lines.append(f'- ({date}) "{h["text"]}"')
    return "## Relevant history\n" + "\n".join(lines)
