"""Billing reconcile (P3 Money). Hourly beat sweep fans out to a per-subscription task, mirroring
tasks/system.py's refresh_due_widgets/refresh_widget_task shape. Each per-subscription task re-pulls
the subscription from Stripe and calls sync_subscription_from_stripe — the same function the webhook
handler uses — so a missed webhook is corrected within the hour and the two paths can never race
into disagreement (idempotent convergence, last-write-wins by Stripe's own current data)."""
from __future__ import annotations

import logging

from mainforte.celery_app import celery
from mainforte.db.models import Subscription
from mainforte.db.session import db_session
from mainforte.events import emit

log = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("incomplete", "active", "past_due", "requires_action")


@celery.task(name="mainforte.tasks.billing.reconcile_subscriptions")
def reconcile_subscriptions() -> int:
    with db_session() as db:
        ids = [row[0] for row in db.query(Subscription.id)
               .filter(Subscription.status.in_(_ACTIVE_STATUSES)).all()]
    for sub_id in ids:
        reconcile_subscription_task.delay(subscription_id=sub_id)
    with db_session() as db:
        emit(db, "billing.reconcile.ran", actor=("system", None), payload={"count": len(ids)})
    return len(ids)


@celery.task(name="mainforte.tasks.billing.reconcile_subscription")
def reconcile_subscription_task(*, subscription_id: str) -> None:
    from mainforte.billing.service import sync_subscription_from_stripe

    with db_session() as db:
        sub = db.get(Subscription, subscription_id)
        if not sub:
            return
        try:
            sync_subscription_from_stripe(db, sub)
        except Exception:
            log.exception("reconcile failed for subscription %s", subscription_id)


@celery.task(name="mainforte.tasks.billing.reconcile_workspace")
def reconcile_workspace_task(*, ws_id: str) -> None:
    """Dispatched non-blocking on login (auth/routes.py _session_response) to reconcile a single
    workspace's subscriptions immediately rather than waiting for the next hourly sweep."""
    with db_session() as db:
        ids = [row[0] for row in db.query(Subscription.id)
               .filter(Subscription.ws_id == ws_id, Subscription.status.in_(_ACTIVE_STATUSES)).all()]
    for sub_id in ids:
        reconcile_subscription_task.delay(subscription_id=sub_id)
