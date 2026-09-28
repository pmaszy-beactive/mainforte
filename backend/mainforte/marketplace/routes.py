"""Marketplace JSON routes (v1, conceptual demo -- IDEA.md:103). Global, per-user scope: NOT
workspace-nested like the rest of the app. Every route depends on `current_identity`; ownership is
checked inline (`listing.seller_user_id == ident.user.id`, `order.{buyer,seller}_user_id`) instead
of `require_membership`, since there is no workspace to check membership against."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mainforte.aiproxy import client as aiproxy
from mainforte.aiproxy.keys import get_or_mint
from mainforte.auth.deps import Identity, current_identity
from mainforte.db.models import Listing, ListingPhoto, Membership, Order, Upload
from mainforte.db.session import get_db
from mainforte.marketplace import search as search_mod
from mainforte.marketplace.service import (
    CATEGORIES,
    create_listing,
    dispute_order,
    place_order,
    publish_listing,
    refund_escrow,
    release_escrow,
    remove_listing,
    report_listing,
    update_listing,
)

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])

DISCLAIMER = "No illegal, stolen, or hazardous items. Sellers are responsible for complying with local law."


# ---------------------------------------------------------------------------------------- schemas

class ListingIn(BaseModel):
    kind: str = Field(pattern="^(good|service)$")
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str
    condition: str | None = None
    price_cents: int = Field(ge=0)
    currency: str = "usd"
    location_label: str | None = None
    lat: float | None = None
    lng: float | None = None
    ws_id: str | None = None


class ListingUpdateIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    condition: str | None = None
    price_cents: int | None = Field(None, ge=0)
    currency: str | None = None
    location_label: str | None = None
    lat: float | None = None
    lng: float | None = None
    photo_upload_ids: list[str] | None = None


class OrderIn(BaseModel):
    payment_method: str = Field(pattern="^(cash|stripe_escrow)$")
    notes: str | None = None


class ReportIn(BaseModel):
    reason: str | None = None


class SearchIn(BaseModel):
    query: str | None = None
    category: str | None = None
    min_price_cents: int | None = None
    max_price_cents: int | None = None
    kind: str | None = None
    lat: float | None = None
    lng: float | None = None
    radius_km: float | None = None


def _validate_category(category: str) -> None:
    if category not in CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown category (allowed: {sorted(CATEGORIES)})")


# ------------------------------------------------------------------------------------------ shape

def _listing_out(listing: Listing) -> dict:
    return {
        "id": listing.id,
        "seller_user_id": listing.seller_user_id,
        "kind": listing.kind,
        "title": listing.title,
        "description": listing.description,
        "category": listing.category,
        "condition": listing.condition,
        "price_cents": listing.price_cents,
        "currency": listing.currency,
        "location_label": listing.location_label,
        "lat": listing.lat,
        "lng": listing.lng,
        "status": listing.status,
        "flagged": listing.flagged,
        "report_count": listing.report_count,
        "photos": [
            {"id": p.id, "upload_id": p.upload_id, "sort_order": p.sort_order}
            for p in sorted(listing.photos, key=lambda p: p.sort_order)
        ],
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }


def _order_out(order: Order) -> dict:
    return {
        "id": order.id,
        "listing_id": order.listing_id,
        "buyer_user_id": order.buyer_user_id,
        "seller_user_id": order.seller_user_id,
        "amount_cents": order.amount_cents,
        "application_fee_cents": order.application_fee_cents,
        "currency": order.currency,
        "payment_method": order.payment_method,
        "escrow_status": order.escrow_status,
        "status": order.status,
        "notes": order.notes,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }


def _get_owned_listing(db: Session, listing_id: str, ident: Identity) -> Listing:
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "listing not found")
    if listing.seller_user_id != ident.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your listing")
    return listing


def _get_order_for_party(db: Session, order_id: str, ident: Identity) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    if ident.user.id not in (order.buyer_user_id, order.seller_user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your order")
    return order


# ---------------------------------------------------------------------------------------- browse

@router.get("/listings")
def list_listings(
    kind: str | None = None, category: str | None = None,
    min_price_cents: int | None = None, max_price_cents: int | None = None, q: str | None = None,
    lat: float | None = None, lng: float | None = None, radius_km: float | None = None,
    limit: int = Query(30, le=100),
    db: Session = Depends(get_db), ident: Identity = Depends(current_identity),
):
    rows = search_mod.fts_search(
        db, query=q, category=category, min_price_cents=min_price_cents,
        max_price_cents=max_price_cents, kind=kind, limit=limit,
    )
    if lat is not None and lng is not None and radius_km is not None:
        rows = search_mod.radius_filter(rows, lat=lat, lng=lng, radius_km=radius_km)
    return {"listings": rows}


@router.post("/search")
async def ai_search(
    body: SearchIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity),
):
    """AI-assisted search: one aiproxy call parses `body.query` into structured filters, then falls
    through to the same FTS as `GET /listings`. Falls back to plain keyword FTS -- no AI step -- if
    ai-proxy is disabled, the user has no workspace with a usable key, or the parse fails."""
    category, min_price, max_price, kind, keywords = (
        body.category, body.min_price_cents, body.max_price_cents, body.kind, body.query,
    )
    if body.query and aiproxy.enabled():
        membership = db.query(Membership).filter_by(user_id=ident.user.id).first()
        api_key = get_or_mint(db, membership.workspace) if membership else None
        if api_key:
            parsed = await search_mod.ai_parse_query(api_key=api_key, query=body.query)
            if parsed:
                keywords = parsed.get("keywords") or body.query
                category = category or parsed.get("category")
                min_price = min_price if min_price is not None else parsed.get("min_price_cents")
                max_price = max_price if max_price is not None else parsed.get("max_price_cents")
                kind = kind or parsed.get("kind")

    rows = search_mod.fts_search(
        db, query=keywords, category=category, min_price_cents=min_price,
        max_price_cents=max_price, kind=kind, limit=30,
    )
    if body.lat is not None and body.lng is not None and body.radius_km is not None:
        rows = search_mod.radius_filter(rows, lat=body.lat, lng=body.lng, radius_km=body.radius_km)
    return {"listings": rows}


@router.get("/listings/{listing_id}")
def get_listing(listing_id: str, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "listing not found")
    return _listing_out(listing)


@router.get("/mine")
def my_listings(db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    rows = (
        db.query(Listing)
        .filter(Listing.seller_user_id == ident.user.id)
        .order_by(Listing.created_at.desc())
        .all()
    )
    return {"listings": [_listing_out(l) for l in rows]}


# --------------------------------------------------------------------------------------- listing

@router.post("/listings", status_code=201)
def create(body: ListingIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    _validate_category(body.category)
    listing = create_listing(
        db, seller_user_id=ident.user.id, ws_id=body.ws_id, kind=body.kind, title=body.title,
        description=body.description, category=body.category, condition=body.condition,
        price_cents=body.price_cents, currency=body.currency, location_label=body.location_label,
        lat=body.lat, lng=body.lng,
    )
    return _listing_out(listing)


@router.patch("/listings/{listing_id}")
def update(
    listing_id: str, body: ListingUpdateIn,
    db: Session = Depends(get_db), ident: Identity = Depends(current_identity),
):
    listing = _get_owned_listing(db, listing_id, ident)
    if body.category is not None:
        _validate_category(body.category)
    fields = body.model_dump(exclude={"photo_upload_ids"}, exclude_unset=True)
    listing = update_listing(db, listing, actor_user_id=ident.user.id, **fields)

    if body.photo_upload_ids is not None:
        existing = {p.upload_id: p for p in listing.photos}
        for sort_order, upload_id in enumerate(body.photo_upload_ids):
            if upload_id in existing:
                existing[upload_id].sort_order = sort_order
                continue
            upload = db.get(Upload, upload_id)
            if not upload:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"upload {upload_id} not found")
            db.add(ListingPhoto(listing_id=listing.id, upload_id=upload_id, sort_order=sort_order))
        for upload_id, photo in existing.items():
            if upload_id not in body.photo_upload_ids:
                db.delete(photo)
        db.flush()
        db.refresh(listing)

    return _listing_out(listing)


@router.post("/listings/{listing_id}/publish")
def publish(listing_id: str, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    listing = _get_owned_listing(db, listing_id, ident)
    listing = publish_listing(db, listing, actor_user_id=ident.user.id)
    return _listing_out(listing)


@router.post("/listings/{listing_id}/remove")
def remove(listing_id: str, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    listing = _get_owned_listing(db, listing_id, ident)
    listing = remove_listing(db, listing, actor_user_id=ident.user.id)
    return _listing_out(listing)


@router.post("/listings/{listing_id}/report")
def report(
    listing_id: str, body: ReportIn,
    db: Session = Depends(get_db), ident: Identity = Depends(current_identity),
):
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "listing not found")
    listing = report_listing(db, listing, actor_user_id=ident.user.id, reason=body.reason)
    return _listing_out(listing)


# ----------------------------------------------------------------------------------------- order

@router.post("/listings/{listing_id}/orders", status_code=201)
def place(
    listing_id: str, body: OrderIn,
    db: Session = Depends(get_db), ident: Identity = Depends(current_identity),
):
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "listing not found")
    if listing.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, f"listing is {listing.status}, not active")
    if listing.seller_user_id == ident.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot buy your own listing")
    order = place_order(
        db, listing, buyer_user_id=ident.user.id, payment_method=body.payment_method, notes=body.notes,
    )
    return _order_out(order)


@router.get("/orders/mine")
def my_orders(db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    rows = (
        db.query(Order)
        .filter((Order.buyer_user_id == ident.user.id) | (Order.seller_user_id == ident.user.id))
        .order_by(Order.created_at.desc())
        .all()
    )
    return {"orders": [_order_out(o) for o in rows]}


@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    order = _get_order_for_party(db, order_id, ident)
    return _order_out(order)


@router.post("/orders/{order_id}/escrow/release")
def escrow_release(order_id: str, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    order = _get_order_for_party(db, order_id, ident)
    if order.payment_method != "stripe_escrow" or order.escrow_status != "held":
        raise HTTPException(status.HTTP_409_CONFLICT, f"nothing to release (escrow_status={order.escrow_status})")
    order = release_escrow(db, order, actor_user_id=ident.user.id)
    return _order_out(order)


@router.post("/orders/{order_id}/escrow/refund")
def escrow_refund(order_id: str, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    order = _get_order_for_party(db, order_id, ident)
    if order.payment_method != "stripe_escrow" or order.escrow_status != "held":
        raise HTTPException(status.HTTP_409_CONFLICT, f"nothing to refund (escrow_status={order.escrow_status})")
    order = refund_escrow(db, order, actor_user_id=ident.user.id)
    return _order_out(order)


@router.post("/orders/{order_id}/dispute")
def dispute(
    order_id: str, body: ReportIn,
    db: Session = Depends(get_db), ident: Identity = Depends(current_identity),
):
    order = _get_order_for_party(db, order_id, ident)
    order = dispute_order(db, order, actor_user_id=ident.user.id, reason=body.reason)
    return _order_out(order)
