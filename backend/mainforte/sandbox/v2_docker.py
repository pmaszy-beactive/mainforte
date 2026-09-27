"""Isolation v2: a Unix-socket client to the privilege-separated `sandbox-launcherd` daemon
(`sandbox/launcherd.py`). The worker process never touches the Docker socket itself — it sends one
fixed-shape RPC and the daemon builds the actual `docker run` invocation.

Network policy: `--network=none` by default (no route to Postgres/Redis), with a per-tool-name
opt-in to `settings.sandbox_network_name` only for the tools that need it (`bash`,
`browser_navigate`, `browser_extract_text`) — everything else (`read_file`/`write_file`/`list_dir`/
`grep`/`glob`) never needs network access at all.
"""
from __future__ import annotations

import json
import socket
import struct
from pathlib import Path
from typing import Any

from mainforte.config import get_settings

_HEADER = struct.Struct(">I")

_NETWORKED_TOOLS = {"bash", "browser_navigate", "browser_extract_text"}


class DockerSandbox:
    def run(self, *, tool_name: str, tool_input: dict[str, Any], workspace: Path, ws_id: str,
            home_dir: Path, timeout_seconds: int, secrets: dict[str, str] | None = None) -> dict[str, Any]:
        settings = get_settings()
        spec = json.dumps({"tool": tool_name, "input": tool_input, "workspace": "/job",
                            "secrets": secrets or {}})
        req = {
            "tool_name": tool_name,
            "image": settings.sandbox_container_image,
            "cmd": ["python", "-m", "mainforte.tools.sandbox_exec"],
            "stdin": spec,
            "mounts": [[str(workspace), "/job"]],
            "memory_mb": settings.sandbox_container_memory_mb,
            "cpus": settings.sandbox_container_cpus,
            "pids_limit": settings.sandbox_container_pids_limit,
            "network": settings.sandbox_network_name if tool_name in _NETWORKED_TOOLS else None,
            "timeout_seconds": timeout_seconds,
        }
        resp = self._call(req, sock_path=settings.sandbox_launcher_socket, timeout_seconds=timeout_seconds)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "sandbox-launcherd request failed"))

        stdout = resp["stdout"]
        if resp["exit_code"] != 0 and not stdout.strip():
            raise RuntimeError(f"sandbox_exec exited {resp['exit_code']}: {resp['stderr'][-2000:]}")
        try:
            out = json.loads(stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            raise RuntimeError(f"sandbox_exec produced no valid JSON: stdout={stdout[-1000:]!r} "
                                f"stderr={resp['stderr'][-1000:]!r}") from None
        if not out.get("ok"):
            raise RuntimeError(out.get("error", "sandboxed tool failed with no error message"))
        return out["result"]

    @staticmethod
    def _call(req: dict, *, sock_path: str, timeout_seconds: int) -> dict:
        payload = json.dumps(req).encode("utf-8")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout_seconds + 10)
            conn.connect(sock_path)
            conn.sendall(_HEADER.pack(len(payload)) + payload)
            conn.shutdown(socket.SHUT_WR)

            (length,) = _HEADER.unpack(DockerSandbox._recv_exact(conn, _HEADER.size))
            body = DockerSandbox._recv_exact(conn, length)
            return json.loads(body)

    @staticmethod
    def _recv_exact(conn: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("sandbox-launcherd closed connection early")
            buf += chunk
        return buf
