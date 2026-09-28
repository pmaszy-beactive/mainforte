"""Triggers the mainforte-owned Jenkins jobs that provision/destroy a site's container, and the
callback handling for when that job reports back.

Uses `jenkins_ssh.py`'s `trigger_jenkins_build` unchanged (already generic — see that module and
`db_settings.py`'s `BASTION_JENKINS_FIELDS` comment for why these are new, mainforte-owned job
names rather than a reuse of beactive-claw's `website_builder_jenkins_job`). The Jenkins job itself
is pipeline-as-code living on the Jenkins server, outside both repos: it clones the mainforte site
starter template, builds/starts the container, and POSTs back to `routes.py`'s
`/api/sites/{id}/callback` with progress/completion.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from mainforte.events import emit

logger = logging.getLogger("mainforte.sites.provisioning")


def trigger_provision(db: Session, *, site, api_key: str, correlation_id: str | None = None) -> None:
    """Fires the site-provision Jenkins job. Fire-and-forget, same as the worker-pool reconciler's
    use of `trigger_jenkins_build` — the job reports progress/completion asynchronously via the
    callback route, not via this call's return value. If Jenkins isn't configured (dev, or before
    an admin fills in the Settings tab), records that as the site's error rather than raising, so
    site creation itself never 500s on missing infra config."""
    from mainforte.config import get_settings
    from mainforte.db_settings import get_bastion_jenkins_config
    from mainforte.jenkins_ssh import trigger_jenkins_build
    from mainforte.sites.service import mark_error

    settings = get_settings()
    s = get_bastion_jenkins_config(db)
    job_name = getattr(s, "jenkins_site_provision_job", None)
    if not job_name:
        logger.warning("jenkins.site_provision_job not configured — site %s left in provisioning", site.id)
        mark_error(db, site, error="jenkins.site_provision_job not configured")
        emit(db, "site.error", ws_id=site.ws_id, actor=("system", None), correlation_id=correlation_id,
             payload={"site_id": site.id, "message": "not_configured"})
        return

    callback_url = f"{settings.api_url}/api/sites/{site.id}/callback"

    # Per-site Postgres role + database, created by the Jenkins job itself (via
    # /etc/backbone/scripts/bootstrap-db.sh, called from deploy-site.sh) before it starts the
    # container -- mainforte's backend never runs bootstrap-db.sh itself. DB_NAME/DB_USER are
    # deterministic from the site's slug (readable in a psql prompt without a lookup, and never
    # stored). DB_PASSWORD is generated here and handed to the job as a param, same as before --
    # but unlike container_api_key_hash's one-way hash, the *plaintext* is also persisted
    # (Fernet-encrypted) on the Site row, because the persona's DB tools need to reconstruct a
    # live DATABASE_URL to this site's database on demand (lookups/queries), not just once at
    # provision time. Postgres itself still verifies every connection; encryption here is only to
    # keep it off disk in plaintext, the same posture bastion.ssh_key already uses. Persisted
    # *before* trigger_jenkins_build so it's saved even if the Jenkins call itself fails partway
    # through (a retry would otherwise mint a second password bootstrap-db.sh has no record of).
    from mainforte.auth.passwords import new_token
    from mainforte.crypto import encrypt

    db_name = f"site_{site.slug}".replace("-", "_")
    db_user = db_name
    db_password = new_token()
    site.db_password_encrypted = encrypt(db_password)
    db.add(site)
    db.commit()

    result = trigger_jenkins_build(db, job_name, {
        "SITE_ID": site.id,
        "SUBDOMAIN": site.slug,
        "CONTAINER_API_KEY": api_key,
        "CALLBACK_URL": callback_url,
        "TEMPLATE": "default",
        "DB_NAME": db_name,
        "DB_USER": db_user,
        "DB_PASSWORD": db_password,
        "DB_ADMIN_USER": getattr(s, "db_admin_user", None) or "",
        "DB_ADMIN_PASSWORD": getattr(s, "db_admin_password", None) or "",
    })
    if result.get("ok"):
        emit(db, "site.provisioning", ws_id=site.ws_id, actor=("system", None), correlation_id=correlation_id,
             payload={"site_id": site.id})
    else:
        mark_error(db, site, error=f"jenkins trigger failed: {result.get('reason')}: {result.get('error', '')}")
        emit(db, "site.error", ws_id=site.ws_id, actor=("system", None), correlation_id=correlation_id,
             payload={"site_id": site.id, "message": result.get("reason")})


def site_database_url(db: Session, site) -> str | None:
    """Reconstructs this site's own DATABASE_URL from its persisted, encrypted password plus its
    deterministic DB_NAME/DB_USER -- for the persona's DB-lookup/DB-modify tools (PLAN.md's "Live
    editing" section) to connect to a site's database on demand, the same connection target
    deploy-site.sh handed the container at provision time. Returns None if this site was never
    provisioned with a password (e.g. it errored before trigger_provision persisted one)."""
    from mainforte.crypto import decrypt
    from mainforte.db_settings import get_bastion_jenkins_config

    if not site.db_password_encrypted:
        return None
    s = get_bastion_jenkins_config(db)
    db_host = getattr(s, "db_sites_host", None) or "db.activeaidemo.com"
    db_port = getattr(s, "db_sites_port", None) or "5432"
    db_name = f"site_{site.slug}".replace("-", "_")
    db_user = db_name
    db_password = decrypt(site.db_password_encrypted)
    return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


def trigger_destroy(db: Session, *, site, correlation_id: str | None = None) -> None:
    from mainforte.db_settings import get_bastion_jenkins_config
    from mainforte.jenkins_ssh import trigger_jenkins_build

    s = get_bastion_jenkins_config(db)
    job_name = getattr(s, "jenkins_site_destroy_job", None)
    if not job_name or not site.container_name:
        logger.warning("skipping destroy for site %s: job=%s container=%s", site.id, job_name, site.container_name)
        return
    # Same deterministic DB_NAME/DB_USER derivation as trigger_provision, so the destroy job can
    # drop the site's database + role (not just stop the container) -- see PLAN.md's "Per-site
    # Postgres provisioning" > Teardown symmetry. Admin creds passed the same way as on provision;
    # exact drop mechanism (dedicated script vs. inline psql) is decided at Jenkins-job-authoring
    # time, outside this repo.
    db_name = f"site_{site.slug}".replace("-", "_")
    trigger_jenkins_build(db, job_name, {
        "SITE_ID": site.id,
        "CONTAINER_NAME": site.container_name,
        "DB_NAME": db_name,
        "DB_USER": db_name,
        "DB_ADMIN_USER": getattr(s, "db_admin_user", None) or "",
        "DB_ADMIN_PASSWORD": getattr(s, "db_admin_password", None) or "",
    })
    emit(db, "site.destroyed", ws_id=site.ws_id, actor=("system", None), correlation_id=correlation_id,
         payload={"site_id": site.id})


def handle_callback(db: Session, site, payload: dict[str, Any]) -> None:
    """Applies one progress/completion report from the Jenkins job. `payload["event"]` is one of
    "log" (forwarded onto the generic build.* namespace — see events/types.py's Site comment),
    "ready" (container is up: needs container_name + dev_port), or "error" (needs message — stored
    as Site.last_error, never returned as-is to the user; see service.py's docstring)."""
    from mainforte.sites.service import mark_error, mark_ready

    event = payload.get("event")
    if event == "log":
        emit(db, "build.log", ws_id=site.ws_id, actor=("system", None), correlation_id=None,
             payload={"site_id": site.id, "line": payload.get("line", "")})
        return
    if event == "ready":
        container_name = payload.get("container_name")
        dev_port = payload.get("dev_port")
        if not container_name or not dev_port:
            mark_error(db, site, error=f"malformed ready callback: {payload!r}")
            emit(db, "site.error", ws_id=site.ws_id, actor=("system", None), correlation_id=None,
                 payload={"site_id": site.id, "message": "malformed_callback"})
            return
        mark_ready(db, site, container_name=container_name, dev_port=int(dev_port))
        emit(db, "build.succeeded", ws_id=site.ws_id, actor=("system", None), correlation_id=None,
             payload={"site_id": site.id})
        emit(db, "site.ready", ws_id=site.ws_id, actor=("system", None), correlation_id=None,
             payload={"site_id": site.id})
        return
    if event == "error":
        message = str(payload.get("message", "unknown error"))
        mark_error(db, site, error=message)
        emit(db, "build.failed", ws_id=site.ws_id, actor=("system", None), correlation_id=None,
             payload={"site_id": site.id})
        emit(db, "site.error", ws_id=site.ws_id, actor=("system", None), correlation_id=None,
             payload={"site_id": site.id, "message": "build_failed"})
        return
    logger.warning("unknown callback event %r for site %s", event, site.id)
