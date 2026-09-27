"""Unit coverage for tools/sandbox_exec.py::_gmail_send (task #38 part 3). No live Gmail API call --
`httpx.post` is monkeypatched with a fake response, matching this repo's hand-rolled-fake convention
(see test_governor_interaction_search.py). Covers: missing-secret short-circuit, a successful send's
request shape (RFC822/base64url raw payload, Bearer header, correct endpoint), and 401/other-4xx/5xx
mapped to ToolExecError rather than raising httpx's own exception type.
"""
import base64
from pathlib import Path

import httpx
import pytest

from mainforte.tools.sandbox_exec import ToolExecError, _gmail_send


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text

    def json(self):
        return self._json


def test_no_connected_account_raises_without_calling_gmail(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append((a, k)))

    with pytest.raises(ToolExecError, match="no connected Gmail account"):
        _gmail_send(tmp_path, to="a@example.com", subject="hi", body="hello", secrets={})

    assert calls == []


def test_successful_send_posts_expected_raw_message(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse(200, {"id": "msg-123"})

    monkeypatch.setattr(httpx, "post", fake_post)

    result = _gmail_send(
        tmp_path, to="a@example.com", subject="hi there", body="hello world",
        secrets={"gmail_access_token": "tok-abc"},
    )

    assert result == {"message_id": "msg-123"}
    assert captured["url"] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    assert captured["headers"] == {"Authorization": "Bearer tok-abc"}
    raw = captured["json"]["raw"]
    decoded = base64.urlsafe_b64decode(raw.encode()).decode()
    assert "to: a@example.com" in decoded
    assert "subject: hi there" in decoded
    assert "hello world" in decoded


@pytest.mark.parametrize("status", [401, 403])
def test_auth_rejection_maps_to_tool_exec_error(monkeypatch, tmp_path: Path, status: int):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(status, text="denied"))

    with pytest.raises(ToolExecError, match="auth rejected"):
        _gmail_send(tmp_path, to="a@example.com", subject="s", body="b",
                     secrets={"gmail_access_token": "tok"})


def test_other_error_status_maps_to_tool_exec_error(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(500, text="boom"))

    with pytest.raises(ToolExecError, match="gmail_send failed \\(500\\)"):
        _gmail_send(tmp_path, to="a@example.com", subject="s", body="b",
                     secrets={"gmail_access_token": "tok"})
