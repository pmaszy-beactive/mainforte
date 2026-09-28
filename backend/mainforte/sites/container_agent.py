"""Reaches ONE already-running, externally-provisioned site container to read/write files or tail
logs — the piece `tasks/work.py`'s `run_tool`/`sandbox.get_sandbox()` deliberately isn't used for
(see `sites/__init__.py`'s docstring: that machinery creates a fresh throwaway workspace per call,
the wrong shape for repeatedly editing one long-lived container's own filesystem).

v1: plain **local** `docker exec <container_name> ...` — not a bastion/Jenkins-host SSH hop. This
code runs inside a mainforte Celery worker (`personas/router.py`'s chat-tool dispatch or
`tasks/work.py`'s stage-tool dispatch, both Celery tasks — see those modules), and those workers
are themselves deployed onto the *same backbone deploy host* site containers run on
(`scripts/deploy-worker.sh` — "Called from the Jenkins job with the mainforte repo already checked
out", i.e. `docker run` on that same host, same Docker network as everything else Jenkins deploys
there). So the worker container reaching a site container is a same-host, same-network `docker
exec` — going bastion→Jenkins-CLI→that same host (what `jenkins_ssh.py` does) would just be
tunnelling back to where the caller already is. `ssh localhost` (rather than mounting the Docker
socket) keeps the "run one shell command on the docker host" shape identical to before, so
`_docker_exec`/`read_file`/`write_file`/etc. below didn't need to change.

**Single-host assumption, explicit**: this only works because there is currently exactly one
backbone deploy host running both the worker pool and site containers. If workers and sites are
ever split across multiple hosts (e.g. a dedicated sites host, or horizontal scaling), `localhost`
stops being correct and this needs to go back to addressing a *specific* host per site (e.g.
`Site.host` recording which deploy host it landed on) — likely via the same bastion/Jenkins-SSH
mechanism this replaced, not a new one. Not needed today; flagged here so it's not a silent
landmine later.

Path safety mirrors `tools/sandbox_exec.py`'s `_resolve`: every path is resolved relative to the
container's fixed app root and rejected if it would escape it, reimplemented natively rather than
importing beactive-claw's `assertSafeWorkspacePath` (per PLAN.md's decision to keep this dependency
native to mainforte).
"""
from __future__ import annotations

import shlex
import subprocess

from mainforte.db.models import Site

logger_name = "mainforte.sites.container_agent"

# Fixed app root inside every site container — set by the mainforte site starter template, not
# configurable per-site. All file tool paths are relative to this.
APP_ROOT = "/app"


class ContainerAgentError(RuntimeError):
    pass


def _assert_safe_rel_path(path: str) -> str:
    """Rejects any path that isn't a simple relative path under APP_ROOT — no absolute paths,
    no `..` segments, no null bytes. Returns the path unchanged if safe."""
    if not path or path.startswith("/") or "\x00" in path:
        raise ContainerAgentError(f"invalid path: {path!r}")
    parts = path.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        raise ContainerAgentError(f"path escapes app root: {path!r}")
    return path


