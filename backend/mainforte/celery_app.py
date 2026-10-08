from __future__ import annotations

import logging
import threading

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_shutdown, worker_ready
from kombu import Queue

from mainforte.config import get_settings

log = logging.getLogger(__name__)

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
        "sweep-stuck-replies": {"task": "mainforte.tasks.healing.sweep_stuck_replies", "schedule": 120.0},
        "refresh-due-tasks": {"task": "mainforte.tasks.system.refresh_due_tasks", "schedule": 60.0},
        "reconcile-agent-workers": {"task": "mainforte.tasks.system.reconcile_agent_workers", "schedule": 60.0},
    },
    imports=("mainforte.tasks.events", "mainforte.tasks.system", "mainforte.tasks.work", "mainforte.tasks.billing",
             "mainforte.tasks.healing", "mainforte.tasks.schedule", "mainforte.push"),
)


# Pooled worker containers (Dockerfile.worker) run plain `celery worker`, no `--beat` -- only the
# API container's in-process scheduler fallback (scheduler.py) drives beat_schedule, and it runs
# each entry in ITS OWN process, so `worker-heartbeat` firing there would self-register the API
# container, never the actual pooled worker. Each worker process therefore needs to heartbeat
# itself: this thread calls worker_heartbeat.apply() (in-process, no broker hop -- it's this same
# worker registering itself) every 30s for as long as this worker process is alive, so
# _reconcile_pool (tasks/system.py) sees it as live instead of endlessly re-provisioning it.
_HEARTBEAT_INTERVAL_SECONDS = 30.0
_heartbeat_stop = threading.Event()
_heartbeat_thread: threading.Thread | None = None


def _heartbeat_loop() -> None:
    from mainforte.tasks.system import worker_heartbeat

    while not _heartbeat_stop.is_set():
        try:
            worker_heartbeat.apply()
        except Exception:
            log.exception("self-heartbeat: worker_heartbeat raised")
        _heartbeat_stop.wait(_HEARTBEAT_INTERVAL_SECONDS)


@worker_ready.connect
def _start_self_heartbeat(**kwargs) -> None:
    global _heartbeat_thread
    if _heartbeat_thread is not None:
        return
    _heartbeat_stop.clear()
    _heartbeat_thread = threading.Thread(target=_heartbeat_loop, name="worker-self-heartbeat", daemon=True)
    _heartbeat_thread.start()
    log.info("self-heartbeat thread started (interval=%ss)", _HEARTBEAT_INTERVAL_SECONDS)


@worker_process_shutdown.connect
def _stop_self_heartbeat(**kwargs) -> None:
    _heartbeat_stop.set()


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
