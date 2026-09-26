"""Client for the internal ai-proxy (backbone). Two roles:

- Admin (AI_PROXY_ADMIN_SECRET): mint one API key per workspace so usage/billing is metered
  per-tenant on the proxy side, not just in our own DB.
- Tenant (the minted key): stream chat completions for personas, Anthropic-Messages-shaped.

The proxy is OpenAI- and Anthropic-compatible at `<base>/ai/v1/...`. AI_PROXY_BASE_URL may or
may not already include the `/ai` suffix; `_ai_root()` normalizes it.

Admin app/key provisioning lives at `<base>/ai/admin/apps...` (a separate standalone service from
the dashboard's session-authenticated `/api/ai-proxy/apps...`) and is the one bearer-token,
no-session admin API meant for machine callers like this one. See
deploy/ai-proxy/CLIENT_API_DOCS.md, "Admin Billing API".
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from mainforte.config import get_settings

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"


class AiProxyError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def _ai_root() -> str:
    base = (get_settings().ai_proxy_base_url or "").rstrip("/")
    if base.endswith("/ai"):
        return base
    return base + "/ai"


def enabled() -> bool:
    return bool(get_settings().ai_proxy_base_url)


# ---------------------------------------------------------------- admin: per-workspace keys


def _admin_headers() -> dict[str, str]:
    secret = get_settings().ai_proxy_admin_secret
    if not secret:
        raise AiProxyError("AI_PROXY_ADMIN_SECRET not configured")
    return {"Authorization": f"Bearer {secret}"}


@dataclass
class MintedKey:
    key: str
    key_id: str
    prefix: str


def ensure_app(*, app_slug: str, name: str) -> str:
    """Idempotently ensure a proxy "app" exists for this workspace. Returns the app id."""
    with httpx.Client(base_url=_ai_root(), timeout=15) as c:
        r = c.post("/admin/apps", headers=_admin_headers(), json={"slug": app_slug, "name": name})
        if r.status_code == 201:
            return r.json()["id"]
        if r.status_code in (400, 409):
            # already exists: look it up
            listing = c.get("/admin/apps", headers=_admin_headers())
            listing.raise_for_status()
            body = listing.json()
            apps = body if isinstance(body, list) else body.get("apps", [])
            for app in apps:
                if app.get("slug") == app_slug:
                    return app["id"]
        r.raise_for_status()
        return r.json()["id"]


def mint_key(*, app_id: str, name: str) -> MintedKey:
    with httpx.Client(base_url=_ai_root(), timeout=15) as c:
        r = c.post(f"/admin/apps/{app_id}/keys", headers=_admin_headers(), json={"name": name})
        r.raise_for_status()
        d = r.json()
        return MintedKey(key=d["key"], key_id=d["id"], prefix=d.get("prefix", d["key"][:12]))


def mint_workspace_key(*, ws_id: str, ws_name: str) -> MintedKey:
    app_id = ensure_app(app_slug=f"mainforte-{ws_id}", name=f"mainforte: {ws_name}")
    return mint_key(app_id=app_id, name="workspace-default")


# ---------------------------------------------------------------- tenant: chat completions


def _tenant_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "x-api-key": api_key, "content-type": "application/json"}


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


async def stream_reply(
    *, api_key: str, model: str, system: str, messages: list[dict[str, Any]], max_tokens: int = 2048,
    usage_sink: dict[str, int] | None = None, tools: list[dict[str, Any]] | None = None,
    tool_use_sink: list[ToolUseBlock] | None = None, stop_reason_sink: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """Yields text deltas from POST /v1/messages (Anthropic Messages shape, SSE). Raises AiProxyError
    on non-2xx, with retry_after populated for 429s so the caller can back off.

    If `usage_sink` is given, it is mutated in place with {"input_tokens", "output_tokens"} once
    known (input from message_start, output from message_delta) — a generator can't also return a
    value, and this avoids changing the yield type for the two existing callers.

    If `tools` is given, it's passed through as the Messages API `tools` param. Completed
    `tool_use` blocks (accumulated across `content_block_start`/`content_block_delta`/
    `content_block_stop`, matching Anthropic's streaming shape for that block type — the `input`
    arrives as a stream of partial_json deltas, not one shot) are appended to `tool_use_sink` if
    given. `stop_reason_sink`, if given, gets `{"stop_reason": ...}` from message_delta so the
    caller can tell "stopped for tool use" apart from "stopped, done" without re-deriving it."""
    url = _ai_root() + "/v1/messages"
    body: dict[str, Any] = {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens, "stream": True}
    if tools:
        body["tools"] = tools
    pending_blocks: dict[int, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0)) as c:
        async with c.stream("POST", url, headers=_tenant_headers(api_key), json=body) as resp:
            if resp.status_code != 200:
                raw = await resp.aread()
                retry_after = resp.headers.get("retry-after")
                raise AiProxyError(
                    f"ai-proxy {resp.status_code}: {raw[:500]!r}",
                    status_code=resp.status_code,
                    retry_after=float(retry_after) if retry_after else None,
                )
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    evt = json.loads(data)
                except json.JSONDecodeError:
                    continue
                evt_type = evt.get("type")
                if evt_type == "content_block_delta":
                    delta = evt.get("delta", {})
                    text = delta.get("text")
                    if text:
                        yield text
                    elif delta.get("type") == "input_json_delta":
                        idx = evt.get("index")
                        block = pending_blocks.get(idx)
                        if block is not None:
                            block["json"] += delta.get("partial_json", "")
                elif evt_type == "content_block_start":
                    block = evt.get("content_block", {})
                    if block.get("type") == "tool_use":
                        pending_blocks[evt.get("index")] = {
                            "id": block.get("id", ""), "name": block.get("name", ""), "json": "",
                        }
                elif evt_type == "content_block_stop":
                    block = pending_blocks.pop(evt.get("index"), None)
                    if block is not None and tool_use_sink is not None:
                        try:
                            parsed_input = json.loads(block["json"]) if block["json"] else {}
                        except json.JSONDecodeError:
                            log.warning("tool_use block %s had unparseable input json: %r", block["id"], block["json"])
                            parsed_input = {}
                        tool_use_sink.append(ToolUseBlock(id=block["id"], name=block["name"], input=parsed_input))
                elif evt_type == "message_start":
                    if usage_sink is not None:
                        usage = (evt.get("message") or {}).get("usage") or {}
                        if "input_tokens" in usage:
                            usage_sink["input_tokens"] = usage["input_tokens"]
                elif evt_type == "message_delta":
                    if usage_sink is not None:
                        usage = evt.get("usage") or {}
                        if "output_tokens" in usage:
                            usage_sink["output_tokens"] = usage["output_tokens"]
                    if stop_reason_sink is not None:
                        stop_reason = (evt.get("delta") or {}).get("stop_reason")
                        if stop_reason:
                            stop_reason_sink["stop_reason"] = stop_reason
                elif evt_type == "message_stop":
                    return
                elif evt_type == "error":
                    raise AiProxyError(str(evt.get("error")))


async def complete(*, api_key: str, model: str, system: str, messages: list[dict[str, Any]],
                    max_tokens: int = 300) -> tuple[str, dict[str, int]]:
    """Non-streaming call for small, cheap, single-shot completions (classification, verification) —
    callers that don't need token-by-token deltas. Same endpoint as stream_reply with stream=False.
    Returns (text, usage) where usage is {"input_tokens", "output_tokens"} (0 if absent)."""
    url = _ai_root() + "/v1/messages"
    body = {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens, "stream": False}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=60.0)) as c:
        r = await c.post(url, headers=_tenant_headers(api_key), json=body)
        if r.status_code != 200:
            retry_after = r.headers.get("retry-after")
            raise AiProxyError(
                f"ai-proxy {r.status_code}: {r.text[:500]!r}",
                status_code=r.status_code,
                retry_after=float(retry_after) if retry_after else None,
            )
        d = r.json()
        blocks = d.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        raw_usage = d.get("usage") or {}
        usage = {"input_tokens": raw_usage.get("input_tokens", 0), "output_tokens": raw_usage.get("output_tokens", 0)}
        return text, usage
