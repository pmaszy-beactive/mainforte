from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from mainforte.auth import google
from mainforte.auth.deps import Identity, current_identity, require_superuser
from mainforte.auth.jwt import mint_session
from mainforte.auth.passwords import hash_password, verify_password
from mainforte.auth.service import consume_token, create_user, issue_token, public_user
from mainforte.config import get_settings
from mainforte.db.base import utcnow
from mainforte.db.models import Membership, OAuthIdentity, User, Workspace
from mainforte.db.session import get_db
from mainforte.events import emit
from mainforte.events.stream import sync_redis
from mainforte.i18n import normalize_locale, valid_timezone
from mainforte.mail import send_magic_link, send_password_reset

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = ""
    locale: str | None = None
    timezone: str | None = None


class MeUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    locale: str | None = None
    timezone: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=200)


def _session_response(db: Session, user: User, *, method: str) -> dict:
    user.last_login_at = utcnow()
    emit(db, "session.login", user_id=user.id, actor=("user", user.id), payload={"method": method})
    return {"token": mint_session(user.id), "user": public_user(user)}


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    user = create_user(db, email=body.email, name=body.name, password=body.password,
                       locale=body.locale, timezone=body.timezone)
    return _session_response(db, user, method="password")


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email.lower()).first()
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    return _session_response(db, user, method="password")


@router.post("/logout", status_code=204)
def logout(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    emit(db, "session.logout", user_id=ident.user.id, actor=("user", ident.real_user.id))
    return Response(status_code=204)


@router.post("/magic-link", status_code=204)
def magic_link(body: EmailIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email.lower()).first()
    if not user:
        user = create_user(db, email=body.email)  # magic link doubles as signup
    raw = issue_token(db, user, "magic_link", timedelta(minutes=15))
    send_magic_link(user.email, f"{get_settings().frontend_url}/magic?token={raw}", locale=user.locale)
    return Response(status_code=204)


@router.post("/magic-link/verify")
def magic_verify(body: TokenIn, db: Session = Depends(get_db)):
    user = consume_token(db, body.token, "magic_link")
    user.email_verified_at = user.email_verified_at or utcnow()
    return _session_response(db, user, method="magic_link")


@router.post("/forgot-password", status_code=204)
def forgot_password(body: EmailIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email.lower()).first()
    if user:  # never reveal existence
        raw = issue_token(db, user, "password_reset", timedelta(hours=1))
        send_password_reset(user.email, f"{get_settings().frontend_url}/reset-password?token={raw}", locale=user.locale)
        emit(db, "user.password.reset_requested", user_id=user.id, actor=("user", user.id))
    return Response(status_code=204)


@router.post("/reset-password", status_code=204)
def reset_password(body: ResetIn, db: Session = Depends(get_db)):
    user = consume_token(db, body.token, "password_reset")
    user.password_hash = hash_password(body.password)
    emit(db, "user.password.reset", user_id=user.id, actor=("user", user.id))
    return Response(status_code=204)


# ---------------------------------------------------------------- google


@router.get("/google/start")
def google_start(request: Request):
    if not google.enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "google login not configured")
    state = secrets.token_urlsafe(24)
    sync_redis().setex(f"oauth:state:{state}", 600, request.query_params.get("next", "/app"))
    return RedirectResponse(google.authorization_url(state))


@router.get("/google/callback")
def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    r = sync_redis()
    nxt = r.getdel(f"oauth:state:{state}")
    if nxt is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad state")
    _token, info = google.exchange(code)
    sub, email = info.get("sub"), (info.get("email") or "").lower()
    if not sub or not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "google did not return an email")
    ident = db.query(OAuthIdentity).filter_by(provider="google", provider_sub=sub).first()
    if ident:
        user = db.get(User, ident.user_id)
    else:
        user = db.query(User).filter_by(email=email).first() or create_user(db, email=email, name=info.get("name", ""))
        db.add(OAuthIdentity(user_id=user.id, provider="google", provider_sub=sub, email=email, scopes=["openid", "email", "profile"]))
        if not user.avatar_url and info.get("picture"):
            user.avatar_url = info["picture"]
    user.email_verified_at = user.email_verified_at or utcnow()
    out = _session_response(db, user, method="google")
    return RedirectResponse(f"{get_settings().frontend_url}/oauth/callback#token={out['token']}&next={nxt}")


# ---------------------------------------------------------------- impersonation


@router.post("/impersonate/stop")
def impersonate_stop(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    if ident.impersonating:
        emit(db, "session.impersonation.ended", user_id=ident.user.id, actor=("user", ident.real_user.id))
    return {"token": mint_session(ident.real_user.id)}


@router.post("/impersonate/{user_id}")
def impersonate(user_id: str, ident: Identity = Depends(require_superuser), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if target.id == ident.real_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot impersonate yourself")
    emit(db, "session.impersonation.started", user_id=target.id, actor=("user", ident.real_user.id),
         payload={"by_email": ident.real_user.email, "target_email": target.email})
    return {"token": mint_session(ident.real_user.id, act_as=target.id)}


# ---------------------------------------------------------------- me

me_router = APIRouter(prefix="/api", tags=["me"])


@me_router.get("/me")
def me(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    rows = (db.query(Membership, Workspace).join(Workspace, Workspace.id == Membership.workspace_id)
            .filter(Membership.user_id == ident.user.id).all())
    return {
        "user": public_user(ident.user),
        "workspaces": [{"id": w.id, "name": w.name, "role": m.role, "plan": w.plan} for m, w in rows],
        "impersonating": ({"by_user_id": ident.real_user.id, "by_email": ident.real_user.email} if ident.impersonating else None),
    }


@me_router.patch("/me")
def update_me(body: MeUpdate, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    u = ident.user
    changed: dict = {}
    if body.name is not None and body.name != u.name:
        u.name = changed["name"] = body.name
    if body.locale is not None:
        loc = normalize_locale(body.locale)
        if loc != u.locale:
            u.locale = changed["locale"] = loc
    if body.timezone is not None and valid_timezone(body.timezone) and body.timezone != u.timezone:
        u.timezone = changed["timezone"] = body.timezone
    if changed:
        emit(db, "user.updated", user_id=u.id, actor=("user", ident.real_user.id), payload=changed)
    return public_user(u)
