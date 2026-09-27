"""Unit coverage for scheduler.py (task #41). No live Celery worker/broker involved -- the scheduler
reads `celery.conf.beat_schedule` (real, imported from celery_app.py) but each test substitutes a
tiny fake schedule dict and fake registered "tasks" (plain callables) via monkeypatch, matching this
repo's hand-rolled-fake convention. Covers: due-time gating using real `celery.schedules` objects, a
raising entry not killing the tick (per-entry error isolation), and start/stop lifecycle.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from celery.schedules import schedule as celery_schedule

from mainforte.scheduler import InProcessScheduler


def _patch_beat_schedule(monkeypatch, entries: dict, tasks: dict):
    monkeypatch.setattr("mainforte.scheduler.celery.conf.beat_schedule", entries)
    monkeypatch.setattr("mainforte.scheduler.celery.tasks", tasks)


def test_tick_runs_only_due_entries(monkeypatch):
    calls = []
    _patch_beat_schedule(
        monkeypatch,
        entries={
            "due-now": {"task": "t.due", "schedule": celery_schedule(30.0)},
            "not-due": {"task": "t.not_due", "schedule": celery_schedule(3600.0)},
        },
        tasks={"t.due": lambda: calls.append("due"), "t.not_due": lambda: calls.append("not_due")},
    )
    sched = InProcessScheduler()
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    just_now = datetime.now(timezone.utc) - timedelta(seconds=1)
    sched._last_run_at = {"due-now": long_ago, "not-due": just_now}

    sched._tick()

    assert calls == ["due"]
    assert sched._last_run_at["not-due"] == just_now  # untouched: not due, no run recorded


def test_unknown_task_path_logs_and_does_not_raise(monkeypatch):
    _patch_beat_schedule(
        monkeypatch,
        entries={"ghost": {"task": "t.ghost", "schedule": celery_schedule(30.0)}},
        tasks={},
    )
    sched = InProcessScheduler()
    sched._last_run_at = {"ghost": datetime.now(timezone.utc) - timedelta(hours=1)}

    sched._tick()  # must not raise


def test_raising_entry_does_not_stop_other_entries_from_running(monkeypatch):
    calls = []

    def _boom():
        raise RuntimeError("boom")

    _patch_beat_schedule(
        monkeypatch,
        entries={
            "broken": {"task": "t.broken", "schedule": celery_schedule(30.0)},
            "fine": {"task": "t.fine", "schedule": celery_schedule(30.0)},
        },
        tasks={"t.broken": _boom, "t.fine": lambda: calls.append("fine")},
    )
    sched = InProcessScheduler()
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    sched._last_run_at = {"broken": long_ago, "fine": long_ago}

    sched._tick()  # must not raise despite "broken" entry's task raising

    assert calls == ["fine"]


def test_start_seeds_last_run_at_and_stop_joins_thread(monkeypatch):
    calls = []
    _patch_beat_schedule(
        monkeypatch,
        entries={"due-now": {"task": "t.due", "schedule": celery_schedule(30.0)}},
        tasks={"t.due": lambda: calls.append("due")},
    )
    monkeypatch.setattr("mainforte.scheduler._POLL_INTERVAL_SECONDS", 0.05)
    sched = InProcessScheduler()

    sched.start()
    try:
        time.sleep(0.2)
    finally:
        sched.stop()

    assert sched._thread is None
    assert "due-now" in sched._last_run_at
