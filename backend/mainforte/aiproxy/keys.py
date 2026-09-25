"""Resolve a workspace's ai-proxy key, minting one on first use if the proxy is configured.
If AI_PROXY_BASE_URL isn't set (e.g. local dev without proxy access), returns None and callers
fall back to a canned/echo reply so chat still works end-to-end."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from mainforte.aiproxy import client as aiproxy
from mainforte.crypto import decrypt, encrypt
from mainforte.db.models import Workspace

log = logging.getLogger(__name__)


def get_or_mint(db: Session, ws: Workspace) -> str | None:
    if ws.ai_proxy_key_enc:
        return decrypt(ws.ai_proxy_key_enc)
    if not aiproxy.enabled():
        return None
    try:
        minted = aiproxy.mint_workspace_key(ws_id=ws.id, ws_name=ws.name)
    except Exception:
        log.exception("could not mint ai-proxy key for workspace %s", ws.id)
        return None
    ws.ai_proxy_key_enc = encrypt(minted.key)
    db.add(ws)
    db.commit()
    return minted.key
