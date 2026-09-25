from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from mainforte.auth.passwords import hash_password, new_token, token_hash
from mainforte.config import get_settings
from mainforte.db.base import utcnow
from mainforte.db.models import AuthToken, Membership, User, Workspace
from mainforte.events import emit


def role_for(email: str) -> str:
    return "superuser" if email.lower() in get_settings().superuser_emails else "user"


def create_user(db: Session, *, email: str, name: str = "", password: str | None = None,
                locale: str | None = None, timezone: str | None = None,
                actor: tuple[str, str | None] = ("system", None)) -> User:
    from mainforte.i18n import normalize_locale, valid_timezone

    email = email.strip().lower()
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = User(email=email, name=name or email.split("@")[0], role=role_for(email),
                password_hash=hash_password(password) if password else None,
                locale=normalize_locale(locale), timezone=timezone if timezone and valid_timezone(timezone) else "America/New_York")
    db.add(user)
    db.flush()
    ws = Workspace(name=f"{user.name}'s home", owner_id=user.id)
    db.add(ws)
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
    db.flush()
    from mainforte.personas.service import seed_defaults

    seed_defaults(db, ws_id=ws.id, actor=("system", None))
    emit(db, "user.created", user_id=user.id, actor=actor, payload={"email": user.email, "role": user.role})
    emit(db, "workspace.created", ws_id=ws.id, user_id=user.id, actor=("user", user.id), payload={"name": ws.name})
    return user


def issue_token(db: Session, user: User, kind: str, ttl: timedelta) -> str:
    raw = new_token()
    db.add(AuthToken(user_id=user.id, kind=kind, token_hash=token_hash(raw), expires_at=utcnow() + ttl))
    db.flush()
    return raw


def consume_token(db: Session, raw: str, kind: str) -> User:
    t = db.query(AuthToken).filter_by(token_hash=token_hash(raw), kind=kind).first()
    if not t or t.used_at or t.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")
    t.used_at = utcnow()
    user = db.get(User, t.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid token")
    return user


def public_user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "avatar_url": u.avatar_url,
            "locale": u.locale, "timezone": u.timezone}
