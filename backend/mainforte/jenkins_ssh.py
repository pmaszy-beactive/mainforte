"""SSH-through-bastion Jenkins CLI trigger (PLAN.md §1.8 worker-pool reconciler).

Mirrors backbone's deploy/flask-api/jenkins_manager.py and ActiveClaw's
lib/jenkins.ts: app server -> SSH ProxyCommand through the bastion (jump
host) -> Jenkins CLI `build <job> -p K=V` -> the Jenkins job runs
deploy-worker.sh on a node.

Bastion/Jenkins config (including SSH key material) is admin-editable and
DB-stored via db_settings.get_bastion_jenkins_config -- see that module's
docstring for why this isn't just get_settings(). SSH keys are encrypted at
rest and decrypted to plain text in memory here; we still copy each key to a
private 0600 temp file per call (never write the DB/env value to a fixed
path) so a single leaked temp file can't be replayed.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import tempfile
import traceback
from typing import Any

logger = logging.getLogger("mainforte.jenkins_ssh")

_SENSITIVE_PARAM_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "CONNECTION_STRING", "PRIVATE_KEY", "API_KEY")


def _redact_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """For LOG LINES only — never used to build the actual CLI args."""
    if not params:
        return params
    out = {}
    for key, value in params.items():
        upper = str(key).upper()
        out[key] = "***" if any(m in upper for m in _SENSITIVE_PARAM_MARKERS) else value
    return out


def _write_key_file(key_text: str) -> str:
    """Write key material to a private 0600 temp file for this call."""
    kf = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False)
    try:
        kf.write(key_text)
        kf.flush()
    finally:
        kf.close()
    os.chmod(kf.name, 0o600)
    return kf.name


def _cleanup_key_files(*paths: str | None) -> None:
    for p in paths:
        if p:
            try:
                os.unlink(p)
            except OSError:
                pass


def _is_configured(s) -> bool:
    return bool(
        s.bastion_host and s.bastion_ssh_key and s.jenkins_host
        and s.jenkins_provision_job and s.jenkins_destroy_job
    )


def _run_jenkins_ssh(s, remote_cmd: str, timeout: int) -> subprocess.CompletedProcess:
    bastion_key_file = _write_key_file(s.bastion_ssh_key)
    jenkins_key_file = _write_key_file(s.jenkins_ssh_key or s.bastion_ssh_key)

    try:
        bastion_target = f"{s.bastion_username}@{s.bastion_host}" if s.bastion_username else s.bastion_host
        proxy_cmd = (
            f"ssh -i {shlex.quote(bastion_key_file)} "
            f"-o StrictHostKeyChecking=no -o ConnectTimeout=10 "
            f"-p {int(s.bastion_port)} -W %h:%p {shlex.quote(bastion_target)}"
        )

        jenkins_target = f"{s.jenkins_username}@{s.jenkins_host}" if s.jenkins_username else s.jenkins_host
        cmd = [
            "ssh",
            "-i", jenkins_key_file,
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=yes",
            "-o", f"ProxyCommand={proxy_cmd}",
            "-p", str(int(s.jenkins_port or 22)),
            jenkins_target,
            remote_cmd,
        ]
        # encoding/errors explicit: Jenkins/SSH output is UTF-8 and can contain
        # multi-byte characters; text=True alone decodes with the process locale,
        # which falls back to ascii when LANG/LC_ALL are unset.
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    finally:
        _cleanup_key_files(bastion_key_file, jenkins_key_file)


def _jenkins_cli_cmd(cli_args: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in cli_args)


def _build_ssh_cli_args(job_name: str, params: dict[str, Any] | None = None, wait: bool = False) -> list[str]:
    args = ["build", job_name]
    if params:
        for key, value in params.items():
            args.extend(["-p", f"{key}={value}"])
    if wait:
        args.extend(["-s", "-v"])
    return args


def trigger_jenkins_build(db, job_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fire-and-forget: queues the build and returns once it's accepted."""
    from mainforte.db_settings import get_bastion_jenkins_config

    # DEBUG (investigating unexplained pool churn -- 2026-09-30): every single call into this
    # function, from ANY caller, with a full stack trace of who called it -- not just _provision's
    # own internal logging (tasks/system.py), since the mystery is precisely that Jenkins builds
    # keep firing with zero trace in _provision's own debug logs. If some OTHER code path (a worker
    # process executing a task we haven't considered, an admin route, anything) calls this function
    # directly, this line is the one place that will catch it regardless of which caller it is.
    caller_stack = "".join(traceback.format_stack(limit=8))
    logger.warning(
        "trigger_jenkins_build CALLED: job=%s params=%s caller_stack:\n%s",
        job_name, _redact_params(params), caller_stack,
    )

    s = get_bastion_jenkins_config(db)
    if not _is_configured(s):
        logger.warning("Jenkins not configured — skipping build trigger for %s", job_name)
        return {"ok": False, "reason": "not_configured"}

    # -v (verbose) without -s: still fire-and-forget (does not block on the build finishing), but
    # makes the Jenkins CLI print the queue item URL/number it was assigned, which -p-only output
    # does not include -- this is what lets a build's own console log/build number be traced back
    # to this exact trigger call.
    cli_args = _build_ssh_cli_args(job_name, params) + ["-v"]
    try:
        remote_cmd = _jenkins_cli_cmd(cli_args)
        result = _run_jenkins_ssh(s, remote_cmd, timeout=60)
        if result.returncode == 0:
            cli_output = (result.stdout or "").strip()
            logger.info(
                "Jenkins build queued: %s with params %s cli_output=%r",
                job_name, _redact_params(params), cli_output[:2000],
            )
            return {"ok": True, "job": job_name, "params": params, "cli_output": cli_output}
        err = (result.stderr or result.stdout or "")[:500]
        logger.error("Jenkins build trigger failed for %s: %s", job_name, err)
        return {"ok": False, "reason": "cli_failed", "error": err}
    except subprocess.TimeoutExpired:
        logger.error("Jenkins build trigger timed out for %s", job_name)
        return {"ok": False, "reason": "timeout"}
    except Exception as e:  # noqa: BLE001
        logger.error("Jenkins build trigger error for %s: %s", job_name, e)
        return {"ok": False, "reason": "exception", "error": str(e)}


