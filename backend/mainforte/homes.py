"""S3 home staging/sync (P2 phase 6, PLAN.md §1.9): a user's persistent workspace files and
Chromium profile live in S3 as a manifest + two zstd tarballs, staged into a job's sandbox
directory before its tool calls run and synced back after (success or failure — always sync, per
PLAN.md's "our own insurance" framing).

Layout, exactly per PLAN.md §1.9:

    users/<uid>/home/manifest.json           {version, tarballs: {workspace, browser}, sizes, updated_at}
    users/<uid>/home/workspace.tar.zst       files, notes, skills state
    users/<uid>/home/browser.tar.zst         Chromium profile (cache dirs stripped)
    users/<uid>/home/snapshots/<ts>/...      last 3 daily copies (our own insurance)

`stage_home`/`sync_home` shell out to the system `tar` with `--zstd` (present in Dockerfile.worker
via the `zstd` apt package; confirmed installed there) rather than a Python zstd binding, since no
such binding is a project dependency and shelling out to `tar` is what every other subprocess
boundary in this codebase already does (`sandbox_exec.py`'s `_bash`).
"""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mainforte.storage import get_storage

log = logging.getLogger(__name__)

MANIFEST_VERSION = 1
MAX_SNAPSHOTS = 3
BROWSER_PROFILE_WARN_BYTES = 200 * 1024 * 1024  # PLAN.md's ~200MB target; log, don't fail

# Cache dirs stripped from the browser profile before archiving (PLAN.md: "cache dirs stripped").
_BROWSER_EXCLUDE = ("Cache", "Code Cache", "GPUCache", "DawnCache", "GrShaderCache")


def _home_prefix(user_id: str) -> str:
    return f"users/{user_id}/home"


def _manifest_key(user_id: str) -> str:
    return f"{_home_prefix(user_id)}/manifest.json"


def _tar_key(user_id: str, name: str) -> str:
    return f"{_home_prefix(user_id)}/{name}.tar.zst"


def _snapshot_key(user_id: str, ts: str, name: str) -> str:
    return f"{_home_prefix(user_id)}/snapshots/{ts}/{name}.tar.zst"


