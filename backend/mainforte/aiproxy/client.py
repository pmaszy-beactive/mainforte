"""Client for the internal ai-proxy (backbone). Two roles:

- Admin (AI_PROXY_ADMIN_SECRET): mint one API key per workspace so usage/billing is metered
  per-tenant on the proxy side, not just in our own DB.
- Tenant (the minted key): stream chat completions for personas, Anthropic-Messages-shaped.

The proxy is OpenAI- and Anthropic-compatible at `<base>/ai/v1/...`. AI_PROXY_BASE_URL may or
may not already include the `/ai` suffix; `_ai_root()` normalizes it.
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
        r = c.post("/apps", headers=_admin_headers(), json={"slug": app_slug, "name": name})
        if r.status_code == 201:
            return r.json()["id"]
        if r.status_code in (400, 409):
            # already exists: look it up
            listing = c.get("/apps", headers=_admin_headers())
            listing.raise_for_status()
            for app in listing.json().get("apps", listing.json() if isinstance(listing.json(), list) else []):
                if app.get("slug") == app_slug:
                    return app["id"]
        r.raise_for_status()
        return r.json()["id"]


def mint_key(*, app_id: str, name: str) -> MintedKey:
    with httpx.Client(base_url=_ai_root(), timeout=15) as c:
        r = c.post(f"/apps/{app_id}/keys", headers=_admin_headers(), json={"name": name})
        r.raise_for_status()
        d = r.json()
        return MintedKey(key=d["key"], key_id=d["id"], prefix=d.get("prefix", d["key"][:12]))


def mint_workspace_key(*, ws_id: str, ws_name: str) -> MintedKey:
    app_id = ensure_app(app_slug=f"mainforte-{ws_id}", name=f"mainforte: {ws_name}")
    return mint_key(app_id=app_id, name="workspace-default")


# ---------------------------------------------------------------- tenant: chat completions


def _tenant_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "x-api-key": api_key, "content-type": "application/json"}


async def stream_reply(
    *, api_key: str, model: str, system: str, messages: list[dict[str, Any]], max_tokens: int = 2048,
) -> AsyncIterator[str]:
    """Yields text deltas from POST /v1/messages (Anthropic Messages shape, SSE). Raises AiProxyError
    on non-2xx, with retry_after populated for 429s so the caller can back off."""
    url = _ai_root() + "/v1/messages"
    body = {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens, "stream": True}
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
                if evt.get("type") == "content_block_delta":
                    delta = evt.get("delta", {})
                    text = delta.get("text")
                    if text:
                        yield text
                elif evt.get("type") == "message_stop":
                    return
                elif evt.get("type") == "error":
                    raise AiProxyError(str(evt.get("error")))


async def complete(*, api_key: str, model: str, system: str, messages: list[dict[str, Any]],
                    max_tokens: int = 300) -> str:
    """Non-streaming call for small, cheap, single-shot completions (classification, verification) —
    callers that don't need token-by-token deltas. Same endpoint as stream_reply with stream=False."""
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
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
