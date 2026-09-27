"""Admin-editable config/secrets stored in the DB (Setting table), overlaid on top of
config.py's env-based fallback. Distinct from config.py's get_settings(): that one is a
process-wide @lru_cache singleton with 40+ call sites, so making it DB-aware would mean
solving cache invalidation everywhere for callers that don't need DB-stored config. This
module is read fresh per call (Setting rows are cheap to query) and used only where DB
overrides are actually needed -- currently just jenkins_ssh.py's bastion/Jenkins fields.

Ships as ready-to-use (env-configured) until an admin fills in the Settings tab: a Setting
row present for a key overrides the env value; absent, the config.py/env value is used.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from mainforte.config import get_settings
from mainforte.crypto import decrypt, encrypt
from mainforte.db.models import Setting

BASTION_JENKINS_FIELDS: dict[str, tuple[str, bool]] = {
    # Setting key -> (output attr name, is_secret)
    "bastion.host": ("bastion_host", False),
    "bastion.port": ("bastion_port", False),
    "bastion.username": ("bastion_username", False),
    "bastion.ssh_key": ("bastion_ssh_key", True),
    "jenkins.host": ("jenkins_host", False),
    "jenkins.port": ("jenkins_port", False),
    "jenkins.username": ("jenkins_username", False),
    "jenkins.ssh_key": ("jenkins_ssh_key", True),
    "jenkins.provision_job": ("jenkins_provision_job", False),
    "jenkins.destroy_job": ("jenkins_destroy_job", False),
}

# output attr -> config.py/env fallback attr, where the name differs (the two SSH keys: the env
# fallback is still a file path, e.g. BASTION_SSH_KEY_PATH, so its content must be read from disk).
_ENV_FALLBACK_ATTR = {
    "bastion_ssh_key": "bastion_ssh_key_path",
    "jenkins_ssh_key": "jenkins_ssh_key_path",
}


def _fallback_value(attr: str) -> Any:
    s = get_settings()
    env_attr = _ENV_FALLBACK_ATTR.get(attr, attr)
    value = getattr(s, env_attr, None)
    if env_attr.endswith("_ssh_key_path") and value:
        from pathlib import Path

        return Path(value).read_text()
    return value


def get_bastion_jenkins_config(db: Session) -> SimpleNamespace:
    """DB-stored Setting rows override config.py/env; secret fields (the two SSH keys) are
    decrypted here so callers always get plaintext key material, never ciphertext or a path."""
    keys = list(BASTION_JENKINS_FIELDS)
    rows = {row.key: row.value for row in db.query(Setting).filter(Setting.key.in_(keys)).all()}

    out: dict[str, Any] = {}
    for setting_key, (attr, is_secret) in BASTION_JENKINS_FIELDS.items():
        row = rows.get(setting_key)
        if row is None:
            out[attr] = _fallback_value(attr)
            continue
        raw = row.get("v")
        out[attr] = decrypt(raw) if (is_secret and row.get("enc") and raw) else raw

    return SimpleNamespace(**out)


def set_bastion_jenkins_config(db: Session, updates: dict[str, Any]) -> None:
    """updates keys are the Setting keys in BASTION_JENKINS_FIELDS (e.g. "bastion.host"). A
    secret field with an empty/missing value is skipped (keeps whatever is already stored)."""
    for setting_key, value in updates.items():
        if setting_key not in BASTION_JENKINS_FIELDS:
            continue
        _, is_secret = BASTION_JENKINS_FIELDS[setting_key]
        if is_secret and not value:
            continue
        stored: dict[str, Any] = {"v": encrypt(value) if is_secret else value, "enc": is_secret}
        row = db.get(Setting, setting_key)
        if row:
            row.value = stored
        else:
            db.add(Setting(key=setting_key, value=stored))


def bastion_jenkins_status(db: Session) -> dict[str, Any]:
    """Masked view for the admin UI: plain fields returned as-is, secret fields reduced to
    whether a value is currently set (from DB or env fallback) -- never the value itself."""
    cfg = get_bastion_jenkins_config(db)
    out: dict[str, Any] = {}
    for setting_key, (attr, is_secret) in BASTION_JENKINS_FIELDS.items():
        value = getattr(cfg, attr, None)
        out[attr] = bool(value) if is_secret else value
    return out
