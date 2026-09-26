"""Stripe webhook (P3 Money). Raw-body route, signature-verified, idempotent on `stripe_events.
stripe_event_id`. Dispatch restricted to exactly payment_intent.*, invoice.*, customer.subscription.*
per PLAN.md; invoice.* and customer.subscription.updated/deleted drive all real state transitions
through sync_subscription_from_stripe (the same function the reconcile job calls), payment_intent.*
is recorded for idempotency but never independently mutates state, avoiding double-writes."""
from __future__ import annotations

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from mainforte.billing import stripe_client
from mainforte.billing.service import sync_subscription_from_stripe
from mainforte.config import get_settings
from mainforte.db.models import StripeEvent, Subscription
from mainforte.db.session import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stripe", tags=["billing"])

_HANDLED_PREFIXES = ("payment_intent.", "invoice.", "customer.subscription.")


@router.post("/webhook", status_code=200)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "stripe webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.construct_event(
            payload=payload, sig_header=sig_header, webhook_secret=settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid signature")

    if not event["type"].startswith(_HANDLED_PREFIXES):
        return {"received": True, "handled": False}

    existing = db.query(StripeEvent).filter_by(stripe_event_id=event["id"]).first()
    if existing:
        return {"received": True, "handled": False, "duplicate": True}

    _dispatch(db, event)

    db.add(StripeEvent(stripe_event_id=event["id"], type=event["type"], payload=dict(event["data"]["object"])))
    db.commit()
    return {"received": True, "handled": True}


def _dispatch(db: Session, event: stripe.Event) -> None:
    obj = event["data"]["object"]
    if event["type"].startswith("customer.subscription.") or event["type"].startswith("invoice."):
        stripe_subscription_id = obj.get("subscription") if event["type"].startswith("invoice.") else obj.get("id")
        if not stripe_subscription_id:
            return
        sub = db.query(Subscription).filter_by(stripe_subscription_id=stripe_subscription_id).first()
        if not sub:
            log.warning("webhook %s for unknown subscription %s", event["type"], stripe_subscription_id)
            return
        stripe_sub = stripe_client.get_subscription(stripe_subscription_id)
        sync_subscription_from_stripe(db, sub, stripe_sub)
