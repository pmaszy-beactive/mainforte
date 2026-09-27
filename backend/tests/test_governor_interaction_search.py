"""Unit coverage for events/governor.py::search_interaction_log (task #37: searchable interaction
log). No live Postgres: `text_fts`/`ts_rank`/`plainto_tsquery` are Postgres-only SQL this repo's
hand-rolled-fake convention can't meaningfully simulate, so these tests cover the two things that
are pure Python -- the empty-query short-circuit (no query issued at all) and the result-shaping
(field mapping, 500-char truncation) applied to whatever `db.execute(...)` returns -- not the FTS
matching/ranking itself, which needs a real Postgres integration test to verify.
"""
from mainforte.events.governor import search_interaction_log


class _FakeRow:
    def __init__(self, *, id: str, type: str, correlation_id: str | None, ts: str, text: str, rank: float):
        self.id = id
        self.type = type
        self.correlation_id = correlation_id
        self.ts = ts
        self.text = text
        self.rank = rank


class _FakeResult:
    def __init__(self, rows: list[_FakeRow]):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows: list[_FakeRow]):
        self._rows = rows
        self.executed: list[tuple] = []

    def execute(self, stmt, params):
        self.executed.append((stmt, params))
        return _FakeResult(self._rows)


def test_blank_query_short_circuits_without_hitting_the_db():
    db = _FakeDB([_FakeRow(id="ev1", type="chat.message.created", correlation_id="t1",
                            ts="2026-09-27T00:00:00Z", text="hello", rank=0.5)])

    results = search_interaction_log(db, ws_id="ws1", query="   ")

    assert results == []
    assert db.executed == []


def test_results_are_shaped_and_truncated():
    long_text = "x" * 600
    rows = [
        _FakeRow(id="ev1", type="chat.message.created", correlation_id="thread-1",
                 ts="2026-09-27T00:00:00Z", text=long_text, rank=0.9),
        _FakeRow(id="ev2", type="persona.reply.ended", correlation_id="thread-2",
                 ts="2026-09-27T01:00:00Z", text=None, rank=0.1),
    ]
    db = _FakeDB(rows)

    results = search_interaction_log(db, ws_id="ws1", query="refund policy", limit=5)

    assert len(results) == 2
    assert results[0]["event_id"] == "ev1"
    assert results[0]["thread_id"] == "thread-1"
    assert len(results[0]["text"]) == 500
    assert results[1]["text"] == ""  # a null payload text coalesces to empty, not None

    # the query params actually reached db.execute unchanged, including the default thread scope
    assert len(db.executed) == 1
    _stmt, params = db.executed[0]
    assert params == {"query": "refund policy", "ws_id": "ws1", "thread_id": None, "limit": 5}


def test_thread_id_is_passed_through_for_thread_scoped_search():
    db = _FakeDB([])

    search_interaction_log(db, ws_id="ws1", query="claim text", thread_id="thread-9")

    _stmt, params = db.executed[0]
    assert params["thread_id"] == "thread-9"
