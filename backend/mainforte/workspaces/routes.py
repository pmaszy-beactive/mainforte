from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from mainforte.auth.deps import Identity, current_identity, require_membership
from mainforte.auth.service import create_user
from mainforte.db.models import Event, Membership, User, Workspace
from mainforte.db.session import get_db
from mainforte.events import emit
from mainforte.events.bus import to_dict

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemberIn(BaseModel):
    email: EmailStr
    role: str = "member"


def _ws_out(ws: Workspace, role: str | None) -> dict:
    return {"id": ws.id, "name": ws.name, "plan": ws.plan, "role": role, "owner_id": ws.owner_id}


@router.get("")
def list_workspaces(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    rows = (db.query(Membership, Workspace).join(Workspace, Workspace.id == Membership.workspace_id)
            .filter(Membership.user_id == ident.user.id).all())
    return [_ws_out(w, m.role) for m, w in rows]


@router.post("", status_code=201)
def create_workspace(body: WorkspaceIn, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = Workspace(name=body.name, owner_id=ident.user.id)
    db.add(ws)
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=ident.user.id, role="owner"))
    emit(db, "workspace.created", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.real_user.id), payload={"name": ws.name})
    return _ws_out(ws, "owner")


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    members = (db.query(Membership, User).join(User, User.id == Membership.user_id)
               .filter(Membership.workspace_id == ws.id).all())
    return {**_ws_out(ws, None), "members": [{"user_id": u.id, "email": u.email, "name": u.name, "role": m.role} for m, u in members]}


@router.post("/{workspace_id}/members", status_code=201)
def add_member(workspace_id: str, body: MemberIn, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db, roles={"owner", "admin"})
    if body.role not in {"admin", "member"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be admin or member")
    user = db.query(User).filter_by(email=body.email.lower()).first() or create_user(db, email=body.email, actor=("user", ident.real_user.id))
    if db.query(Membership).filter_by(workspace_id=ws.id, user_id=user.id).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "already a member")
    db.add(Membership(workspace_id=ws.id, user_id=user.id, role=body.role))
    emit(db, "workspace.member.added", ws_id=ws.id, user_id=user.id, actor=("user", ident.real_user.id),
         payload={"email": user.email, "role": body.role})
    return {"user_id": user.id, "email": user.email, "role": body.role}


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db, roles={"owner", "admin"})
    if user_id == ws.owner_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot remove the owner")
    m = db.query(Membership).filter_by(workspace_id=ws.id, user_id=user_id).first()
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not a member")
    db.delete(m)
    emit(db, "workspace.member.removed", ws_id=ws.id, user_id=user_id, actor=("user", ident.real_user.id))


@router.get("/{workspace_id}/events")
def workspace_events(workspace_id: str, after: str | None = None, limit: int = Query(200, le=1000),
                     type: str | None = None, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    """Replay from Postgres (source of truth). `after` is an event ULID.
    With `after`: the next `limit` events after it, ascending (gap replay).
    Without: the LATEST `limit` events, still returned ascending (initial hydration)."""
    ws = require_membership(workspace_id, ident, db)
    q = db.query(Event).filter(Event.ws_id == ws.id)
    if type:
        q = q.filter(Event.type.like(type.replace("*", "%")))
    if after:
        rows = q.filter(Event.id > after).order_by(Event.id.asc()).limit(limit).all()
    else:
        rows = list(reversed(q.order_by(Event.id.desc()).limit(limit).all()))
    return {"events": [to_dict(e) for e in rows]}
