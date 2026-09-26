"""Billing service layer (P3 Money). `sync_subscription_from_stripe` is the single shared choke
point both the webhook handler and the hourly reconcile job call, so re-application is idempotent
and the two paths can never race into disagreement — last-write-wins by Stripe's own current data."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from mainforte.billing import stripe_client
from mainforte.db.models import Coupon, Plan, Price, Subscription, User, Workspace
from mainforte.events import emit

log = logging.getLogger(__name__)

_STATUS_MAP = {
    "incomplete": "incomplete",
    "incomplete_expired": "canceled",
    "trialing": "active",
    "active": "active",
    "past_due": "past_due",
    "canceled": "canceled",
    "unpaid": "unpaid",
    "paused": "past_due",
}


def get_or_create_customer(db: Session, ws: Workspace, owner: User) -> str:
    if ws.stripe_customer_id:
        return ws.stripe_customer_id
    customer_id = stripe_client.create_customer(email=owner.email, ws_id=ws.id)
    ws.stripe_customer_id = customer_id
    db.add(ws)
    return customer_id


def _effective_status(stripe_sub: Any) -> str:
    raw = stripe_sub["status"]
    status = _STATUS_MAP.get(raw, raw)
    if status == "incomplete":
        pi = stripe_sub.get("latest_invoice", {}).get("payment_intent") if stripe_sub.get("latest_invoice") else None
        if pi and pi.get("status") == "requires_action":
            return "requires_action"
    return status


def create_subscription_for_workspace(
    db: Session, ws: Workspace, owner: User, price: Price, coupon: Coupon | None = None
) -> Subscription:
    customer_id = get_or_create_customer(db, ws, owner)
    stripe_sub = stripe_client.create_subscription(customer_id=customer_id, price=price, coupon=coupon)
    sub = Subscription(
        ws_id=ws.id,
        plan_id=price.plan_id,
        price_id=price.id,
        coupon_id=coupon.id if coupon else None,
        stripe_subscription_id=stripe_sub["id"],
        stripe_customer_id=customer_id,
        status=_effective_status(stripe_sub),
        current_period_end=None,
        latest_invoice_id=stripe_sub["latest_invoice"]["id"] if stripe_sub.get("latest_invoice") else None,
    )
    db.add(sub)
    db.flush()
    emit(db, "billing.subscription.created", ws_id=ws.id, actor=("user", owner.id),
         payload={"subscription_id": sub.id, "plan_id": price.plan_id, "status": sub.status})
    return sub


def sync_subscription_from_stripe(db: Session, sub: Subscription, stripe_sub: Any | None = None) -> Subscription:
    """Idempotent convergence: pulls (or accepts) the current Stripe subscription state and writes
    it onto our row + the workspace's denormalized plan cache. Safe to call from the webhook handler
    or the reconcile task with the same result either way."""
    if stripe_sub is None:
        stripe_sub = stripe_client.get_subscription(sub.stripe_subscription_id)

    old_status = sub.status
    new_status = _effective_status(stripe_sub)
    sub.status = new_status
    sub.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end", False))
    period_end = stripe_sub.get("current_period_end")
    sub.current_period_end = _from_unix(period_end) if period_end else sub.current_period_end
    if stripe_sub.get("latest_invoice"):
        sub.latest_invoice_id = stripe_sub["latest_invoice"]["id"]
    db.add(sub)

    ws = db.get(Workspace, sub.ws_id)
    if ws is not None:
        plan = db.get(Plan, sub.plan_id)
        new_plan_slug = plan.slug if (plan and new_status in {"active", "past_due"}) else ws.plan
        if new_plan_slug != ws.plan:
            ws.plan = new_plan_slug
            db.add(ws)
            emit(db, "workspace.plan.changed", ws_id=ws.id, actor=("system", None),
                 payload={"plan": new_plan_slug, "subscription_id": sub.id})

    if new_status != old_status:
        event_type = {
            "active": "billing.subscription.renewed",
            "past_due": "billing.subscription.past_due",
            "canceled": "billing.subscription.canceled",
        }.get(new_status)
        if event_type:
            emit(db, event_type, ws_id=sub.ws_id, actor=("system", None),
                 payload={"subscription_id": sub.id, "status": new_status})

    return sub


def cancel_subscription(db: Session, sub: Subscription, actor_user_id: str) -> Subscription:
    stripe_sub = stripe_client.cancel_subscription_at_period_end(sub.stripe_subscription_id)
    sub.cancel_at_period_end = True
    db.add(sub)
    emit(db, "billing.subscription.canceled", ws_id=sub.ws_id, actor=("user", actor_user_id),
         payload={"subscription_id": sub.id, "at_period_end": True})
    return sub


def _from_unix(ts: int) -> Any:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc)