def trigger_jenkins_build_sync(db, job_name: str, params: dict[str, Any] | None = None, timeout: int = 180) -> dict[str, Any]:
    """Blocks until the build finishes and returns its console output.

    Use only when the caller needs to parse the build's own stdout for a
    result (e.g. a newly-provisioned worker's identifying output) — the
    fire-and-forget trigger_jenkins_build has no way to report an outcome.
    """
    from mainforte.db_settings import get_bastion_jenkins_config

    s = get_bastion_jenkins_config(db)
    if not _is_configured(s):
        logger.warning("Jenkins not configured — skipping sync build trigger for %s", job_name)
        return {"ok": False, "reason": "not_configured", "output": ""}

    cli_args = _build_ssh_cli_args(job_name, params, wait=True)
    try:
        remote_cmd = _jenkins_cli_cmd(cli_args)
        result = _run_jenkins_ssh(s, remote_cmd, timeout=timeout)
        output = result.stdout or ""
        if result.returncode == 0:
            logger.info("Jenkins build completed: %s with params %s", job_name, _redact_params(params))
            return {"ok": True, "output": output, "reason": None}
        err = (result.stderr or output or "")[:1000]
        logger.error("Jenkins sync build failed for %s: %s", job_name, err)
        return {"ok": False, "reason": "build_failed", "output": output, "error": err}
    except subprocess.TimeoutExpired:
        logger.error("Jenkins sync build timed out for %s", job_name)
        return {"ok": False, "reason": "timeout", "output": ""}
    except Exception as e:  # noqa: BLE001
        logger.error("Jenkins sync build error for %s: %s", job_name, e)
        return {"ok": False, "reason": "exception", "error": str(e), "output": ""}
