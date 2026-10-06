"""CRUD for `Site` rows, plus the plain-language status shape every user-facing surface (API
responses, the persona's tool results) must use instead of raw `status`/`last_error`.

Mirrors `widgets.py`'s split between "service functions that touch DB/storage" and a route module
that wraps them — kept here as its own module rather than folded into `routes.py` since
`provisioning.py`'s callback handler and `tools/catalog.py`'s `create_site` tool handler both need
these functions without importing the route module (which pulls in FastAPI's `APIRouter`).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from mainforte.auth.passwords import new_token, token_hash
from mainforte.db.models import Site
from mainforte.ids import new_id

# Plain-language status shown to the (non-technical) end user. Keys are `Site.status` values;
# `Site.stage` (draft/published) is layered on top by `plain_status` below, never inferred from
# `status` alone — see the Site docstring for why these stay separate columns.
_STATUS_COPY = {
    "provisioning": "Setting things up",
    "building": "Working on your site",
    "ready": "Ready",
    "error": "Ran into a snag — retrying",
    "destroying": "Taking your site down",
}


def safe_slug(text: str) -> str:
    """Subdomain-safe slug: lowercase, hyphens, no leading/trailing/double hyphens, 63 chars max
    (DNS label limit — see Site.slug's docstring comment on models.py)."""
    import re

    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return (s or "site")[:63].strip("-") or "site"


def create_site(db: Session, *, ws_id: str, owner_id: str, name: str, brief: str,
                 slug: str | None = None, agent_thread_id: str | None = None) -> tuple[Site, str]:
    """Creates the `Site` row (status=provisioning, stage=draft) and a fresh container API key —
    the plaintext key is returned once, here, for the caller to hand to the just-triggered Jenkins
    job as a param; only its hash is ever persisted (same shape as `auth/passwords.py`'s token
    pattern). Caller commits and emits `site.created` in the same transaction, same convention as
    `widgets.create_widget`."""
    base = safe_slug(slug or name)
    candidate = base
    n = 2
    while db.query(Site).filter_by(ws_id=ws_id, slug=candidate).first() is not None:
        candidate = f"{base}-{n}"
        n += 1

    api_key = new_token()
    site = Site(
        id=new_id(), ws_id=ws_id, owner_id=owner_id, slug=candidate, name=name, brief=brief,
        status="provisioning", stage="draft", container_api_key_hash=token_hash(api_key),
        preview_token=new_id(), agent_thread_id=agent_thread_id,
    )
    db.add(site)
    db.flush()
    return site, api_key


def get_site(db: Session, site_id: str) -> Site | None:
    return db.get(Site, site_id)


def get_site_by_preview_token(db: Session, token: str) -> Site | None:
    return db.query(Site).filter_by(preview_token=token).first()


def list_sites(db: Session, ws_id: str) -> list[Site]:
    return db.query(Site).filter_by(ws_id=ws_id).order_by(Site.created_at.desc()).all()


def mark_ready(db: Session, site: Site, *, container_name: str, dev_port: int) -> None:
    site.status = "ready"
    site.container_name = container_name
    site.dev_port = dev_port
    site.last_error = None


def mark_error(db: Session, site: Site, *, error: str) -> None:
    """`error` is the raw technical detail — stored for admin/debug only. Never return this value
    from a user-facing route or tool result; see the Site model docstring and this module's
    docstring."""
    site.status = "error"
    site.last_error = error


def mark_published(db: Session, site: Site) -> None:
    from mainforte.db.base import utcnow

    site.stage = "published"
    site.published_at = utcnow()


def plain_status(site: Site) -> dict[str, Any]:
    """The only status shape a non-technical user (or the persona's chat reply) should ever read.
    Deliberately excludes `last_error`, `container_name`, `dev_port` — infra detail with no
    business here. `can_publish` folds "is the site actually healthy" into one boolean so the
    frontend's Publish button never has to reason about the `status` enum itself."""
    return {
        "status_label": _STATUS_COPY.get(site.status, "Working on it"),
        "stage": site.stage,
        "can_publish": site.status == "ready",
        "has_error": site.status == "error",
        "is_destroying": site.status == "destroying",
    }


def site_out(site: Site) -> dict[str, Any]:
    from mainforte.config import get_settings

    settings = get_settings()
    out: dict[str, Any] = {
        "id": site.id,
        "name": site.name,
        "slug": site.slug,
        "brief": site.brief,
        "created_at": site.created_at.isoformat(),
        "preview_url": f"{settings.api_url}/sites/preview/{site.preview_token}/",
    }
    out.update(plain_status(site))
    if site.stage == "published":
        out["published_url"] = f"https://{site.slug}.mainforte.ai/"
    return out
