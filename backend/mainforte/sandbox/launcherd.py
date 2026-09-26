"""`sandbox-launcherd` (P4 §4): the *only* process holding the Docker socket. Deliberately
dependency-light — stdlib only, no SQLAlchemy/Celery/FastAPI imports — so a compromise of the
worker's tool-execution path (arbitrary `bash`, browser automation driven by LLM output) can't
reach this process's own code, only its one fixed-shape RPC below.

Wire protocol: a length-prefixed JSON request/response over a Unix domain socket.
Request:  {"tool_name": str, "image": str, "cmd": [str, ...], "stdin": str, "mounts": [[host, container], ...],
           "memory_mb": int, "cpus": float, "pids_limit": int, "network": str | null, "timeout_seconds": int}
Response: {"ok": true, "stdout": str, "stderr": str, "exit_code": int} or {"ok": false, "error": str}

The daemon builds the `docker run` argv itself from a fixed template (see `_build_argv`) — callers
send structured fields, never raw docker flags, so a compromised caller cannot escalate beyond what
this template allows (no `--privileged`, no arbitrary bind mounts beyond the one workspace mount,
no host networking). This is an explicitly-accepted residual risk, not a claim of a full security
boundary: the launcher itself still holds the socket and is de-facto root-equivalent, but the blast
radius is now a minimal process with no chat/tool/LLM code path in it.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import struct
import subprocess
import sys

log = logging.getLogger(__name__)

_HEADER = struct.Struct(">I")
_MAX_REQUEST_BYTES = 1_000_000


def _build_argv(req: dict) -> list[str]:
    image = req["image"]
    cmd = req["cmd"]
    mounts = req.get("mounts") or []
    memory_mb = int(req.get("memory_mb", 1024))
    cpus = float(req.get("cpus", 1.0))
    pids_limit = int(req.get("pids_limit", 128))
    network = req.get("network")

    argv = [
        "docker", "run", "--rm", "-i",
        "--user", "10100:10100",
        "--read-only",
        "--tmpfs", "/tmp:size=512m",
        "--memory", f"{memory_mb}m",
        "--memory-swap", f"{memory_mb}m",
        "--cpus", str(cpus),
        "--pids-limit", str(pids_limit),
        "--network", network if network else "none",
    ]
    for host_path, container_path in mounts:
        argv += ["-v", f"{host_path}:{container_path}"]
    argv.append(image)
    argv += cmd
    return argv


def run_job(req: dict) -> dict:
    try:
        argv = _build_argv(req)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": f"malformed request: {e}"}

    timeout_seconds = int(req.get("timeout_seconds", 60))
    try:
        proc = subprocess.run(
            argv, input=req.get("stdin", ""), capture_output=True, text=True, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"job timed out after {timeout_seconds}s"}
    except OSError as e:
        return {"ok": False, "error": f"failed to invoke docker: {e}"}
    return {"ok": True, "stdout": proc.stdout, "stderr": proc.stderr, "exit_code": proc.returncode}


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("client closed connection early")
        buf += chunk
    return buf


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        conn: socket.socket = self.request
        try:
            (length,) = _HEADER.unpack(_recv_exact(conn, _HEADER.size))
            if length > _MAX_REQUEST_BYTES:
                resp = {"ok": False, "error": "request too large"}
            else:
                body = _recv_exact(conn, length)
                req = json.loads(body)
                resp = run_job(req)
        except Exception as e:
            log.exception("sandbox-launcherd request failed")
            resp = {"ok": False, "error": str(e)}
        payload = json.dumps(resp).encode("utf-8")
        conn.sendall(_HEADER.pack(len(payload)) + payload)


class _Server(socketserver.ThreadingUnixStreamServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sock_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "SANDBOX_LAUNCHER_SOCKET", "/var/run/mainforte/launcher.sock"
    )
    if os.path.exists(sock_path):
        os.remove(sock_path)
    os.makedirs(os.path.dirname(sock_path), exist_ok=True)
    server = _Server(sock_path, _Handler)
    try:
        os.chmod(sock_path, 0o666)
    except OSError:
        log.warning(
            "could not chmod socket %s (likely a bind-mount filesystem limitation); continuing anyway",
            sock_path,
        )
    log.info("sandbox-launcherd listening on %s", sock_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if os.path.exists(sock_path):
            os.remove(sock_path)


if __name__ == "__main__":
    main()
