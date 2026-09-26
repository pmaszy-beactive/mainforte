"""Unit coverage for events/governor.py::ground_action_claims — the P2 Phase 4 grounding check.
No live DB, no live LLM (matches the existing test_events_registry.py pattern): a fake query
object stands in for `db.query(Event)...`, and only the deterministic-match / no-events branches
are exercised, since those never call the LLM fallback. A claim with zero matching events for its
correlation_id (test_no_matching_events_is_unverified) IS the seeded-hallucination scenario in
unit-test form, not a simulation of one.
"""
import asyncio

from mainforte.events.governor import ground_action_claims


class _FakeEvent:
    def __init__(self, type: str, payload: dict, correlation_id: str):
        self.type = type
        self.payload = payload
        self.correlation_id = correlation_id
        self.id = "01FAKE"


class _FakeQuery:
    def __init__(self, rows: list[_FakeEvent]):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows: list[_FakeEvent]):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)


def _run(coro):
    return asyncio.run(coro)


def test_claim_matching_tool_event_is_verified_deterministically():
    events = [_FakeEvent("tool.ended", {"name": "browser_navigate", "result": {"title": "Example Domain"}},
                          "corr-1")]
    db = _FakeDB(events)
    claims = [{"type": "action", "text": "Example Domain"}]

    results = _run(ground_action_claims(db, ws_id="ws1", correlation_id="corr-1", api_key=None, claims=claims))

    assert len(results) == 1
    assert results[0]["verified"] is True
    assert results[0]["method"] == "grounded-deterministic"


def test_no_matching_events_is_unverified():
    """The seeded-hallucination case: a claim with zero tool/agent-work events for this
    correlation_id can never be grounded, regardless of what the claim text says."""
    db = _FakeDB([])
    claims = [{"type": "action", "text": "I booked your flight to Toronto"}]

    results = _run(ground_action_claims(db, ws_id="ws1", correlation_id="corr-2", api_key=None, claims=claims))

    assert len(results) == 1
    assert results[0]["verified"] is False
    assert results[0]["method"] is None
    assert "no tool/agent-work events" in results[0]["reason"]


def test_mixed_claims_partition_correctly():
    events = [_FakeEvent("tool.ended", {"name": "bash", "result": {"stdout": "3 files listed"}}, "corr-3")]
    db = _FakeDB(events)
    claims = [
        {"type": "action", "text": "3 files listed"},
        {"type": "action", "text": "I also emailed the results to your manager"},
        {"type": "fact", "text": "the sky is blue"},  # non-action: should be skipped entirely
    ]

    results = _run(ground_action_claims(db, ws_id="ws1", correlation_id="corr-3", api_key=None, claims=claims))

    assert len(results) == 2  # the fact claim is not returned at all
    verified = {r["claim"]["text"]: r["verified"] for r in results}
    assert verified["3 files listed"] is True
    assert verified["I also emailed the results to your manager"] is False


def test_no_action_claims_returns_empty():
    db = _FakeDB([])
    claims = [{"type": "fact", "text": "the sky is blue"}]

    results = _run(ground_action_claims(db, ws_id="ws1", correlation_id="corr-4", api_key=None, claims=claims))

    assert results == []
