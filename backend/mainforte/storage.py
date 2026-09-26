"""Object storage: backbone s3-proxy (Bearer auth) with a local-disk fallback for dev.

Backbone facts (s3_proxy.py): keys are namespaced per app under storage/<slug>/, GET reads whole objects
into memory (no Range), no batch delete, keys <= ~950 chars and no '..'.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx

from mainforte.config import get_settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    n = _SAFE.sub("_", name.strip())[:120] or "file"
    return n.replace("..", "_")


@dataclass
class Stored:
    key: str
    size: int
    sha256: str


class Storage:
    def put(self, key: str, data: bytes, content_type: str) -> Stored: ...
    def get(self, key: str) -> bytes | None: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root

    def _p(self, key: str) -> Path:
        if ".." in key or key.startswith("/"):
            raise ValueError("bad key")
        return self.root / key

    def put(self, key: str, data: bytes, content_type: str) -> Stored:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return Stored(key=key, size=len(data), sha256=hashlib.sha256(data).hexdigest())

    def get(self, key: str) -> bytes | None:
        p = self._p(key)
        return p.read_bytes() if p.is_file() else None

    def delete(self, key: str) -> None:
        p = self._p(key)
        if p.is_file():
            p.unlink()

    def exists(self, key: str) -> bool:
        return self._p(key).is_file()


class BackboneS3(Storage):
    def __init__(self, endpoint: str, api_key: str) -> None:
        base = endpoint.rstrip("/")
        if not base.endswith("/s3"):
            base += "/s3"
        self.base = base
        self.client = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {api_key}"}, timeout=120,
                                   transport=httpx.HTTPTransport(retries=3))

    def put(self, key: str, data: bytes, content_type: str) -> Stored:
        if ".." in key or key.startswith("/"):
            raise ValueError("bad key")
        r = self.client.put(f"/{key}", content=data, headers={"Content-Type": content_type})
        r.raise_for_status()
        return Stored(key=key, size=len(data), sha256=hashlib.sha256(data).hexdigest())

    def get(self, key: str) -> bytes | None:
        r = self.client.get(f"/{key}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def delete(self, key: str) -> None:
        r = self.client.delete(f"/{key}")
        if r.status_code not in (204, 404):
            r.raise_for_status()

    def exists(self, key: str) -> bool:
        return self.client.head(f"/{key}").status_code == 200


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.s3_endpoint and s.s3_api_key:
        return BackboneS3(s.s3_endpoint, s.s3_api_key)
    root = Path(__file__).resolve().parents[2] / ".data" / "storage"
    return LocalStorage(root)


def upload_key(user_id: str, upload_id: str, name: str) -> str:
    return f"users/{user_id}/uploads/{upload_id}-{safe_name(name)}"


def widget_key(user_id: str, slug: str, version: int, filename: str) -> str:
    return f"users/{user_id}/widgets/{slug}/{version}/{filename}"
