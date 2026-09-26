"""Thin Stripe SDK wrapper (P3 Money). `plans`/`prices`/`coupons` are OUR rows, never Stripe
Dashboard objects — subscriptions are created with inline `price_data`/ad hoc `coupon`, so nothing
here ever references a Stripe product/price/coupon id."""
from __future__ import annotations

from typing import Any

import stripe

from mainforte.config import get_settings
from mainforte.db.models import Coupon, Price

_configured = False


def _client() -> Any:
    global _configured
    if not _configured:
        stripe.api_key = get_settings().stripe_secret_key
        _configured = True
    return stripe


def enabled() -> bool:
    return bool(get_settings().stripe_secret_key)


def create_customer(*, email: str, ws_id: str) -> str:
    c = _client().Customer.create(email=email, metadata={"ws_id": ws_id})
    return c.id


def create_setup_intent(*, customer_id: str) -> stripe.SetupIntent:
    return _client().SetupIntent.create(customer=customer_id, usage="off_session")


def get_setup_intent(setup_intent_id: str) -> stripe.SetupIntent:
    return _client().SetupIntent.retrieve(setup_intent_id)


def attach_payment_method(*, customer_id: str, payment_method_id: str) -> None:
    _client().PaymentMethod.attach(payment_method_id, customer=customer_id)
    _client().Customer.modify(customer_id, invoice_settings={"default_payment_method": payment_method_id})


def _coupon_kwargs(coupon: Coupon | None) -> dict[str, Any]:
    if coupon is None:
        return {}
    spec: dict[str, Any] = {"duration": coupon.duration}
    if coupon.kind == "percent":
        spec["percent_off"] = coupon.percent_off
    else:
        spec["amount_off"] = coupon.amount_off_cents
        spec["currency"] = coupon.currency
    if coupon.duration == "repeating":
        spec["duration_in_months"] = coupon.duration_in_months
    return {"coupon_data": spec}


def create_subscription(*, customer_id: str, price: Price, coupon: Coupon | None = None) -> stripe.Subscription:
    price_data = {
        "currency": price.currency,
        "unit_amount": price.amount_cents,
        "recurring": {"interval": price.interval},
        "product_data": {"name": f"Mainforte {price.plan.name}"},
    }
    return _client().Subscription.create(
        customer=customer_id,
        items=[{"price_data": price_data}],
        payment_behavior="default_incomplete",
        payment_settings={"save_default_payment_method": "on_subscription"},
        expand=["latest_invoice.payment_intent"],
        **_coupon_kwargs(coupon),
    )


def get_subscription(subscription_id: str) -> stripe.Subscription:
    return _client().Subscription.retrieve(subscription_id, expand=["latest_invoice.payment_intent"])


def cancel_subscription_at_period_end(subscription_id: str) -> stripe.Subscription:
    return _client().Subscription.modify(subscription_id, cancel_at_period_end=True)


def construct_event(*, payload: bytes, sig_header: str, webhook_secret: str) -> stripe.Event:
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
