"""Runs a registered event handler by name (at-least-once; handlers must be idempotent on event id)."""
from __future__ import annotations

import logging
from typing import Any

from mainforte.celery_app import celery
from mainforte.events import governor  # noqa: F401  (register governor handlers)
from mainforte.events import handlers  # noqa: F401  (register default handlers)
from mainforte.events import onboarding  # noqa: F401  (register onboarding handler)
from mainforte.events.registry import resolve

log = logging.getLogger(__name__)


@celery.task(name="mainforte.tasks.events.dispatch_handler", bind=True, max_retries=5,
             autoretry_for=(Exception,), retry_backoff=2, retry_backoff_max=120, retry_jitter=True,
             acks_late=True, reject_on_worker_lost=True)
def dispatch_handler(self, handler_name: str, event: dict[str, Any]) -> None:
    fn = resolve(handler_name)
    if fn is None:
        log.error("no handler registered as %s (event %s)", handler_name, event.get("id"))
        return
    fn(event)
