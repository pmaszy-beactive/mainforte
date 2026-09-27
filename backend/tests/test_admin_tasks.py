"""Tests for the admin Tasks endpoints (`GET /api/admin/tasks`, `GET /api/admin/tasks/{id}`):
the list/summary shape, filtering, and that the event-timeline query for a task detail includes
both base-correlation events and stage-correlation (`base_corr:N`) sub-events (the scheme used by
`mainforte.tasks.work.run_task_stage`), via `Event.correlation_id.like(f"{base_corr}:%")`.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import mainforte.admin.routes as routes_mod
from mainforte.admin.routes import _task_summary


class _Cmp:
    """Result of a fake-column comparison/like/or — remembers how to test a row."""

    def __init__(self, check):
        self._check = check

    def __call__(self, row):
        return self._check(row)

    def __or__(self, other):
        return _Cmp(lambda row: self(row) or other(row))


class _Col:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return _Cmp(lambda row: getattr(row, self.name) == value)

    def __hash__(self):
        return id(self)

    def like(self, pattern):
        assert pattern.endswith("%")
        prefix = pattern[:-1]
        return _Cmp(lambda row: str(getattr(row, self.name)).startswith(prefix))

    def desc(self):
        return _Col(self.name)

    def asc(self):
        return _Col(self.name)


class _FakeTaskModel:
    id = _Col("id")
    ws_id = _Col("ws_id")
    persona_id = _Col("persona_id")
    status = _Col("status")
    created_at = _Col("created_at")


class _FakeEventModel:
    id = _Col("id")
    correlation_id = _Col("correlation_id")


class _Task:
    def __init__(self, *, id="task-1", ws_id="ws-1", persona_id=None, status="running",
                 current_stage=1, plan=None, attempt=0, schedule=None, correlation_id=None,
                 thread_id=None, result=None):
        self.id = id
        self.ws_id = ws_id
        self.persona_id = persona_id
        self.status = status
        self.current_stage = current_stage
        self.plan = plan if plan is not None else [{}, {}, {}]
        self.attempt = attempt
        self.schedule = schedule
        self.correlation_id = correlation_id
        self.thread_id = thread_id
        self.result = result
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)


class _Event:
    def __init__(self, id, type, correlation_id, payload=None):
        self.id = id
        self.type = type
        self.correlation_id = correlation_id
        self.payload = payload or {}
        self.ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.ws_id = "ws-1"
        self.user_id = None
        self.actor_type = "system"
        self.actor_id = "sys"
        self.causation_id = None
        self.ephemeral = False


class _Query:
    def __init__(self, rows, *, is_event=False):
        self._rows = rows
        self._is_event = is_event

    def join(self, *a, **k):
        return self

    def outerjoin(self, *a, **k):
        return self

    def filter(self, cond):
        rows = [r for r in self._rows if cond(r if self._is_event else r[0])]
        return _Query(rows, is_event=self._is_event)

    def order_by(self, *a, **k):
        key = (lambda r: r.id) if self._is_event else (lambda r: r[0].created_at)
        return _Query(sorted(self._rows, key=key, reverse=not self._is_event), is_event=self._is_event)

    def limit(self, n):
        return _Query(self._rows[:n], is_event=self._is_event)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDb:
    def __init__(self, task_rows, events=None):
        self._task_rows = task_rows
        self._events = events or []

    def query(self, *targets):
        if targets and targets[0] is _FakeEventModel:
            return _Query(self._events, is_event=True)
        return _Query(self._task_rows)


@pytest.fixture(autouse=True)
def _patch_models(monkeypatch):
    monkeypatch.setattr(routes_mod, "Task", _FakeTaskModel)
    monkeypatch.setattr(routes_mod, "Event", _FakeEventModel)


def test_task_summary_shape():
    t = _Task(plan=[{}, {}])
    out = _task_summary(t, ws_name="Acme", persona_name="Scout")
    assert out["id"] == "task-1"
    assert out["ws_name"] == "Acme"
    assert out["persona_name"] == "Scout"
    assert out["plan_len"] == 2
    assert out["created_at"] == "2026-01-01T00:00:00+00:00"


def test_tasks_list_filters_by_status_and_workspace():
    rows = [
        (_Task(id="t1", ws_id="ws-1", status="running"), "Acme", "Scout"),
        (_Task(id="t2", ws_id="ws-1", status="completed"), "Acme", "Scout"),
        (_Task(id="t3", ws_id="ws-2", status="running"), "Other", None),
    ]
    db = _FakeDb(rows)

    out = routes_mod.tasks(status="running", workspace_id=None, limit=100, db=db)
    ids = {r["id"] for r in out["tasks"]}
    assert ids == {"t1", "t3"}

    out2 = routes_mod.tasks(status=None, workspace_id="ws-1", limit=100, db=db)
    ids2 = {r["id"] for r in out2["tasks"]}
    assert ids2 == {"t1", "t2"}


def test_task_detail_includes_base_and_stage_correlated_events():
    task = _Task(id="task-1", correlation_id="task-1", result={"ok": True})
    task_rows = [(task, "Acme", "Scout")]
    events = [
        _Event(1, "task.stage.started", "task-1:0"),
        _Event(2, "tool.started", "task-1:0"),
        _Event(3, "tool.ended", "task-1:0"),
        _Event(4, "task.stage.ended", "task-1:0"),
        _Event(5, "task.stage.started", "task-1:1"),
        _Event(6, "task.completed", "task-1"),
        _Event(99, "task.stage.started", "other-task:0"),  # must NOT be included
    ]
    db = _FakeDb(task_rows, events=events)

    out = routes_mod.task_detail(task_id="task-1", db=db)

    assert out["task"]["id"] == "task-1"
    assert out["task"]["result"] == {"ok": True}
    event_ids = [e["id"] for e in out["events"]]
    assert event_ids == [1, 2, 3, 4, 5, 6]


def test_task_detail_404_when_missing():
    db = _FakeDb([])
    with pytest.raises(HTTPException) as exc_info:
        routes_mod.task_detail(task_id="nope", db=db)
    assert exc_info.value.status_code == 404
