"""Marketplace search (v1). Postgres FTS first (`fts_search`), with one optional AI call
(`ai_parse_query`) that turns a natural-language query into structured filters before the SQL
runs — mirrors `events/governor.py::search_interaction_log`'s `ts_rank`/`plainto_tsquery`
technique and `_extract_claims`'s `aiproxy.complete()` call shape. No embeddings: this codebase has
none, and the stated bias (governor.py) is "FTS first, embeddings only if this proves
insufficient."

`ai_parse_query` never raises for a caller-facing reason: on any failure (ai-proxy disabled, no
key, bad JSON, network error) it returns `None` and the caller falls back to plain keyword FTS.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from mainforte.aiproxy import client as aiproxy

log = logging.getLogger(__name__)

SEARCH_MODEL = "claude-haiku-4-5-20251001"

_PARSE_SYSTEM = """You turn a shopper's natural-language search into structured filters for a \
marketplace search. Respond with ONLY a JSON object, no prose, no markdown fences, shaped exactly:
{"keywords": string, "category": string|null, "min_price_cents": integer|null, \
"max_price_cents": integer|null, "kind": "good"|"service"|null}

"keywords" is a short plain-text string of the core search terms (strip filler words like "find \
me" or "something for"). Only set "category" if the query clearly implies one of: general, \
electronics, furniture, clothing, kids_baby, tools, sports_outdoors, books_media, home_garden, \
tickets_events, services_lessons, services_home, services_other, free -- otherwise null. Prices \
are in whole cents (e.g. "under $50" -> max_price_cents: 5000). "kind" is "service" only for \
lessons/gigs/services, "good" only for physical items, otherwise null when ambiguous."""


def fts_search(
    db: Session, *, query: str | None = None, category: str | None = None,
    min_price_cents: int | None = None, max_price_cents: int | None = None,
    kind: str | None = None, limit: int = 30,
) -> list[dict[str, Any]]:
    """`status='active'` listings, best-match-first when `query` is set else newest-first, with
    optional category/price/kind filters. `Listing.text_fts` is migration-added only (never
    ORM-mapped), same treatment as `Event.text_fts` -- queried here via raw SQL."""
    has_query = bool(query and query.strip())
    rows = db.execute(
        sa_text(
            f"""
            select id, seller_user_id, kind, title, description, category, condition,
                   price_cents, currency, location_label, lat, lng, status, created_at
                   {", ts_rank(text_fts, plainto_tsquery('english', :query)) as rank" if has_query else ""}
            from listings
            where status = 'active'
              and (:query_empty or text_fts @@ plainto_tsquery('english', :query))
              and (:category is null or category = :category)
              and (:min_price is null or price_cents >= :min_price)
              and (:max_price is null or price_cents <= :max_price)
              and (:kind is null or kind = :kind)
            order by {"rank desc, " if has_query else ""}created_at desc
            limit :limit
            """
        ),
        {
            "query": query or "", "query_empty": not has_query, "category": category,
            "min_price": min_price_cents, "max_price": max_price_cents, "kind": kind, "limit": limit,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


async def ai_parse_query(*, api_key: str, query: str) -> dict[str, Any] | None:
    """One aiproxy.complete() call parsing `query` into structured filters. Returns None (never
    raises) on any failure so the caller can transparently fall back to keyword-only FTS."""
    if not aiproxy.enabled() or not api_key:
        return None
    try:
        raw, _usage = await aiproxy.complete(
            api_key=api_key, model=SEARCH_MODEL, system=_PARSE_SYSTEM,
            messages=[{"role": "user", "content": query}], max_tokens=200,
        )
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception:
        log.info("marketplace.search: ai_parse_query failed, falling back to plain FTS", exc_info=True)
        return None


def radius_filter(
    listings: list[dict[str, Any]], *, lat: float, lng: float, radius_km: float,
) -> list[dict[str, Any]]:
    """Haversine distance over an already-small prefiltered set -- no PostGIS, no geocoding.
    Listings without lat/lng are excluded (can't be placed in a radius). Adds a `distance_km` key,
    sorted nearest-first."""
    out = []
    for listing in listings:
        llat, llng = listing.get("lat"), listing.get("lng")
        if llat is None or llng is None:
            continue
        distance_km = _haversine_km(lat, lng, llat, llng)
        if distance_km <= radius_km:
            out.append({**listing, "distance_km": distance_km})
    out.sort(key=lambda x: x["distance_km"])
    return out


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
