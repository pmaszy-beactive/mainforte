"""Marketplace service layer (v1, conceptual demo — IDEA.md:103). Pure functions taking
`db: Session`, mirroring `billing/service.py`: resolve/mutate rows, `emit()`, return the row for
the route to shape into a response dict.

No reservation/concurrency handling here — a demo doesn't need it. `place_order` flips the listing
straight to `sold` on order creation, cash or escrow alike."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from mainforte.config import get_settings
from mainforte.db.models import Listing, Order
from mainforte.events import emit
from mainforte.marketplace import stripe_connect_stub

log = logging.getLogger(__name__)

# Never offered: weapons/firearms, drugs/paraphernalia (the cannabis legality question is exactly
# why it's simply absent rather than adjudicated per-jurisdiction), counterfeit/replica goods,
# adult services. Illustrative v1 list, not a legal compliance system.
CATEGORIES = {
    "general", "electronics", "furniture", "clothing", "kids_baby", "tools", "sports_outdoors",
    "books_media", "home_garden", "tickets_events", "services_lessons", "services_home",
    "services_other", "free",
}

REPORT_FLAG_THRESHOLD = 1  # demo visibility: first report flags it, but it still shows in browse


def create_listing(
    db: Session, *, seller_user_id: str, ws_id: str | None, kind: str, title: str, description: str,
    category: str, condition: str | None, price_cents: int, currency: str,
    location_label: str | None, lat: float | None, lng: float | None,
) -> Listing:
    listing = Listing(
        seller_user_id=seller_user_id, ws_id=ws_id, kind=kind, title=title, description=description,
        category=category, condition=condition, price_cents=price_cents, currency=currency,
        location_label=location_label, lat=lat, lng=lng, status="draft",
    )
    db.add(listing)
    db.flush()
    emit(db, "marketplace.listing.created", ws_id=ws_id, actor=("user", seller_user_id),
         payload={"listing_id": listing.id, "kind": kind, "category": category})
    return listing


def update_listing(db: Session, listing: Listing, *, actor_user_id: str, **fields) -> Listing:
    for key, value in fields.items():
        if value is not None and hasattr(listing, key):
            setattr(listing, key, value)
    db.add(listing)
    emit(db, "marketplace.listing.updated", ws_id=listing.ws_id, actor=("user", actor_user_id),
         payload={"listing_id": listing.id, "fields": sorted(fields.keys())})
    return listing


def publish_listing(db: Session, listing: Listing, *, actor_user_id: str) -> Listing:
    listing.status = "active"
    db.add(listing)
    emit(db, "marketplace.listing.published", ws_id=listing.ws_id, actor=("user", actor_user_id),
         payload={"listing_id": listing.id})
    return listing


def remove_listing(db: Session, listing: Listing, *, actor_user_id: str) -> Listing:
    listing.status = "removed"
    db.add(listing)
    emit(db, "marketplace.listing.removed", ws_id=listing.ws_id, actor=("user", actor_user_id),
         payload={"listing_id": listing.id})
    return listing


def report_listing(db: Session, listing: Listing, *, actor_user_id: str, reason: str | None) -> Listing:
    listing.report_count += 1
    if listing.report_count >= REPORT_FLAG_THRESHOLD:
        listing.flagged = True
    db.add(listing)
    emit(db, "marketplace.listing.reported", ws_id=listing.ws_id, actor=("user", actor_user_id),
         payload={"listing_id": listing.id, "reason": reason, "report_count": listing.report_count})
    return listing


def place_order(
    db: Session, listing: Listing, *, buyer_user_id: str, payment_method: str, notes: str | None,
) -> Order:
    settings = get_settings()
    amount_cents = listing.price_cents
    application_fee_cents = round(amount_cents * settings.marketplace_application_fee_percent / 100)

    order = Order(
        listing_id=listing.id, buyer_user_id=buyer_user_id, seller_user_id=listing.seller_user_id,
        amount_cents=amount_cents, application_fee_cents=application_fee_cents, currency=listing.currency,
        payment_method=payment_method, escrow_status="none", status="pending", notes=notes,
    )

    if payment_method == "stripe_escrow":
        db.add(order)
        db.flush()
        payment_intent_id = stripe_connect_stub.hold_funds(
            order_id=order.id, amount_cents=amount_cents, currency=listing.currency
        )
        order.stripe_payment_intent_id = payment_intent_id
        order.escrow_status = "held"
        db.add(order)
        emit(db, "marketplace.escrow.held", ws_id=listing.ws_id, actor=("user", buyer_user_id),
             payload={"order_id": order.id, "listing_id": listing.id, "payment_intent_id": payment_intent_id})
    else:
        db.add(order)
        db.flush()

    listing.status = "sold"
    db.add(listing)

    emit(db, "marketplace.order.placed", ws_id=listing.ws_id, actor=("user", buyer_user_id),
         payload={"order_id": order.id, "listing_id": listing.id, "payment_method": payment_method,
                   "amount_cents": amount_cents})
    emit(db, "marketplace.listing.sold", ws_id=listing.ws_id, actor=("user", buyer_user_id),
         payload={"listing_id": listing.id, "order_id": order.id})
    return order


def release_escrow(db: Session, order: Order, *, actor_user_id: str) -> Order:
    transfer_id = stripe_connect_stub.release_funds(
        order_id=order.id, payment_intent_id=order.stripe_payment_intent_id
    )
    order.stripe_transfer_id = transfer_id
    order.escrow_status = "released"
    order.status = "completed"
    db.add(order)
    emit(db, "marketplace.escrow.released", ws_id=None, actor=("user", actor_user_id),
         payload={"order_id": order.id, "transfer_id": transfer_id})
    return order


def refund_escrow(db: Session, order: Order, *, actor_user_id: str) -> Order:
    refund_id = stripe_connect_stub.refund_funds(
        order_id=order.id, payment_intent_id=order.stripe_payment_intent_id
    )
    order.escrow_status = "refunded"
    order.status = "canceled"
    db.add(order)
    emit(db, "marketplace.escrow.refunded", ws_id=None, actor=("user", actor_user_id),
         payload={"order_id": order.id, "refund_id": refund_id})
    return order


def dispute_order(db: Session, order: Order, *, actor_user_id: str, reason: str | None) -> Order:
    order.status = "disputed"
    if order.escrow_status == "held":
        order.escrow_status = "disputed"
    db.add(order)
    emit(db, "marketplace.order.disputed", ws_id=None, actor=("user", actor_user_id),
         payload={"order_id": order.id, "reason": reason})
    return order
