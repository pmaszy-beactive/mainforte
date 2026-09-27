"""Regression test for the QA stale-error poisoning bug: a task stage that fails once (emitting
`tool.error`) and then succeeds on retry (emitting a fresh `tool.started`/`tool.ended` under the
SAME `stage_corr`, since retries rerun the identical stage index) must not be permanently
QA-failing due to the earlier attempt's stale error. `_stage_claims` must only consider events at
or after that stage's latest `tool.started`.
"""
from mainforte.events.task_qa import _stage_claims


class _FakeEvent:
    _next_id = 1

    def __init__(self, type: str, payload: dict, correlation_id: str):
        self.type = type
        self.payload = payload
        self.correlation_id = correlation_id
        self.id = _FakeEvent._next_id
        _FakeEvent._next_id += 1


class _FakeColumn:
    """Stands in for `Event.id` so `.filter(Event.id >= x)` can be evaluated against fake rows."""

    def __init__(self, name: str):
        self.name = name


class _FakeEventModel:
    id = _FakeColumn("id")
    correlation_id = _FakeColumn("correlation_id")
    type = _FakeColumn("type")


class _Cmp:
    """Result of `Event.id >= latest_start[0]` etc — just remembers what to check later."""

    def __init__(self, col: str, op: str, value):
        self.col = col
        self.op = op
        self.value = value

    def matches(self, row: _FakeEvent) -> bool:
        actual = getattr(row, self.col)
        if self.op == "==":
            return actual == self.value
        if self.op == ">=":
            return actual >= self.value
        if self.op == "in":
            return actual in self.value
        raise AssertionError(f"unhandled op {self.op}")


def _make_col_ops():
    # Patch comparison operators onto _FakeColumn instances via monkey-style methods.
    def eq(self, value):
        return _Cmp(self.name, "==", value)

    def ge(self, value):
        return _Cmp(self.name, ">=", value)

    def in_(self, value):
        return _Cmp(self.name, "in", value)

    def desc(self):
        return self

    def asc(self):
        return self

    _FakeColumn.__eq__ = eq
    _FakeColumn.__ge__ = ge
    _FakeColumn.in_ = in_
    _FakeColumn.desc = desc
    _FakeColumn.asc = asc


_make_col_ops()


class _FakeQuery:
    def __init__(self, rows: list[_FakeEvent], select_id_only: bool = False):
        self._rows = rows
        self._select_id_only = select_id_only

    def filter(self, *conds):
        rows = self._rows
        for cond in conds:
            rows = [r for r in rows if cond.matches(r)]
        return _FakeQuery(rows, select_id_only=self._select_id_only)

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return (self._rows[0].id,) if self._rows else None


class _FakeSession:
    def __init__(self, rows: list[_FakeEvent]):
        self._rows = rows

    def query(self, target):
        if target is _FakeEventModel.id:
            return _FakeQuery(sorted(self._rows, key=lambda r: -r.id))
        return _FakeQuery(sorted(self._rows, key=lambda r: r.id))


def test_retry_success_after_failure_is_not_poisoned_by_stale_error(monkeypatch):
    import mainforte.events.task_qa as task_qa_mod

    monkeypatch.setattr(task_qa_mod, "Event", _FakeEventModel)

    stage_corr = "task-1:0"
    events = [
        _FakeEvent("tool.started", {"name": "bash"}, stage_corr),
        _FakeEvent("tool.error", {"name": "bash", "message": "boom"}, stage_corr),
        # retry: identical stage_index -> same stage_corr
        _FakeEvent("tool.started", {"name": "bash"}, stage_corr),
        _FakeEvent("tool.ended", {"name": "bash", "result": {"stdout": "ok"}}, stage_corr),
    ]
    db = _FakeSession(events)

    claims, errors = _stage_claims(db, base_corr="task-1", first_stage=0, last_stage=1)

    assert errors == []
    assert len(claims) == 1
    assert claims[0]["text"] == "name=bash result={'stdout': 'ok'}"


def test_no_retry_still_surfaces_error():
    import mainforte.events.task_qa as task_qa_mod

    stage_corr = "task-2:0"
    events = [
        _FakeEvent("tool.started", {"name": "bash"}, stage_corr),
        _FakeEvent("tool.error", {"name": "bash", "message": "boom"}, stage_corr),
    ]
    db = _FakeSession(events)

    import mainforte.events.task_qa as m
    m_orig_event = m.Event
    m.Event = _FakeEventModel
    try:
        claims, errors = _stage_claims(db, base_corr="task-2", first_stage=0, last_stage=1)
    finally:
        m.Event = m_orig_event

    assert claims == []
    assert len(errors) == 1
    assert errors[0]["text"] == "name=bash message=boom"
