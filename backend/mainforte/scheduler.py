"""In-process fallback scheduler for beat-only tasks under a backbone deploy (PLAN.md open item,
2026-09-27). Backbone's api container runs plain `uvicorn` with no separate `celery beat` process
(only the worker container runs `celery worker`, without `--beat`) -- so today, none of
`celery_app.py`'s `beat_schedule` entries ever fire in production. This module runs those same
task bodies directly, in-process, on the same cadence, without going through Celery's beat service
or requiring a broker connection for the top-level tick (tasks that fan out via `.delay()`
internally still need the broker for that inner dispatch, exactly as they do under real beat).

Reads cadence directly from `celery.conf.beat_schedule` (not a second hardcoded copy) so this can
never silently drift from the Celery-side schedule. Each entry's `schedule` is either a plain
number of seconds or a `celery.schedules.crontab` -- both expose `.remaining_estimate(last_run_at)`,
which this scheduler uses to decide when each entry is next due, mirroring how Celery's own beat
service drives its loop.

Deliberately NOT started by default in local dev, where `celery worker --beat` already runs in the
same combined process (README's dev command) -- running both would double-fire every task. Gated by
`Settings.enable_in_process_scheduler`, which defaults to "on only when APP_ENV is prod/production"
and can be overridden explicitly either way via the ENABLE_IN_PROCESS_SCHEDULER env var.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from mainforte.celery_app import celery

log = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 5.0


class InProcessScheduler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_run_at: dict[str, datetime] = {}

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="in-process-scheduler", daemon=True)
        self._thread.start()
        log.info("in-process scheduler started (%d entries)", len(celery.conf.beat_schedule))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=_POLL_INTERVAL_SECONDS * 2)
            self._thread = None

    def _loop(self) -> None:
        now = datetime.now(timezone.utc)
        for name in celery.conf.beat_schedule:
            self._last_run_at[name] = now
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(_POLL_INTERVAL_SECONDS)

    def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        for name, entry in celery.conf.beat_schedule.items():
            last_run_at = self._last_run_at.get(name, now)
            remaining = entry["schedule"].remaining_estimate(last_run_at).total_seconds()
            if remaining > 0:
                continue
            self._last_run_at[name] = now
            self._run_entry(name, entry["task"])

    def _run_entry(self, name: str, task_path: str) -> None:
        task = celery.tasks.get(task_path)
        if task is None:
            log.error("in-process scheduler: unknown task %r for entry %r", task_path, name)
            return
        try:
            task()
        except Exception:
            log.exception("in-process scheduler: entry %r (%s) raised", name, task_path)


scheduler = InProcessScheduler()
