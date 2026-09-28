from __future__ import annotations

import random

from sqlalchemy.orm import Session

from mainforte.db.models import Persona
from mainforte.events import emit
from mainforte.personas import catalog


def seed_defaults(db: Session, *, ws_id: str, actor: tuple[str, str | None]) -> list[Persona]:
    """Called once when a workspace is created. Adds the always-on personas (Concierge)."""
    created = []
    for slug in catalog.DEFAULT_ON_CREATE:
        created.append(invite(db, ws_id=ws_id, slug=slug, actor=actor))
    return created


def _random_name(slug: str, arche: catalog.Archetype) -> str:
    """Pick a display name when the caller doesn't specify one. Concierge always keeps its default
    name — the member names it themselves during the onboarding interview instead (see
    events/onboarding.py) — every other archetype gets a random first name from its pool, paired
    with the role suffix already baked into default_name (e.g. "Morgan (PM)")."""
    if slug == "concierge":
        return arche.default_name
    pool = catalog.NAME_POOLS.get(slug)
    if not pool:
        return arche.default_name
    first = random.choice(pool)
    suffix = arche.default_name.split("(", 1)
    return f"{first} ({suffix[1]}" if len(suffix) == 2 else first


def invite(db: Session, *, ws_id: str, slug: str, actor: tuple[str, str | None], name: str | None = None) -> Persona:
    arche = catalog.get(slug)
    if arche is None:
        raise ValueError(f"unknown persona archetype {slug!r}")
    existing = db.query(Persona).filter_by(ws_id=ws_id, slug=slug).one_or_none()
    if existing:
        if existing.status == "removed":
            existing.status = "active"
            emit(db, "persona.invited", ws_id=ws_id, actor=actor, payload={"persona_id": existing.id, "slug": slug})
        return existing
    p = Persona(
        ws_id=ws_id, slug=slug, name=name or _random_name(slug, arche), model=arche.default_model,
        settings={"personality_flavor": random.choice(catalog.FLAVOR_SNIPPETS)},
    )
    db.add(p)
    db.flush()
    emit(db, "persona.invited", ws_id=ws_id, actor=actor, payload={"persona_id": p.id, "slug": slug, "name": p.name})
    return p


def rename(db: Session, *, persona: Persona, name: str, actor: tuple[str, str | None]) -> Persona:
    old = persona.name
    persona.name = name
    emit(db, "persona.renamed", ws_id=persona.ws_id, actor=actor,
         payload={"persona_id": persona.id, "old_name": old, "new_name": name})
    return persona


def remove(db: Session, *, persona: Persona, actor: tuple[str, str | None]) -> None:
    persona.status = "removed"
    emit(db, "persona.removed", ws_id=persona.ws_id, actor=actor, payload={"persona_id": persona.id, "slug": persona.slug})


def list_active(db: Session, *, ws_id: str) -> list[Persona]:
    return db.query(Persona).filter_by(ws_id=ws_id, status="active").order_by(Persona.created_at).all()


def public(p: Persona) -> dict:
    arche = catalog.get(p.slug)
    return {
        "id": p.id, "slug": p.slug, "name": p.name, "role": arche.role if arche else "",
        "status": p.status, "model": p.model,
    }
