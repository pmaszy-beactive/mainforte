from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mainforte.auth.deps import Identity, current_identity, require_membership
from mainforte.db.models import Persona
from mainforte.db.session import get_db
from mainforte.personas import catalog, service

router = APIRouter(prefix="/api/workspaces/{workspace_id}/personas", tags=["personas"])


class InviteIn(BaseModel):
    slug: str
    name: str | None = Field(None, max_length=80)


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.get("")
def list_personas(workspace_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    return {"personas": [service.public(p) for p in service.list_active(db, ws_id=ws.id)],
            "available": [{"slug": a.slug, "name": a.default_name, "role": a.role} for a in catalog.ARCHETYPES.values()]}


@router.post("", status_code=201)
def invite_persona(workspace_id: str, body: InviteIn, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    try:
        p = service.invite(db, ws_id=ws.id, slug=body.slug, actor=("user", ident.user.id), name=body.name)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return service.public(p)


@router.patch("/{persona_id}")
def rename_persona(workspace_id: str, persona_id: str, body: RenameIn,
                   ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    p = db.get(Persona, persona_id)
    if not p or p.ws_id != ws.id or p.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    service.rename(db, persona=p, name=body.name, actor=("user", ident.user.id))
    return service.public(p)


@router.delete("/{persona_id}", status_code=204)
def remove_persona(workspace_id: str, persona_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    p = db.get(Persona, persona_id)
    if not p or p.ws_id != ws.id or p.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if p.slug == "concierge":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the concierge can't be removed")
    service.remove(db, persona=p, actor=("user", ident.user.id))
    return None
