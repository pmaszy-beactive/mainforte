from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from sqlalchemy import Numeric, func

from mainforte.auth import google
from mainforte.auth.deps import Identity, current_identity, require_membership, require_superuser
from mainforte.auth.jwt import mint_session
from mainforte.auth.passwords import hash_password, verify_password
from mainforte.auth.service import consume_token, create_user, issue_token, public_user
from mainforte.config import get_settings
from mainforte.crypto import encrypt
from mainforte.db.base import utcnow
from mainforte.db.models import Event, Membership, OAuthIdentity, User, Workspace
from mainforte.db.session import get_db
from mainforte.events import emit
from mainforte.events.onboarding import run_onboarding
from mainforte.events.stream import sync_redis
from mainforte.i18n import normalize_locale, valid_timezone
from mainforte.mail import send_magic_link, send_password_reset
from mainforte.workspaces.service import reset_workspace

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


class PrefsUpdate(BaseModel):
    interaction_style: str | None = Field(None, max_length=200)
    concierge_name: str | None = Field(None, max_length=80)


class WorkspaceResetIn(BaseModel):
    workspace_id: str | None = None


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
    db.commit()
    from mainforte.tasks.billing import reconcile_workspace_task

    ws_ids = [row[0] for row in db.query(Membership.workspace_id).filter_by(user_id=user.id).all()]
    for ws_id in ws_ids:
        reconcile_workspace_task.delay(ws_id=ws_id)
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


_GOOGLE_SCOPE_URIS = {
    "gmail.send": "https://www.googleapis.com/auth/gmail.send",
    "calendar": "https://www.googleapis.com/auth/calendar",
}
_CONNECT_CALLBACK_PATH = "/api/auth/google/connect-callback"


@router.get("/google/connect")
def google_connect(scopes: str, identity: Identity = Depends(current_identity)):
    """Incremental consent: an already-logged-in user escalates their existing Google identity to
    also grant additional scopes (gmail.send, calendar, ...), kept as a separate flow from
    /google/start because it has a different precondition (an existing session, not none) and a
    different post-action (persist tokens and return to settings, not mint a session).
    `scopes` is a comma-separated list of keys from `_GOOGLE_SCOPE_URIS`, e.g. "gmail.send,calendar"."""
    if not google.enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "google login not configured")
    keys = [s for s in scopes.split(",") if s]
    unknown = [s for s in keys if s not in _GOOGLE_SCOPE_URIS]
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown scope(s): {', '.join(unknown)}")
    scope = " ".join([google.BASE_SCOPES, *[_GOOGLE_SCOPE_URIS[k] for k in keys]])
    state = secrets.token_urlsafe(24)
    sync_redis().setex(f"oauth:google_connect:{state}", 600, f"{identity.user.id}:{scopes}")
    return RedirectResponse(google.authorization_url(state, scope=scope, offline=True,
                                                       callback_path=_CONNECT_CALLBACK_PATH))


@router.get("/google/connect-callback")
def google_connect_callback(code: str, state: str, db: Session = Depends(get_db)):
    raw = sync_redis().getdel(f"oauth:google_connect:{state}")
    if raw is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad state")
    user_id, scopes = raw.split(":", 1)
    keys = [s for s in scopes.split(",") if s]
    scope = " ".join([google.BASE_SCOPES, *[_GOOGLE_SCOPE_URIS[k] for k in keys]])
    token, info = google.exchange(code, scope=scope, callback_path=_CONNECT_CALLBACK_PATH)
    sub = info.get("sub")
    ident = db.query(OAuthIdentity).filter_by(provider="google", provider_sub=sub).first()
    if ident is None or ident.user_id != user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "identity mismatch")
    ident.access_token_enc = encrypt(token["access_token"])
    if token.get("refresh_token"):  # Google omits this on re-consent unless prompt=consent forced it
        ident.refresh_token_enc = encrypt(token["refresh_token"])
    ident.expires_at = utcnow() + timedelta(seconds=token.get("expires_in", 3600))
    ident.scopes = sorted(set(ident.scopes) | set(keys))
    return RedirectResponse(f"{get_settings().frontend_url}/settings?connected={scopes}")


# ---------------------------------------------------------------- connections


