"""Unit coverage for tasks/work.py::_gmail_secrets (task #38 part 3). `db_session()` is monkeypatched
with a fake context manager (mirrors _home_owner's shape: `Workspace.owner_id` collapses a
workspace's tool calls to one user's identity) so no live Postgres is needed, matching this repo's
hand-rolled-fake convention. Covers: non-gmail tool names short-circuit before any DB access,
missing workspace/identity/token all resolve to `{}`, and a real match returns the *decrypted*
access token under the expected secrets key.
"""
from types import SimpleNamespace

import mainforte.tasks.work as work_mod
from mainforte.crypto import encrypt


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._result


class _FakeDb:
    def __init__(self, *, workspace=None, identity=None):
        self._workspace = workspace
        self._identity = identity
        self.got: list[tuple] = []

    def get(self, _model, ws_id):
        self.got.append(ws_id)
        return self._workspace

    def query(self, _model):
        return _FakeQuery(self._identity)


class _FakeSession:
    def __init__(self, db: _FakeDb):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *exc):
        return False


def _patch_db(monkeypatch, db: _FakeDb):
    monkeypatch.setattr(work_mod, "db_session", lambda: _FakeSession(db))


def test_non_gmail_tool_short_circuits_without_touching_the_db(monkeypatch):
    db = _FakeDb(workspace=SimpleNamespace(owner_id="u-1"))
    _patch_db(monkeypatch, db)

    result = work_mod._gmail_secrets("ws-1", "web_search")

    assert result == {}
    assert db.got == []


def test_missing_workspace_returns_empty(monkeypatch):
    db = _FakeDb(workspace=None)
    _patch_db(monkeypatch, db)

    assert work_mod._gmail_secrets("ws-missing", "gmail_send") == {}


def test_no_connected_identity_returns_empty(monkeypatch):
    db = _FakeDb(workspace=SimpleNamespace(owner_id="u-1"), identity=None)
    _patch_db(monkeypatch, db)

    assert work_mod._gmail_secrets("ws-1", "gmail_send") == {}


def test_identity_without_access_token_returns_empty(monkeypatch):
    ident = SimpleNamespace(access_token_enc=None)
    db = _FakeDb(workspace=SimpleNamespace(owner_id="u-1"), identity=ident)
    _patch_db(monkeypatch, db)

    assert work_mod._gmail_secrets("ws-1", "gmail_send") == {}


def test_connected_identity_returns_decrypted_token(monkeypatch):
    ident = SimpleNamespace(access_token_enc=encrypt("tok-plaintext"))
    db = _FakeDb(workspace=SimpleNamespace(owner_id="u-1"), identity=ident)
    _patch_db(monkeypatch, db)

    result = work_mod._gmail_secrets("ws-1", "gmail_send")

    assert result == {"gmail_access_token": "tok-plaintext"}