def _tar_dir(src: Path, *, exclude: tuple[str, ...] = ()) -> bytes:
    """Deterministic-enough tar.zst of `src`'s contents (not `src` itself) as bytes, via a temp
    file — `tarfile` has no zstd filter, so we shell out to `tar` (present in both the worker
    image and local dev macOS) rather than pull in a zstd binding."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".tar.zst") as tmp:
        argv = ["tar", "--zstd", "-cf", tmp.name, "-C", str(src)]
        for e in exclude:
            argv += ["--exclude", e]
        argv.append(".")
        subprocess.run(argv, check=True, capture_output=True, text=True)
        return Path(tmp.name).read_bytes()


def _untar_bytes(data: bytes, dest: Path) -> None:
    import tempfile

    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.zst") as tmp:
        tmp.write(data)
        tmp.flush()
        subprocess.run(["tar", "--zstd", "-xf", tmp.name, "-C", str(dest)], check=True, capture_output=True, text=True)


def stage_home(user_id: str, dest: Path) -> dict[str, Any]:
    """Downloads and extracts the user's home under `dest` (typically `/work/<job_id>/home`).
    Returns the manifest dict (empty-shaped if the user has no home yet — first job for a new
    user). Never raises for "no home yet"; does raise if a tarball the manifest names is missing
    (that's a real inconsistency, not an absent home)."""
    storage = get_storage()
    raw = storage.get(_manifest_key(user_id))
    if raw is None:
        (dest / "workspace").mkdir(parents=True, exist_ok=True)
        (dest / "browser").mkdir(parents=True, exist_ok=True)
        return {"version": MANIFEST_VERSION, "tarballs": {}, "sizes": {}, "updated_at": None}

    manifest = json.loads(raw)
    for name in ("workspace", "browser"):
        target = dest / name
        target.mkdir(parents=True, exist_ok=True)
        if name not in manifest.get("tarballs", {}):
            continue
        data = storage.get(_tar_key(user_id, name))
        if data is None:
            raise RuntimeError(f"home manifest for user {user_id} names {name!r} but the tarball is missing")
        _untar_bytes(data, target)
    return manifest


def sync_home(user_id: str, src: Path) -> dict[str, Any]:
    """Tars `src/workspace` and `src/browser` (each optional — a job that never touched the
    browser doesn't force a browser tarball into existence), uploads them, rotates the previous
    manifest+tarballs into a dated snapshot, and writes the new manifest. Always call this even
    when the job failed, per PLAN.md's "our own insurance" framing — whatever state exists is
    worth keeping."""
    storage = get_storage()
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%SZ")

    prev_raw = storage.get(_manifest_key(user_id))
    prev_manifest = json.loads(prev_raw) if prev_raw is not None else None

    # Fetch the previous tarball bytes BEFORE uploading any fresh ones — `_rotate_snapshot` needs
    # the old bytes, and `_tar_key` is the same live key the fresh upload below is about to
    # overwrite, so this must happen first or the "snapshot" would just be a copy of the new data.
    prev_tarball_data: dict[str, bytes] = {}
    if prev_manifest is not None:
        for name in prev_manifest.get("tarballs", {}):
            data = storage.get(_tar_key(user_id, name))
            if data is not None:
                prev_tarball_data[name] = data

    tarballs: dict[str, dict[str, int]] = {}
    for name, exclude in (("workspace", ()), ("browser", _BROWSER_EXCLUDE)):
        d = src / name
        if not d.is_dir() or not any(d.iterdir()):
            continue
        data = _tar_dir(d, exclude=exclude)
        if name == "browser" and len(data) > BROWSER_PROFILE_WARN_BYTES:
            log.warning("home sync: user %s browser profile tarball is %d bytes (target ~%d)",
                        user_id, len(data), BROWSER_PROFILE_WARN_BYTES)
        storage.put(_tar_key(user_id, name), data, "application/zstd")
        tarballs[name] = {"size": len(data)}

    if prev_manifest is not None:
        for name in prev_manifest.get("tarballs", {}):
            if name in tarballs:
                continue  # this sync produced a fresher copy already uploaded above
            if name in prev_tarball_data:
                tarballs[name] = prev_manifest["tarballs"][name]
        _rotate_snapshot(user_id, prev_manifest, prev_tarball_data, ts)

    manifest = {
        "version": MANIFEST_VERSION,
        "tarballs": tarballs,
        "sizes": {k: v["size"] for k, v in tarballs.items()},
        "updated_at": now.isoformat(),
    }
    storage.put(_manifest_key(user_id), json.dumps(manifest).encode(), "application/json")
    return manifest


def _rotate_snapshot(user_id: str, prev_manifest: dict[str, Any], prev_tarball_data: dict[str, bytes], ts: str) -> None:
    """Copies the *previous* manifest's tarballs (already fetched by the caller, before the fresh
    sync overwrote their live keys) into `snapshots/<ts>/`, records `ts` in the snapshot index,
    and trims to the last MAX_SNAPSHOTS. Best-effort: a snapshot failure must never block the real
    sync from completing.

    `Storage` has no list/prefix-scan (backbone's s3-proxy doesn't expose one — see storage.py),
    so snapshot discovery relies on this small index object rather than a bucket listing."""
    storage = get_storage()
    try:
        for name, data in prev_tarball_data.items():
            storage.put(_snapshot_key(user_id, ts, name), data, "application/zstd")
        storage.put(f"{_home_prefix(user_id)}/snapshots/{ts}/manifest.json",
                    json.dumps(prev_manifest).encode(), "application/json")

        index_key = f"{_home_prefix(user_id)}/snapshots/_index.json"
        raw = storage.get(index_key)
        index: list[str] = json.loads(raw) if raw is not None else []
        index.append(ts)
        stale, index = index[:-MAX_SNAPSHOTS], index[-MAX_SNAPSHOTS:]
        for old_ts in stale:
            storage.delete(_snapshot_key(user_id, old_ts, "workspace"))
            storage.delete(_snapshot_key(user_id, old_ts, "browser"))
            storage.delete(f"{_home_prefix(user_id)}/snapshots/{old_ts}/manifest.json")
        storage.put(index_key, json.dumps(index).encode(), "application/json")
    except Exception:
        log.exception("home sync: snapshot rotation failed for user %s (sync itself still proceeds)", user_id)
