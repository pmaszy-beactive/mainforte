"""REST API for Sites. Mirrors widgets.py's route shape (require_membership, emit-in-route), split
into its own module since this package also has provisioning.py/container_agent.py/service.py
that routes.py itself depends on (see sites/__init__.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mainforte.auth.deps import Identity, current_identity, require_membership
from mainforte.auth.passwords import token_hash
from mainforte.db.session import get_db
from mainforte.events import emit
from mainforte.sites import service as site_service
from mainforte.sites.provisioning import handle_callback, trigger_provision

router = APIRouter(tags=["sites"])


class CreateSiteBody(BaseModel):
    name: str
    brief: str
    slug: str | None = None


@router.post("/api/workspaces/{workspace_id}/sites", status_code=status.HTTP_201_CREATED)
def create_site(workspace_id: str, body: CreateSiteBody, ident: Identity = Depends(current_identity),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    require_membership(workspace_id, ident, db)
    site, api_key = site_service.create_site(
        db, ws_id=workspace_id, owner_id=ident.user.id, name=body.name, brief=body.brief, slug=body.slug,
    )
    emit(db, "site.created", ws_id=workspace_id, actor=("user", ident.user.id), correlation_id=None,
         payload={"site_id": site.id, "name": body.name, "slug": site.slug})
    db.commit()
    trigger_provision(db, site=site, api_key=api_key)
    db.commit()
    return site_service.site_out(site)


@router.get("/api/workspaces/{workspace_id}/sites")
def list_sites(workspace_id: str, ident: Identity = Depends(current_identity),
                db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    require_membership(workspace_id, ident, db)
    return [site_service.site_out(s) for s in site_service.list_sites(db, workspace_id)]


@router.get("/api/sites/{site_id}")
def get_site(site_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)) -> dict[str, Any]:
    site = site_service.get_site(db, site_id)
    if not site:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "site not found")
    require_membership(site.ws_id, ident, db)
    return site_service.site_out(site)


@router.post("/api/sites/{site_id}/publish")
def publish_site(site_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)) -> dict[str, Any]:
    site = site_service.get_site(db, site_id)
    if not site:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "site not found")
    require_membership(site.ws_id, ident, db)
    if site.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "site isn't ready to publish yet")
    site_service.mark_published(db, site)
    emit(db, "site.published", ws_id=site.ws_id, actor=("user", ident.user.id), correlation_id=None,
         payload={"site_id": site.id, "slug": site.slug})
    db.commit()
    return site_service.site_out(site)


class CallbackBody(BaseModel):
    event: str
    line: str | None = None
    container_name: str | None = None
    dev_port: int | None = None
    message: str | None = None


@router.post("/api/sites/{site_id}/callback")
def site_callback(site_id: str, body: CallbackBody, db: Session = Depends(get_db),
                    authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Called by the Jenkins provision job (both its own pipeline step and, indirectly, the
    template's `lib/callback.ts` startup ping relayed by the job — see the plan's "Site starter
    template fork" section) — not a logged-in user. Authenticated by the site's own container API
    key: the job receives CONTAINER_API_KEY as a param (see provisioning.trigger_provision) and
    must send it back as `Authorization: Bearer <key>`, verified here against
    container_api_key_hash the same way auth/deps.py verifies session tokens (token_hash, constant
    -time-ish via hash comparison rather than a raw string compare)."""
    site = site_service.get_site(db, site_id)
    if not site:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "site not found")
    presented = (authorization or "").removeprefix("Bearer ").strip()
    if not presented or not site.container_api_key_hash or token_hash(presented) != site.container_api_key_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing callback credential")
    handle_callback(db, site, body.model_dump())
    db.commit()
    return {"ok": True}


@router.get("/sites/preview/{token}/{path:path}")
def preview_site(token: str, path: str, db: Session = Depends(get_db)):
    """Proxies to the site container's dev port — unauthenticated beyond the capability token
    itself, same trust model as widgets.py's serve_widget. Actual proxying (HAProxy vs. a thin
    FastAPI httpx passthrough) is TBD at the point a real Jenkins job exists to test against; this
    stub establishes the URL shape site_out() already promises callers."""
    site = site_service.get_site_by_preview_token(db, token)
    if not site or site.status != "ready":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "preview not available")
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "preview proxy not wired yet")
