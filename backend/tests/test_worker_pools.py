"""Tests for the two-pool agent-worker reconciler (mainforte.tasks.system): that the "full"
(chat,work,system) and "sandbox" (work-only) pools are tracked under non-overlapping
container_name prefixes, and that CELERY_QUEUES is only ever passed to Jenkins for the sandbox
pool -- the full pool relies on Dockerfile.worker's default and must never send an explicit
CELERY_QUEUES override that could accidentally narrow it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from mainforte.tasks.system import AGENT_WORKER_POOLS, _reconcile_pool


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
    db.settings["workers.desired.sandbox"] = MagicMock(value={"count": 1})
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
    db.settings["workers.desired"] = MagicMock(value={"count": 1})
    settings = MagicMock(jenkins_provision_job="provision-job")

    with patch("mainforte.jenkins_ssh.trigger_jenkins_build", return_value={"ok": True}) as trigger:
        with patch("mainforte.tasks.system.emit"):
            result = _reconcile_pool(db, settings, "full", AGENT_WORKER_POOLS["full"])

    assert result["action"] == "provision"
    assert trigger.call_count == 1
    _, _, params = trigger.call_args[0]
    assert "CELERY_QUEUES" not in params
