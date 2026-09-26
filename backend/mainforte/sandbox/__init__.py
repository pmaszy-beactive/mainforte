"""Isolation backends for sandboxed tool execution (P4 §4). `_run_sandboxed` in `tasks/work.py`
keeps owning `stage_home`/`sync_home` orchestration; this package owns only "run this tool call
somewhere isolated" via a small `Protocol`, selected by `settings.sandbox_backend`."""
from __future__ import annotations

from typing import Any, Protocol


class Sandbox(Protocol):
    def run(self, *, tool_name: str, tool_input: dict[str, Any], workspace: Any, ws_id: str,
             home_dir: Any, timeout_seconds: int) -> dict[str, Any]:
        """Runs one tool call in isolation and returns the parsed `sandbox_exec` JSON envelope
        (`{"ok": bool, "result": ...}` or `{"ok": bool, "error": str}`). Raises on infrastructure
        failure (timeout, launcher unreachable, malformed output) — never returns a raised
        exception as `{"ok": False}`, mirroring today's `_run_sandboxed` contract so callers don't
        need to special-case backends."""
        ...


def get_sandbox() -> Sandbox:
    from mainforte.config import get_settings

    backend = get_settings().sandbox_backend
    if backend == "v2":
        from mainforte.sandbox.v2_docker import DockerSandbox

        return DockerSandbox()
    from mainforte.sandbox.v1_runuser import RunuserSandbox

    return RunuserSandbox()
