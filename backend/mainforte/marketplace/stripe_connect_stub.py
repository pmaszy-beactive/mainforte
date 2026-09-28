"""Stubbed Stripe Connect escrow. Deliberately fake in v1 -- Paul wants to think through the real
Connect integration before building it ("stub the stripe stuff i need to think about it").

Every function here is a no-op: no `stripe` import, no network call, ever -- regardless of what
STRIPE_SECRET_KEY (billing's subscription key) happens to be set to. Gated by
`settings.marketplace_stripe_connect_enabled`, which defaults to False and is not flipped on by
this pass. Functions return fake ids shaped like real Stripe object ids so the rest of the
order/escrow state machine (Order.stripe_payment_intent_id etc.) can be exercised end-to-end, and
so a later swap to the real integration doesn't need a schema change -- only these functions'
bodies change.
"""
from __future__ import annotations

import logging

from mainforte.config import get_settings
from mainforte.ids import new_id

log = logging.getLogger(__name__)


def enabled() -> bool:
    return get_settings().marketplace_stripe_connect_enabled


def create_connected_account_stub(*, seller_user_id: str) -> str:
    """Stands in for creating a Stripe Connect Express/Standard account for a seller. Never called
    for real in v1 -- present so the seller-onboarding step has somewhere to plug in later."""
    log.info("stripe_connect_stub: create_connected_account_stub seller=%s (no network call)", seller_user_id)
    return f"stub_acct_{new_id()}"


def hold_funds(*, order_id: str, amount_cents: int, currency: str) -> str:
    """Stands in for creating+capturing a PaymentIntent held for a connected account. Returns a
    fake payment_intent id; no charge is ever made."""
    log.info(
        "stripe_connect_stub: hold_funds order=%s amount_cents=%s currency=%s (no network call)",
        order_id, amount_cents, currency,
    )
    return f"stub_pi_{new_id()}"


def release_funds(*, order_id: str, payment_intent_id: str | None) -> str:
    """Stands in for transferring held funds to the seller's connected account. Returns a fake
    transfer id; no transfer is ever made."""
    log.info(
        "stripe_connect_stub: release_funds order=%s payment_intent=%s (no network call)",
        order_id, payment_intent_id,
    )
    return f"stub_tr_{new_id()}"


def refund_funds(*, order_id: str, payment_intent_id: str | None) -> str:
    """Stands in for refunding held funds to the buyer. Returns a fake refund id; no refund is
    ever made."""
    log.info(
        "stripe_connect_stub: refund_funds order=%s payment_intent=%s (no network call)",
        order_id, payment_intent_id,
    )
    return f"stub_rf_{new_id()}"
