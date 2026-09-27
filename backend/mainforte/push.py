"""Push notifications via FCM HTTP v1 (covers Android directly and iOS through FCM's own APNs
bridge, so one integration covers both instead of standing up FCM + direct APNs separately).

FCM v1 needs an OAuth2 bearer token minted from the service account's RS256-signed JWT assertion
(https://developers.google.com/identity/protocols/oauth2/service-account) -- built with `jose`
(already a dependency for this app's own auth JWTs) rather than adding `google-auth` for one call.
The minted access token is cached in-process until shortly before it expires.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from jose import jwt as jose_jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mainforte.auth.deps import Identity, current_identity
from mainforte.config import get_settings
from mainforte.db.models import PushToken
from mainforte.db.session import get_db
from mainforte.events.registry import on

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/push", tags=["push"])

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

_cached_token: str | None = None
_cached_expiry: float = 0.0


def _mint_access_token() -> str | None:
    global _cached_token, _cached_expiry
    if _cached_token and time.time() < _cached_expiry - 60:
        return _cached_token
    raw = get_settings().fcm_service_account_json
    if not raw:
        return None
    creds = json.loads(raw)
    now = int(time.time())
    claims = {
        "iss": creds["client_email"],
        "scope": _SCOPE,
        "aud": _TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jose_jwt.encode(claims, creds["private_key"], algorithm="RS256")
    resp = httpx.post(
        _TOKEN_URL,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_token = data["access_token"]
    _cached_expiry = time.time() + data.get("expires_in", 3600)
    return _cached_token


def send_push(token: str, *, title: str, body: str, data: dict[str, Any] | None = None) -> bool:
    """Sends one FCM message; returns False (never raises) on any failure so a bad/stale device
    token can't take down the caller's event-handling flow."""
    settings = get_settings()
    if not settings.fcm_project_id:
        return False
    access_token = _mint_access_token()
    if not access_token:
        return False
    url = f"https://fcm.googleapis.com/v1/projects/{settings.fcm_project_id}/messages:send"
    message = {"message": {"token": token, "notification": {"title": title, "body": body}}}
    if data:
        message["message"]["data"] = {k: str(v) for k, v in data.items()}
    try:
        resp = httpx.post(
            url, json=message, headers={"Authorization": f"Bearer {access_token}"}, timeout=10,
        )
    except httpx.HTTPError:
        log.exception("fcm send failed")
        return False
    if resp.status_code >= 400:
        log.warning("fcm send rejected (%s): %s", resp.status_code, resp.text[:500])
        return False
    return True


def _push_to_user(db: Session, user_id: str, *, title: str, body: str, data: dict[str, Any] | None = None) -> None:
    tokens = db.query(PushToken).filter_by(user_id=user_id).all()
    for t in tokens:
        send_push(t.token, title=title, body=body, data=data)


class RegisterBody(BaseModel):
    platform: str
    token: str


@router.post("/register", status_code=204)
def register(body: RegisterBody, identity: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    row = db.query(PushToken).filter_by(user_id=identity.user.id, token=body.token).first()
    if row is None:
        db.add(PushToken(user_id=identity.user.id, platform=body.platform, token=body.token))
    else:
        row.platform = body.platform


def _push_for_task_event(event: dict[str, Any], *, title: str, body: str) -> None:
    from mainforte.db.session import db_session
    from mainforte.db.models import Workspace

    payload = event.get("payload") or {}
    task_id = payload.get("task_id")
    ws_id = event.get("ws_id")
    if not task_id or not ws_id:
        return
    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            return
        _push_to_user(db, ws.owner_id, title=title, body=body, data={"task_id": task_id, "type": event["type"]})


@on("task.blocked", queue="system")
def _on_task_blocked(event: dict[str, Any]) -> None:
    payload = event.get("payload") or {}
    _push_for_task_event(
        event,
        title="Your agent needs you",
        body=payload.get("reason") or "A task is waiting on your input.",
    )


@on("task.completed", queue="system")
def _on_task_completed(event: dict[str, Any]) -> None:
    _push_for_task_event(event, title="Task completed", body="Your agent finished a task.")
