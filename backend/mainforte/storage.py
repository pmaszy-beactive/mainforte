"""Object storage: backbone s3-proxy (Bearer auth) with a local-disk fallback for dev.

Backbone facts (s3_proxy.py): keys are namespaced per app under storage/<slug>/, GET reads whole objects
into memory (no Range), no batch delete, keys <= ~950 chars and no '..'. The underlying s3-proxy
*does* support prefix listing (GET on the bucket root with a `prefix` param, `_handle_list`) — this
`Storage` class just doesn't wrap that endpoint today (nothing here has needed it yet; homes.py's
snapshot index and the site-source layout below both use their own small index/manifest objects
instead of a bucket listing).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
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


def site_source_key(site_id: str, version: int) -> str:
    return f"sites/{site_id}/source/{version}.tar.zst"


def site_source_latest_key(site_id: str) -> str:
    return f"sites/{site_id}/source/latest.json"


# ---------------------------------------------------------------- tar.zst directory sync
#
# Promoted out of homes.py, which established this exact pattern first (sync a whole directory
# tree through this module's single-object PUT/GET interface, PLAN.md's Sites "Live editing"
# section §"S3 object shape") — sites/source.py is the second real call site. homes.py still
# defines its own `_tar_dir`/`_untar_bytes` too; not worth a disruptive rename of a shipped module
# just to import these instead, but any third caller should import from here rather than adding a
# third copy.


def tar_dir(src: Path, *, exclude: tuple[str, ...] = ()) -> bytes:
    """Deterministic-enough tar.zst of `src`'s contents (not `src` itself) as bytes, via a temp
    file — `tarfile` has no zstd filter, so we shell out to `tar` (present in both the worker
    image and local dev macOS) rather than pull in a zstd binding."""
    with tempfile.NamedTemporaryFile(suffix=".tar.zst") as tmp:
        argv = ["tar", "--zstd", "-cf", tmp.name, "-C", str(src)]
        for e in exclude:
            argv += ["--exclude", e]
        argv.append(".")
        subprocess.run(argv, check=True, capture_output=True, text=True)
        return Path(tmp.name).read_bytes()


def untar_bytes(data: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.zst") as tmp:
        tmp.write(data)
        tmp.flush()
        subprocess.run(["tar", "--zstd", "-xf", tmp.name, "-C", str(dest)], check=True, capture_output=True, text=True)
