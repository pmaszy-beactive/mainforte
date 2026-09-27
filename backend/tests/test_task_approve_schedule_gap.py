"""Regression test for the /approve vs /schedule gap: a task created with a `schedule` up front
must, on approval, become `status="scheduled"` (so `refresh_due_tasks`/`fire_scheduled_task` can
fan out its recurring runs) instead of running once via `run_task_stage` and being left as a dead
`scheduled`-looking-but-actually-`completed` row with an inert schedule blob.
"""
from types import SimpleNamespace

import mainforte.tasks.routes as routes_mod


class _FakeTask:
    def __init__(self, *, status: str, schedule: dict | None, ws_id: str = "ws-1"):
        self.id = "task-1"
        self.ws_id = ws_id
        self.status = status
        self.schedule = schedule
        self.correlation_id = "task-1"
        self.thread_id = None


class _FakeDb:
    def __init__(self, task: _FakeTask):
        self._task = task
        self.committed = False

    def get(self, _model, task_id):
        return self._task if task_id == self._task.id else None

    def commit(self):
        self.committed = True


def _patch_common(monkeypatch, task: _FakeTask):
    ws = SimpleNamespace(id=task.ws_id)
    monkeypatch.setattr(routes_mod, "require_membership", lambda *a, **k: ws)
    monkeypatch.setattr(routes_mod, "emit", lambda *a, **k: {"id": "ev-1"})
    dispatched = []
    monkeypatch.setattr(routes_mod.run_task_stage, "delay",
                         lambda *a, **k: dispatched.append((a, k)))
    return dispatched


def test_approve_recurring_task_schedules_instead_of_running_once(monkeypatch):
    task = _FakeTask(status="planned", schedule={"kind": "interval", "interval_seconds": 604800,
                                                  "active": True, "next_run_at": "2026-01-01T00:00:00"})
    db = _FakeDb(task)
    dispatched = _patch_common(monkeypatch, task)
    ident = SimpleNamespace(user=SimpleNamespace(id="u-1"))

    out = routes_mod.approve_task(workspace_id="ws-1", task_id="task-1", ident=ident, db=db)

    assert task.status == "scheduled"
    assert dispatched == []  # template itself must never be run directly
    assert out["status"] == "scheduled"
    assert db.committed is True


def test_approve_one_shot_task_still_runs_once(monkeypatch):
    task = _FakeTask(status="planned", schedule=None)
    db = _FakeDb(task)
    dispatched = _patch_common(monkeypatch, task)
    ident = SimpleNamespace(user=SimpleNamespace(id="u-1"))

    out = routes_mod.approve_task(workspace_id="ws-1", task_id="task-1", ident=ident, db=db)

    assert task.status == "approved"
    assert len(dispatched) == 1
    assert dispatched[0][1] == {"task_id": "task-1", "ws_id": "ws-1"}
    assert out["status"] == "approved"


def test_approve_inactive_schedule_still_runs_once(monkeypatch):
    """A schedule that was later disabled (active: false) before approval — e.g. via a
    since-superseded /schedule DELETE — should not block a normal one-shot approve/run."""
    task = _FakeTask(status="planned", schedule={"kind": "interval", "interval_seconds": 60,
                                                  "active": False})
    db = _FakeDb(task)
    dispatched = _patch_common(monkeypatch, task)
    ident = SimpleNamespace(user=SimpleNamespace(id="u-1"))

    out = routes_mod.approve_task(workspace_id="ws-1", task_id="task-1", ident=ident, db=db)

    assert task.status == "approved"
    assert len(dispatched) == 1
    assert out["status"] == "approved"
