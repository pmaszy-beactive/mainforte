"""Unit coverage for the connections endpoints in auth/routes.py (list_connections,
disconnect_connection): the generic, provider-agnostic settings UI reads its state from here
instead of the old `?gmail=connected` URL-param hack. Hand-rolled fakes for `db.query(...)`,
matching this repo's convention (see test_gmail_secrets.py, test_admin_tasks.py)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import mainforte.auth.routes as routes_mod


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter_by(self, **kwargs):
        rows = [r for r in self._rows if all(getattr(r, k) == v for k, v in kwargs.items())]
        return _Query(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDb:
    def __init__(self, identities):
        self._identities = identities
        self.emitted: list[tuple] = []

    def query(self, _model):
        return _Query(self._identities)

    def commit(self):
        pass


def _identity(user_id="u-1", *, real_user_id=None):
    user = SimpleNamespace(id=user_id)
    real = SimpleNamespace(id=real_user_id or user_id)
    return SimpleNamespace(user=user, real_user=real)


def test_list_connections_returns_only_current_users_rows():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(user_id="u-1", provider="google", email="me@x.com", scopes=["openid", "gmail.send"],
                        created_at=now, expires_at=None),
        SimpleNamespace(user_id="u-2", provider="google", email="other@x.com", scopes=["openid"],
                        created_at=now, expires_at=None),
    ]
    db = _FakeDb(rows)

    out = routes_mod.list_connections(identity=_identity("u-1"), db=db)

    assert len(out["connections"]) == 1
    assert out["connections"][0]["provider"] == "google"
    assert out["connections"][0]["email"] == "me@x.com"
    assert out["connections"][0]["scopes"] == ["openid", "gmail.send"]


def test_disconnect_clears_tokens_and_extra_scopes_but_keeps_identity(monkeypatch):
    ident = SimpleNamespace(
        user_id="u-1", provider="google", email="me@x.com",
        scopes=["openid", "email", "profile", "gmail.send"],
        access_token_enc="enc-a", refresh_token_enc="enc-r",
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db = _FakeDb([ident])
    called = {}
    monkeypatch.setattr(routes_mod, "emit", lambda db, *a, **k: called.setdefault("emitted", True))

    resp = routes_mod.disconnect_connection("google", identity=_identity("u-1"), db=db)

    assert ident.access_token_enc is None
    assert ident.refresh_token_enc is None
    assert ident.expires_at is None
    assert ident.scopes == ["openid", "email", "profile"]
    assert resp.status_code == 204
    assert called.get("emitted") is True


def test_disconnect_missing_provider_404s():
    import pytest
    from fastapi import HTTPException

    db = _FakeDb([])
    with pytest.raises(HTTPException) as exc_info:
        routes_mod.disconnect_connection("google", identity=_identity("u-1"), db=db)
    assert exc_info.value.status_code == 404