@router.get("/connections")
def list_connections(identity: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    rows = db.query(OAuthIdentity).filter_by(user_id=identity.user.id).all()
    return {"connections": [
        {
            "provider": r.provider,
            "email": r.email,
            "scopes": r.scopes,
            "connected_at": r.created_at.isoformat(),
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        }
        for r in rows
    ]}


@router.post("/connections/{provider}/disconnect", status_code=204)
def disconnect_connection(provider: str, identity: Identity = Depends(current_identity),
                           db: Session = Depends(get_db)):
    ident = db.query(OAuthIdentity).filter_by(user_id=identity.user.id, provider=provider).first()
    if ident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not connected")
    ident.access_token_enc = None
    ident.refresh_token_enc = None
    ident.expires_at = None
    ident.scopes = [s for s in ident.scopes if s in ("openid", "email", "profile")]
    emit(db, "user.connection.disconnected", user_id=identity.user.id, actor=("user", identity.user.id),
         payload={"provider": provider})
    return Response(status_code=204)


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


@me_router.get("/me/usage")
def my_usage(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws_ids = [row[0] for row in db.query(Membership.workspace_id).filter(Membership.user_id == ident.user.id).all()]
    if not ws_ids:
        return {"usage_by_workspace": [], "total_cost_usd": 0.0}

    cost_expr = func.sum(func.cast(Event.payload["cost_usd"].astext, Numeric))
    in_tok_expr = func.sum(func.cast(Event.payload["input_tokens"].astext, Numeric))
    out_tok_expr = func.sum(func.cast(Event.payload["output_tokens"].astext, Numeric))
    rows = (
        db.query(Event.ws_id, Workspace.name, in_tok_expr, out_tok_expr, cost_expr)
        .join(Workspace, Workspace.id == Event.ws_id)
        .filter(Event.type == "billing.usage.recorded", Event.ws_id.in_(ws_ids))
        .group_by(Event.ws_id, Workspace.name)
        .order_by(cost_expr.desc())
        .all()
    )
    usage_by_workspace = [
        {"ws_id": ws_id, "ws_name": ws_name, "input_tokens": int(in_tok or 0), "output_tokens": int(out_tok or 0),
         "cost_usd": float(cost or 0.0)}
        for ws_id, ws_name, in_tok, out_tok, cost in rows
    ]
    return {"usage_by_workspace": usage_by_workspace, "total_cost_usd": sum(r["cost_usd"] for r in usage_by_workspace)}


@me_router.post("/me/prefs")
def update_my_prefs(body: PrefsUpdate, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    u = ident.user
    changed: dict = {}
    if body.interaction_style is not None and body.interaction_style != u.prefs.get("interaction_style"):
        changed["interaction_style"] = body.interaction_style
    if body.concierge_name is not None and body.concierge_name != u.prefs.get("concierge_name"):
        changed["concierge_name"] = body.concierge_name
    if changed:
        u.prefs = {**u.prefs, **changed}
        emit(db, "user.prefs.updated", user_id=u.id, actor=("user", ident.real_user.id),
             payload={"updated_keys": list(changed.keys())})

        cname = changed.get("concierge_name")
        if cname:
            from mainforte.db.models import Persona
            from mainforte.personas.service import rename

            ws_ids = [row[0] for row in db.query(Membership.workspace_id).filter(Membership.user_id == u.id).all()]
            personas = (
                db.query(Persona)
                .filter(Persona.ws_id.in_(ws_ids), Persona.slug == "concierge", Persona.status == "active")
                .all()
                if ws_ids else []
            )
            for concierge in personas:
                if concierge.name != cname:
                    rename(db, persona=concierge, name=cname, actor=("user", ident.real_user.id))
    return {"prefs": u.prefs}


@me_router.post("/me/reset")
def reset_my_workspace(body: WorkspaceResetIn, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    workspace_id = body.workspace_id
    if not workspace_id:
        owned = (
            db.query(Membership.workspace_id)
            .filter(Membership.user_id == ident.user.id, Membership.role == "owner")
            .first()
        )
        if not owned:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no owned workspace to reset")
        workspace_id = owned[0]
    ws = require_membership(workspace_id, ident, db, roles={"owner"})
    reset_workspace(db, ws_id=ws.id, actor=("user", ident.real_user.id))
    db.commit()
    run_onboarding(ws.id, user_id=ident.user.id)
    return {"ok": True, "workspace_id": ws.id}
