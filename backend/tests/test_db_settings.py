"""Unit coverage for db_settings.py: DB-stored Setting rows override config.py's env-based
fallback for bastion/Jenkins config, absent rows fall back to env, and the two SSH-key fields
round-trip through crypto.py's Fernet encrypt/decrypt. Hand-rolled fake DB (this repo's
established convention, see test_gmail_secrets.py) rather than a live Postgres.
"""
from __future__ import annotations

from mainforte.crypto import decrypt
from mainforte.db_settings import (
    bastion_jenkins_status,
    get_bastion_jenkins_config,
    set_bastion_jenkins_config,
)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_kw):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self):
        self.rows: dict[str, object] = {}

    def get(self, _model, key):
        return self.rows.get(key)

    def add(self, obj):
        self.rows[obj.key] = obj

    def query(self, _model):
        return _FakeQuery(list(self.rows.values()))


def test_falls_back_to_env_when_no_db_rows(monkeypatch):
    from mainforte import db_settings as mod

    monkeypatch.setattr(mod, "get_settings", lambda: type(
        "S", (), {"bastion_host": "env-bastion", "bastion_port": 22, "bastion_username": None,
                   "bastion_ssh_key_path": None, "jenkins_host": "env-jenkins", "jenkins_port": None,
                   "jenkins_username": None, "jenkins_ssh_key_path": None,
                   "jenkins_provision_job": None, "jenkins_destroy_job": None},
    )())

    db = _FakeDB()
    cfg = get_bastion_jenkins_config(db)
    assert cfg.bastion_host == "env-bastion"
    assert cfg.jenkins_host == "env-jenkins"


def test_db_row_overrides_env_fallback(monkeypatch):
    from mainforte import db_settings as mod

    monkeypatch.setattr(mod, "get_settings", lambda: type(
        "S", (), {"bastion_host": "env-bastion", "bastion_port": 22, "bastion_username": None,
                   "bastion_ssh_key_path": None, "jenkins_host": None, "jenkins_port": None,
                   "jenkins_username": None, "jenkins_ssh_key_path": None,
                   "jenkins_provision_job": None, "jenkins_destroy_job": None},
    )())

    db = _FakeDB()
    set_bastion_jenkins_config(db, {"bastion.host": "db-bastion"})
    cfg = get_bastion_jenkins_config(db)
    assert cfg.bastion_host == "db-bastion"


def test_secret_field_round_trips_through_encryption():
    db = _FakeDB()
    set_bastion_jenkins_config(db, {"bastion.ssh_key": "-----BEGIN KEY-----\nsecret\n-----END KEY-----"})

    row = db.rows["bastion.ssh_key"]
    assert row.value["enc"] is True
    assert row.value["v"] != "-----BEGIN KEY-----\nsecret\n-----END KEY-----"
    assert decrypt(row.value["v"]) == "-----BEGIN KEY-----\nsecret\n-----END KEY-----"

    cfg = get_bastion_jenkins_config(db)
    assert cfg.bastion_ssh_key == "-----BEGIN KEY-----\nsecret\n-----END KEY-----"


def test_empty_secret_update_keeps_existing_value():
    db = _FakeDB()
    set_bastion_jenkins_config(db, {"bastion.ssh_key": "original-key"})
    set_bastion_jenkins_config(db, {"bastion.ssh_key": ""})

    cfg = get_bastion_jenkins_config(db)
    assert cfg.bastion_ssh_key == "original-key"


def test_status_masks_secret_fields():
    db = _FakeDB()
    set_bastion_jenkins_config(db, {"bastion.ssh_key": "some-key", "bastion.host": "h"})

    status = bastion_jenkins_status(db)
    assert status["bastion_ssh_key"] is True
    assert status["bastion_host"] == "h"