def _run_on_host(db, remote_cmd: str, *, timeout: int = 30) -> subprocess.CompletedProcess:
    """Runs `remote_cmd` against the local Docker daemon — `db` is accepted but unused today (kept
    so callers/signature don't change if a future multi-host split needs it again to look up which
    host a given Site lives on; see the module docstring's "Single-host assumption" note). Goes
    through `ssh localhost` (as this worker's own user) rather than `subprocess.run(["docker",
    "exec", ...])` directly so the docker CLI invocation shape — and therefore `_docker_exec`'s
    caller-facing behavior (stdout/stderr capture, timeout, non-zero exit -> ContainerAgentError)
    — is unchanged from the previous bastion-hop implementation; swap this one function's body for
    a direct subprocess call if the extra SSH hop through localhost turns out to be unnecessary
    overhead in practice."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "localhost", remote_cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")


def _docker_exec(db, site: Site, inner_cmd: str, *, timeout: int = 30) -> subprocess.CompletedProcess:
    if not site.container_name:
        raise ContainerAgentError("site has no container yet")
    remote_cmd = f"docker exec {shlex.quote(site.container_name)} /bin/sh -c {shlex.quote(inner_cmd)}"
    result = _run_on_host(db, remote_cmd, timeout=timeout)
    if result.returncode != 0:
        raise ContainerAgentError((result.stderr or result.stdout or "command failed")[:2000])
    return result


def read_file(db, site: Site, path: str) -> str:
    rel = _assert_safe_rel_path(path)
    full = f"{APP_ROOT}/{rel}"
    result = _docker_exec(db, site, f"cat {shlex.quote(full)}")
    return result.stdout[:200_000]


def write_file(db, site: Site, path: str, content: str) -> None:
    rel = _assert_safe_rel_path(path)
    full = f"{APP_ROOT}/{rel}"
    # base64 round-trip avoids any quoting/escaping hazard from the file content itself reaching
    # the remote shell verbatim — content is arbitrary LLM-authored source code.
    import base64

    b64 = base64.b64encode(content.encode()).decode()
    inner = f"mkdir -p $(dirname {shlex.quote(full)}) && echo {shlex.quote(b64)} | base64 -d > {shlex.quote(full)}"
    _docker_exec(db, site, inner)


def list_dir(db, site: Site, path: str = ".") -> list[str]:
    rel = _assert_safe_rel_path(path) if path != "." else "."
    full = f"{APP_ROOT}/{rel}" if rel != "." else APP_ROOT
    result = _docker_exec(db, site, f"ls -1p {shlex.quote(full)}")
    return sorted(line for line in result.stdout.splitlines() if line)


def read_logs(db, site: Site, *, lines: int = 200) -> str:
    if not site.container_name:
        raise ContainerAgentError("site has no container yet")
    remote_cmd = f"docker logs --tail {int(lines)} {shlex.quote(site.container_name)}"
    result = _run_on_host(db, remote_cmd, timeout=20)
    return (result.stdout + result.stderr)[-20_000:]


# ---------------------------------------------------------------- bulk sync (sites/source.py)
#
# The functions above are per-file, live-`docker exec` operations — still used for one-off reads
# (e.g. an ops/debug peek) but no longer how a chat turn's edits reach the container; see
# sites/source.py's module docstring and PLAN.md's "Live editing: revised design". These two are
# the bulk counterpart: ship a whole validated local directory in one shot, then confirm the
# process came back up.


def docker_cp_in(db, site: Site, local_dir, *, exclude: tuple[str, ...] = ()) -> None:
    """`docker cp`s the contents of `local_dir` (a turn's validated scratch checkout — see
    sites/source.py's TurnScratch) into the container's APP_ROOT, replacing whatever's already
    there path-for-path. `docker cp` has no `--exclude`, so `exclude` (e.g. node_modules) is
    honored by copying a pruned tmp mirror rather than local_dir itself — `docker cp` also has no
    partial-overlay mode (copying a directory onto an existing one merges, it doesn't delete files
    that no longer exist locally, which is what we want here: a file the LLM deleted from scratch
    should disappear from the container too). We handle deletion by first clearing APP_ROOT's
    tracked source (everything except the excluded, install-time-only dirs) inside the container,
    then copying the fresh tree in — both steps must succeed or this raises and the caller
    (source.ship_to_container) must not proceed to commit_turn.
    """
    import shutil
    import tempfile
    from pathlib import Path

    if not site.container_name:
        raise ContainerAgentError("site has no container yet")

    local_dir = Path(local_dir)
    container = shlex.quote(site.container_name)

    # Clear everything under APP_ROOT except the excluded dirs (node_modules etc.), so a
    # locally-deleted file actually disappears from the container instead of lingering forever.
    # NOTE: the second `-exec` clause must NOT repeat `-mindepth 0` here — find applies mindepth
    # per-expression-evaluation, not just to the initial descent, so a stray `-mindepth 0` on this
    # branch would override the outer `-mindepth 1` and make APP_ROOT itself (depth 0) match too,
    # rm -rf'ing the app root directory before docker cp gets a chance to write into it. Verified
    # by hand against a scratch dir before landing this — see the fix in this same commit.
    prune_clause = " -o ".join(f"-name {shlex.quote(e)}" for e in exclude) or "-false"
    clear_cmd = (
        f"find {shlex.quote(APP_ROOT)} -mindepth 1 -maxdepth 1 "
        f"\\( {prune_clause} \\) -prune -o -exec rm -rf {{}} + 2>/dev/null; true"
    )
    _docker_exec(db, site, clear_cmd, timeout=60)

    # Stage a pruned mirror (docker cp has no --exclude) so node_modules/.git/dist/build never
    # transit even temporarily — cheap since these are hardlinks where the platform supports it,
    # a real copy otherwise.
    with tempfile.TemporaryDirectory() as tmp:
        mirror = Path(tmp) / "src"

        def _ignore(dirpath: str, names: list[str]) -> set[str]:
            return {n for n in names if n in exclude}

        shutil.copytree(local_dir, mirror, ignore=_ignore)
        # Trailing "/." copies the *contents* of mirror into APP_ROOT, not mirror itself as a
        # subdirectory — same convention `cp -r src/. dst` uses.
        cmd = ["docker", "cp", f"{mirror}/.", f"{site.container_name}:{APP_ROOT}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise ContainerAgentError((result.stderr or result.stdout or "docker cp failed")[:2000])


def tail_logs_for_errors(db, site: Site, *, settle_seconds: float = 3.0) -> str | None:
    """Gives the container's watched process (`node --watch` per site-template's dev.sh) a moment
    to notice the copied files and restart, then tails recent logs for a crash signature. Returns
    None if things look fine, or the raw tail (caller decides what to do with it — never shown
    as-is to the user) if it looks like the process didn't come back up cleanly. This is a
    heuristic, not a health-check endpoint — good enough to catch "it crashed on boot", not a
    substitute for the container's own future health check if one gets added."""
    import time

    time.sleep(settle_seconds)
    tail = read_logs(db, site, lines=80)
    crash_markers = ("Error:", "Traceback", "ECONNREFUSED", "EADDRINUSE", "Cannot find module",
                      "SyntaxError", "unhandled", "UnhandledPromiseRejection", "process exited")
    if any(marker.lower() in tail.lower() for marker in crash_markers):
        return tail
    return None
