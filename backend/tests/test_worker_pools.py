"""Tests for the two-pool agent-worker reconciler (mainforte.tasks.system): that the "full"
(chat,work,system) and "sandbox" (work-only) pools are tracked under non-overlapping
container_name prefixes, and that CELERY_QUEUES is only ever passed to Jenkins for the sandbox
pool -- the full pool relies on Dockerfile.worker's default and must never send an explicit
CELERY_QUEUES override that could accidentally narrow it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from mainforte.db.base import utcnow
from mainforte.tasks.system import AGENT_WORKER_POOLS, __version__, _reconcile_pool, get_pool_desired_counts


def test_pool_prefixes_do_not_overlap():
    full_prefix = AGENT_WORKER_POOLS["full"]["prefix"]
    sandbox_prefix = AGENT_WORKER_POOLS["sandbox"]["prefix"]
    assert sandbox_prefix.startswith(full_prefix)
    assert AGENT_WORKER_POOLS["full"]["exclude_prefix"] == sandbox_prefix
    assert AGENT_WORKER_POOLS["sandbox"]["exclude_prefix"] is None


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_kw):
        return self

    def order_by(self, *_a, **_kw):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows
        self.settings = {}

    def get(self, _model, key):
        return self.settings.get(key)

    def query(self, _model):
        return _FakeQuery(self._rows)


def test_sandbox_pool_provision_sends_celery_queues():
    db = _FakeDB(rows=[])
    db.settings["workers.desired"] = MagicMock(value={"full": 0, "sandbox": 1})
    settings = MagicMock(jenkins_provision_job="provision-job")

    with patch("mainforte.jenkins_ssh.trigger_jenkins_build", return_value={"ok": True}) as trigger:
        with patch("mainforte.tasks.system.emit"):
            result = _reconcile_pool(db, settings, "sandbox", AGENT_WORKER_POOLS["sandbox"])

    assert result["action"] == "provision"
    assert trigger.call_count == 1
    _, _, params = trigger.call_args[0]
    assert params["CELERY_QUEUES"] == "work"


def test_full_pool_provision_omits_celery_queues():
    db = _FakeDB(rows=[])
    db.settings["workers.desired"] = MagicMock(value={"full": 1, "sandbox": 0})
    settings = MagicMock(jenkins_provision_job="provision-job")

    with patch("mainforte.jenkins_ssh.trigger_jenkins_build", return_value={"ok": True}) as trigger:
        with patch("mainforte.tasks.system.emit"):
            result = _reconcile_pool(db, settings, "full", AGENT_WORKER_POOLS["full"])

    assert result["action"] == "provision"
    assert trigger.call_count == 1
    _, _, params = trigger.call_args[0]
    assert "CELERY_QUEUES" not in params


def test_get_pool_desired_counts_merged_row():
    db = _FakeDB(rows=[])
    db.settings["workers.desired"] = MagicMock(value={"full": 2, "sandbox": 3})
    assert get_pool_desired_counts(db) == {"full": 2, "sandbox": 3}


def test_get_pool_desired_counts_falls_back_to_legacy_sandbox_key():
    db = _FakeDB(rows=[])
    db.settings["workers.desired"] = MagicMock(value={"count": 2})  # pre-merge "full" row
    db.settings["workers.desired.sandbox"] = MagicMock(value={"count": 3})  # pre-merge "sandbox" row
    assert get_pool_desired_counts(db) == {"full": 2, "sandbox": 3}


def test_get_pool_desired_counts_defaults_when_no_rows():
    db = _FakeDB(rows=[])
    assert get_pool_desired_counts(db) == {"full": 1, "sandbox": 0}


def _worker(name, *, version, status="online", current_job=None):
    w = MagicMock()
    w.container_name = name
    w.version = version
    w.status = status
    w.current_job = current_job
    w.last_heartbeat = utcnow()
    return w


def test_recently_provisioned_outdated_worker_is_not_drained():
    """A worker that just heartbeated for the first time, before its version tag caught up, must
    not be classified outdated -- doing so immediately drains/destroys it and the replacement
    repeats the same race forever (the churn bug: see reconcile_agent_workers' docstring)."""
    stale_worker = _worker("mainforte-agent-worker-2", version="0.1.50")  # in its grace window
    current_worker = _worker("mainforte-agent-worker-3", version=__version__)
    db = _FakeDB(rows=[stale_worker, current_worker])
    db.settings["workers.desired"] = MagicMock(value={"full": 2, "sandbox": 0})
    settings = MagicMock(jenkins_provision_job="provision-job", jenkins_destroy_job="destroy-job")

    with patch("mainforte.tasks.system._recently_provisioned_names", return_value={"mainforte-agent-worker-2"}):
        with patch("mainforte.jenkins_ssh.trigger_jenkins_build") as trigger:
            with patch("mainforte.tasks.system.emit"):
                result = _reconcile_pool(db, settings, "full", AGENT_WORKER_POOLS["full"])

    assert result["action"] == "none"
    trigger.assert_not_called()


def test_outdated_worker_past_grace_window_is_drained():
    """Once the grace window has expired, an outdated worker is fair game for drain again --
    the fix only defers the destroy branches, it never grants permanent immunity."""
    stale_worker = _worker("mainforte-agent-worker-2", version="0.1.50")
    current_worker_a = _worker("mainforte-agent-worker-3", version=__version__)
    current_worker_b = _worker("mainforte-agent-worker-4", version=__version__)
    db = _FakeDB(rows=[stale_worker, current_worker_a, current_worker_b])
    db.settings["workers.desired"] = MagicMock(value={"full": 2, "sandbox": 0})
    settings = MagicMock(jenkins_provision_job="provision-job", jenkins_destroy_job="destroy-job")

    with patch("mainforte.tasks.system._recently_provisioned_names", return_value=set()):
        with patch("mainforte.tasks.system.drain_worker") as drain:
            with patch("mainforte.jenkins_ssh.trigger_jenkins_build") as trigger:
                with patch("mainforte.tasks.system.emit"):
                    result = _reconcile_pool(db, settings, "full", AGENT_WORKER_POOLS["full"])

    assert result["action"] == "drain"
    assert result["container_name"] == "mainforte-agent-worker-2"
    drain.assert_called_once_with(db, "mainforte-agent-worker-2", AGENT_WORKER_POOLS["full"]["queues"])
    trigger.assert_not_called()  # drain_worker uses celery control, not Jenkins
