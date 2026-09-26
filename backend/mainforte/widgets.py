"""Widgets (P2 phase 7, PLAN.md §1.7): a small HTML+data bundle a persona publishes, served
unauthenticated at /w/{token}/ and optionally kept fresh by a periodic refresh job.

Layout, mirroring homes.py's storage-key conventions:

    users/<owner_id>/widgets/<slug>/<version>/index.html
    users/<owner_id>/widgets/<slug>/<version>/data.json

A refresh bumps `version` and rewrites only `data.json` under the new version; `index.html` is
copied forward unchanged (the template doesn't change on a data refresh, only the data it reads).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from mainforte.auth.deps import Identity, current_identity
from mainforte.db.session import get_db
from mainforte.storage import get_storage, widget_key


def create_widget(db: Any, *, ws_id: str, owner_id: str, title: str, slug: str, html: str,
                   data: dict[str, Any], refresh_spec: dict[str, Any] | None = None) -> Any:
    """Creates the Widget row (version 1) and uploads its bundle. Caller is responsible for
    emitting `widget.created` inside the same transaction (see tools/catalog.py's `create_widget`
    handler) — this function only touches storage and the row."""
    from mainforte.db.models import Widget
    from mainforte.ids import new_id

    widget = Widget(
        id=new_id(), ws_id=ws_id, owner_id=owner_id, slug=slug, title=title, version=1,
        status="active", refresh_spec=refresh_spec, token=new_id(),
    )
    db.add(widget)
    db.flush()

    storage = get_storage()
    storage.put(widget_key(owner_id, slug, widget.version, "index.html"), html.encode(), "text/html")
    storage.put(widget_key(owner_id, slug, widget.version, "data.json"),
                json.dumps(data).encode(), "application/json")
    return widget


def refresh_widget(widget: Any, data: dict[str, Any]) -> None:
    """Bumps `widget.version` and rewrites `data.json` under the new version; copies `index.html`
    forward unchanged. Caller commits the row and emits `widget.updated`."""
    storage = get_storage()
    prev_html = storage.get(widget_key(widget.owner_id, widget.slug, widget.version, "index.html"))
    if prev_html is None:
        raise RuntimeError(f"widget {widget.id} has no index.html at version {widget.version}")

    widget.version += 1
    storage.put(widget_key(widget.owner_id, widget.slug, widget.version, "index.html"), prev_html, "text/html")
    storage.put(widget_key(widget.owner_id, widget.slug, widget.version, "data.json"),
                json.dumps(data).encode(), "application/json")


def get_widget_bundle(widget: Any) -> tuple[str, dict[str, Any]]:
    """Reads back the current (html, data) bundle for a widget at its current version."""
    storage = get_storage()
    html_bytes = storage.get(widget_key(widget.owner_id, widget.slug, widget.version, "index.html"))
    data_bytes = storage.get(widget_key(widget.owner_id, widget.slug, widget.version, "data.json"))
    if html_bytes is None or data_bytes is None:
        raise RuntimeError(f"widget {widget.id} bundle missing at version {widget.version}")
    return html_bytes.decode(), json.loads(data_bytes)


# ---------------------------------------------------------------- routes

router = APIRouter(tags=["widgets"])


def _widget_out(w: Any) -> dict[str, Any]:
    from mainforte.config import get_settings
    return {"id": w.id, "title": w.title, "slug": w.slug, "version": w.version, "status": w.status,
            "token": w.token, "url": f"{get_settings().api_url}/w/{w.token}/"}


@router.get("/api/workspaces/{workspace_id}/widgets")
def list_widgets(workspace_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    from mainforte.auth.deps import require_membership
    from mainforte.db.models import Widget

    require_membership(workspace_id, ident, db)
    rows = db.query(Widget).filter_by(ws_id=workspace_id).order_by(Widget.created_at.desc()).all()
    return [_widget_out(w) for w in rows]


@router.get("/w/{token}/{path:path}")
def serve_widget(token: str, path: str, db: Session = Depends(get_db)):
    from mainforte.db.models import Widget
    from mainforte.events import emit

    widget = db.query(Widget).filter_by(token=token, status="active").first()
    if not widget:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "widget not found")

    filename = path or "index.html"
    if filename not in ("index.html", "data.json"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    storage = get_storage()
    data = storage.get(widget_key(widget.owner_id, widget.slug, widget.version, filename))
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    if filename == "index.html":
        emit(db, "widget.viewed", ws_id=widget.ws_id, actor=("system", None), correlation_id=None,
             payload={"widget_id": widget.id})
        db.commit()

    media_type = "text/html" if filename == "index.html" else "application/json"
    return Response(content=data, media_type=media_type)
