"""Request identity. Every request resolves BOTH the real user and the effective user (impersonation)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from mainforte.auth.jwt import decode_session
from mainforte.db.base import utcnow
from mainforte.db.models import Membership, User, Workspace
from mainforte.db.session import get_db

LAST_ACTIVE_BUMP_INTERVAL = timedelta(minutes=5)


@dataclass
class Identity:
    user: User            # effective user (the one being impersonated, if any)
    real_user: User       # who is actually holding the session
    token_claims: dict

    @property
    def impersonating(self) -> bool:
        return self.real_user.id != self.user.id


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token")


def resolve_identity(token: str | None, db: Session) -> Identity | None:
    if not token:
        return None
    claims = decode_session(token)
    if not claims:
        return None
    real = db.get(User, claims["sub"])
    if not real or not real.is_active:
        return None  # deleted/disabled accounts cannot keep using a JWT

    now = utcnow()
    if not real.last_active_at or (now - real.last_active_at) > LAST_ACTIVE_BUMP_INTERVAL:
        real.last_active_at = now
        db.commit()

    eff = real
    if claims.get("act_as"):
        if not real.is_superuser:
            return None
        eff = db.get(User, claims["act_as"])
        if not eff:
            return None
    return Identity(user=eff, real_user=real, token_claims=claims)


def current_identity(request: Request, db: Session = Depends(get_db)) -> Identity:
    ident = resolve_identity(_bearer(request), db)
    if not ident:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    request.state.identity = ident
    return ident


def current_user(ident: Identity = Depends(current_identity)) -> User:
    return ident.user


def require_superuser(ident: Identity = Depends(current_identity)) -> Identity:
    # impersonated sessions never get admin powers, even if the target is a superuser
    if not ident.real_user.is_superuser or ident.impersonating:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superuser required")
    return ident


def require_membership(workspace_id: str, ident: Identity, db: Session, roles: set[str] | None = None) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    m = db.query(Membership).filter_by(workspace_id=workspace_id, user_id=ident.user.id).first()
    if not m and not (ident.real_user.is_superuser and not ident.impersonating):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not a member")
    if roles and m and m.role not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
    return ws
