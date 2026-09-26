"""Billing JSON routes (P3 Money): plan/subscription status, SetupIntent (save a card), subscribe,
cancel. Follows workspaces/routes.py's require_membership + Pydantic *In + emit()-after-mutation
pattern."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mainforte.auth.deps import Identity, current_identity, require_membership
from mainforte.billing import stripe_client
from mainforte.billing.service import (
    cancel_subscription,
    create_subscription_for_workspace,
    get_or_create_customer,
)
from mainforte.db.models import Coupon, Plan, Price, Subscription, User, Workspace
from mainforte.db.session import get_db
from mainforte.events import emit

router = APIRouter(prefix="/api/workspaces/{workspace_id}/billing", tags=["billing"])


class SubscribeIn(BaseModel):
    price_id: str = Field(min_length=1)
    coupon_code: str | None = None


def _plan_out(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "slug": plan.slug,
        "name": plan.name,
        "features": plan.features,
        "prices": [
            {"id": p.id, "amount_cents": p.amount_cents, "currency": p.currency, "interval": p.interval}
            for p in sorted(plan.prices, key=lambda p: p.amount_cents)
            if p.status == "active"
        ],
    }


def _sub_out(sub: Subscription | None) -> dict | None:
    if not sub:
        return None
    return {
        "id": sub.id,
        "plan_id": sub.plan_id,
        "status": sub.status,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "cancel_at_period_end": sub.cancel_at_period_end,
    }


@router.get("")
def get_billing(workspace_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    plans = db.query(Plan).filter(Plan.status == "active").order_by(Plan.sort_order).all()
    sub = (
        db.query(Subscription)
        .filter(Subscription.ws_id == ws.id, Subscription.status != "canceled")
        .order_by(Subscription.created_at.desc())
        .first()
    )
    return {
        "plans": [_plan_out(p) for p in plans],
        "subscription": _sub_out(sub),
        "has_card": bool(ws.stripe_payment_method_id),
    }


@router.post("/setup-intent", status_code=201)
def create_setup_intent(workspace_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db, roles={"owner", "admin"})
    owner = db.get(User, ws.owner_id)
    customer_id = get_or_create_customer(db, ws, owner)
    si = stripe_client.create_setup_intent(customer_id=customer_id)
    return {"client_secret": si["client_secret"]}


@router.post("/setup-intent/confirm", status_code=200)
def confirm_setup_intent(
    workspace_id: str, setup_intent_id: str,
    ident: Identity = Depends(current_identity), db: Session = Depends(get_db),
):
    ws = require_membership(workspace_id, ident, db, roles={"owner", "admin"})
    si = stripe_client.get_setup_intent(setup_intent_id)
    if si["status"] != "succeeded":
        raise HTTPException(status.HTTP_409_CONFLICT, f"setup_intent is {si['status']}, not succeeded")
    payment_method_id = si["payment_method"]
    stripe_client.attach_payment_method(customer_id=ws.stripe_customer_id, payment_method_id=payment_method_id)
    ws.stripe_payment_method_id = payment_method_id
    db.add(ws)
    emit(db, "billing.card.saved", ws_id=ws.id, actor=("user", ident.user.id), payload={})
    return {"ok": True}


@router.post("/subscribe", status_code=201)
def subscribe(
    workspace_id: str, body: SubscribeIn,
    ident: Identity = Depends(current_identity), db: Session = Depends(get_db),
):
    ws = require_membership(workspace_id, ident, db, roles={"owner", "admin"})
    if not ws.stripe_payment_method_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "save a card before subscribing")
    price = db.get(Price, body.price_id)
    if not price or price.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "price not found")
    coupon = None
    if body.coupon_code:
        coupon = db.query(Coupon).filter_by(code=body.coupon_code, status="active").first()
        if not coupon:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "coupon not found")
    owner = db.get(User, ws.owner_id)
    sub = create_subscription_for_workspace(db, ws, owner, price, coupon)
    return _sub_out(sub)


@router.post("/cancel", status_code=200)
def cancel(workspace_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db, roles={"owner", "admin"})
    sub = (
        db.query(Subscription)
        .filter(Subscription.ws_id == ws.id, Subscription.status.in_(("active", "past_due")))
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active subscription")
    sub = cancel_subscription(db, sub, ident.user.id)
    return _sub_out(sub)
