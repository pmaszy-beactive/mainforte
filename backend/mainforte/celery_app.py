from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from mainforte.config import get_settings

s = get_settings()

celery = Celery("mainforte", broker=s.celery_broker_url, backend=s.celery_result_backend or s.redis_url)
celery.conf.update(
    task_queues=(Queue("chat"), Queue("work"), Queue("system")),
    task_default_queue="system",
    task_acks_late=True,                 # a job survives its worker dying: it is redelivered
    task_reject_on_worker_lost=True,     # ... including SIGKILL / OOM / node down
    worker_prefetch_multiplier=1,        # no hoarding: a dead worker strands at most one job per process
    worker_cancel_long_running_tasks_on_connection_loss=True,
    broker_transport_options={"confirm_publish": True},
    task_publish_retry=True,
    task_publish_retry_policy={"max_retries": 5, "interval_start": 0.2, "interval_step": 0.5, "interval_max": 5},
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_routes={
        "mainforte.tasks.chat.*": {"queue": "chat"},
        "mainforte.tasks.work.*": {"queue": "work"},
        "mainforte.tasks.system.*": {"queue": "system"},
        "mainforte.tasks.billing.*": {"queue": "system"},
    },
    beat_schedule={
        "worker-heartbeat": {"task": "mainforte.tasks.system.worker_heartbeat", "schedule": 30.0},
        "sweep-outbox": {"task": "mainforte.tasks.system.sweep_outbox", "schedule": 30.0},
        "sweep-auth-tokens": {"task": "mainforte.tasks.system.sweep_auth_tokens", "schedule": 3600.0},
        "rollup-threads": {"task": "mainforte.tasks.system.rollup_threads", "schedule": crontab(hour=6, minute=0)},
        "sweep-old-events": {"task": "mainforte.tasks.system.sweep_old_events", "schedule": crontab(hour=5, minute=30)},
        "refresh-due-widgets": {"task": "mainforte.tasks.system.refresh_due_widgets", "schedule": 300.0},
        "reconcile-subscriptions": {"task": "mainforte.tasks.billing.reconcile_subscriptions", "schedule": 3600.0},
        "sweep-stuck-tasks": {"task": "mainforte.tasks.healing.sweep_stuck_tasks", "schedule": 120.0},
        "refresh-due-tasks": {"task": "mainforte.tasks.system.refresh_due_tasks", "schedule": 60.0},
        "reconcile-agent-workers": {"task": "mainforte.tasks.system.reconcile_agent_workers", "schedule": 60.0},
    },
    imports=("mainforte.tasks.events", "mainforte.tasks.system", "mainforte.tasks.work", "mainforte.tasks.billing",
             "mainforte.tasks.healing", "mainforte.tasks.schedule", "mainforte.push"),
)


def queue_depths() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with celery.connection_for_read() as conn:
            for q in ("chat", "work", "system"):
                try:
                    out[q] = conn.default_channel.queue_declare(queue=q, passive=True).message_count
                except Exception:
                    out[q] = -1
    except Exception:
        out = {q: -1 for q in ("chat", "work", "system")}
    return out
