#!/bin/bash
# deploy-worker.sh — deploy one pooled mainforte agent worker container.
#
# Workers are interchangeable and have no inbound HTTP: unlike a web/API
# deploy, there is no HAProxy site, no domain, and no health-check wait
# here. Liveness is the AgentWorker DB heartbeat (worker_heartbeat(),
# mainforte/tasks/system.py) — the pool UI polls that table directly, not
# a port on this container.
#
# Called from the Jenkins job with the mainforte repo already checked out
# into the current directory (standard Jenkins workspace behavior).
#
# Params (Jenkins job) — must match what _reconcile_pool (tasks/system.py)
# actually sends via trigger_jenkins_build:
#   WORKER_NAME    — this worker's unique container/identity name, e.g.
#                     mainforte-agent-worker-3 or mainforte-agent-worker-sandbox-1
#   CELERY_QUEUES  — optional; set only for the sandbox pool (celery queue
#                     override). Omitted entirely for the full pool, which
#                     relies on Dockerfile.worker's default queue set.
#   API_URL        — backend API URL the worker talks to. Sent by the
#                     reconciler from the admin-editable worker.api_url DB
#                     setting (falls back to this environment's FRONTEND_URL
#                     if unset — see db_settings.py).
#
# Env this script expects to already be present on the Jenkins/deploy host
# (same variables backbone's own deploy-v1.sh reads there — never passed in
# by the caller, never typed into chat):
#   DATABASE_URL          — mainforte has its own dedicated Postgres (unlike
#                            Redis/RabbitMQ below, it is not backbone-shared),
#                            so this is just forwarded into the container.
#   POSTGRES_ADMIN_USER/PASS   — backbone's admin Postgres creds, used only to
#                            read (never write) deploy_app_state for the
#                            already-provisioned redis_db/rabbit_pass. Same
#                            creds deploy-v1.sh's own _pg_query uses.
#   REDIS_HOSTNAME, RABBIT_HOSTNAME  — optional; override the universal
#                            redis.<domain>/rmq.<domain> hostnames, exactly
#                            like deploy-v1.sh's REDIS_UNIVERSAL_HOST/
#                            RABBIT_UNIVERSAL_HOST.
#   BACKBONE_BASE_DOMAIN, REDIS_PORT  — optional; same defaults as deploy-v1.sh
#                            (activeaidemo.com, 7027).
#
# Redis/RabbitMQ are backbone-multiplexed resources: this app's slot
# (redis_db, rabbit_vhost/user/pass) was already provisioned by backbone's
# own deploy-v1.sh for the main mainforte app deploy. Workers must reuse that
# same slot — never create a new one — so this script only SELECTs from
# deploy_app_state, mirroring deploy-v1.sh's IS_WORKER=true read-only path
# (see backbone/deploy/scripts/deploy-v1.sh, ~line 7150 and ~line 7330).
set -euo pipefail

: "${WORKER_NAME:?WORKER_NAME is required}"
: "${API_URL:?API_URL is required}"
CELERY_QUEUES="${CELERY_QUEUES:-}"

MAINFORTE_SLUG="${MAINFORTE_SLUG:-mainforte}"

echo "Deploying worker: $WORKER_NAME"

# --- Resolve REDIS_URL / CELERY_BROKER_URL from backbone's deploy_app_state ---
# Mirrors deploy-v1.sh's worker-path formulas exactly (TLS schemes, port 5671,
# universal hostnames) so the worker container reaches the same Redis DB /
# RabbitMQ vhost the main app already uses. Falls back to whatever the
# container's own config.py defaults are (local dev) only if the admin PG
# creds aren't available — e.g. running this script outside the backbone
# deploy host — since we never invent new credentials here.
_BACKBONE_BASE_DOMAIN="${BACKBONE_BASE_DOMAIN:-activeaidemo.com}"
_REDIS_HOSTNAME="${REDIS_HOSTNAME:-redis.${_BACKBONE_BASE_DOMAIN}}"
_RABBIT_HOSTNAME="${RABBIT_HOSTNAME:-rmq.${_BACKBONE_BASE_DOMAIN}}"
_REDIS_PORT="${REDIS_PORT:-7027}"

RESOLVED_REDIS_URL=""
RESOLVED_BROKER_URL=""

if [ -n "${POSTGRES_ADMIN_USER:-}" ] && [ -n "${POSTGRES_ADMIN_PASS:-}" ]; then
    _ADMIN_PG_HOST="${POSTGRES_ADMIN_HOST:-${DB_HOSTNAME:-${MAIN_HOST:-localhost}}}"
    _ADMIN_PG_PORT="${POSTGRES_ADMIN_PORT:-5432}"
    _ADMIN_PG_DB="${POSTGRES_ADMIN_DB:-backbone}"
    _ADMIN_PG_URL="postgresql://${POSTGRES_ADMIN_USER}:${POSTGRES_ADMIN_PASS}@${_ADMIN_PG_HOST}:${_ADMIN_PG_PORT}/${_ADMIN_PG_DB}"

    echo "  Looking up backbone deploy_app_state for slug '$MAINFORTE_SLUG'..."
    _STATE_ROW=$(timeout 10 env PGCONNECT_TIMEOUT=5 psql "$_ADMIN_PG_URL" -XtA -F'|' -c \
        "SELECT redis_db, rabbit_pass FROM deploy_app_state WHERE slug = '$(printf '%s' "$MAINFORTE_SLUG" | sed "s/'/''/g")' LIMIT 1" \
        2>/dev/null || true)
    _REDIS_DB="${_STATE_ROW%%|*}"
    _RABBIT_PASS="${_STATE_ROW##*|}"

    if [ -n "$_REDIS_DB" ]; then
        RESOLVED_REDIS_URL="rediss://${_REDIS_HOSTNAME}:${_REDIS_PORT}/${_REDIS_DB}?ssl_ca_certs=/etc/ssl/backbone-ca/ca.crt&ssl_cert_reqs=required"
        echo "  Resolved REDIS_URL: rediss://${_REDIS_HOSTNAME}:${_REDIS_PORT}/${_REDIS_DB}?..."
    else
        echo "  WARNING: no redis_db found in deploy_app_state for '$MAINFORTE_SLUG' — leaving REDIS_URL unset"
    fi

    if [ -n "$_RABBIT_PASS" ]; then
        RESOLVED_BROKER_URL="amqps://${MAINFORTE_SLUG}:${_RABBIT_PASS}@${_RABBIT_HOSTNAME}:5671/${MAINFORTE_SLUG}"
        echo "  Resolved CELERY_BROKER_URL: amqps://${MAINFORTE_SLUG}:***@${_RABBIT_HOSTNAME}:5671/${MAINFORTE_SLUG}"
    else
        echo "  WARNING: no rabbit_pass found in deploy_app_state for '$MAINFORTE_SLUG' — leaving CELERY_BROKER_URL unset"
    fi
else
    echo "  WARNING: POSTGRES_ADMIN_USER/POSTGRES_ADMIN_PASS not set in this environment —"
    echo "           skipping deploy_app_state lookup. Worker will fall back to config.py's"
    echo "           local-dev defaults for REDIS_URL/CELERY_BROKER_URL, which will NOT reach"
    echo "           backbone's shared Redis/RabbitMQ."
fi

echo "  Building worker image..."
# base and worker must NOT be built in the same `docker compose build` call: bake runs
# multi-target builds in parallel, and worker's `FROM mainforte-base` can start resolving
# before base's own build finishes tagging the image locally, so it falls through to
# Docker Hub ("pull access denied ... docker.io/library/mainforte-base") instead of using
# the freshly-built local image. Two separate invocations force base to finish first.
docker compose build base
docker compose build worker

echo "  Stopping/removing any existing container named $WORKER_NAME..."
docker stop "$WORKER_NAME" >/dev/null 2>&1 || true
docker rm "$WORKER_NAME" >/dev/null 2>&1 || true

ENV_ARGS=(-e "MAINFORTE_WORKER_ID=$WORKER_NAME" -e "API_URL=$API_URL")
if [ -n "$CELERY_QUEUES" ]; then
    ENV_ARGS+=(-e "CELERY_QUEUES=$CELERY_QUEUES")
fi
if [ -n "${DATABASE_URL:-}" ]; then
    ENV_ARGS+=(-e "DATABASE_URL=$DATABASE_URL")
fi
if [ -n "$RESOLVED_REDIS_URL" ]; then
    ENV_ARGS+=(-e "REDIS_URL=$RESOLVED_REDIS_URL")
fi
if [ -n "$RESOLVED_BROKER_URL" ]; then
    ENV_ARGS+=(-e "CELERY_BROKER_URL=$RESOLVED_BROKER_URL")
fi

# rediss:// and amqps:// both terminate at backbone's internal CA, which is
# self-signed — the host trusts it (deploy-v1.sh maintains a merged CA bundle
# there), but a fresh container has no idea it exists. Redis's ssl_ca_certs
# query param points at an in-container path; py-amqp/Celery has no such URL
# param and instead relies on Python's default SSL context, so give it the
# same trust via SSL_CERT_FILE/REQUESTS_CA_BUNDLE — exactly what deploy-v1.sh
# does for every other backbone-hosted container (see its _CA_CERT_VOL /
# _TRUST_BUNDLE_ENV, ~line 6271). Without this mount, amqps:// connections
# fail with "self-signed certificate in certificate chain".
VOL_ARGS=()
_INTERNAL_CA_DIR="${INTERNAL_TLS_DIR:-/etc/backbone/internal-tls}"
_INTERNAL_CA_FILE="${_INTERNAL_CA_DIR}/ca.crt"
_MERGED_CA_FILE="${_INTERNAL_CA_DIR}/merged-ca-bundle.crt"
if [ -f "$_INTERNAL_CA_FILE" ]; then
    VOL_ARGS+=(-v "${_INTERNAL_CA_FILE}:/etc/ssl/backbone-ca/ca.crt:ro")
    if [ -f "$_MERGED_CA_FILE" ]; then
        VOL_ARGS+=(-v "${_MERGED_CA_FILE}:/etc/ssl/backbone-ca/merged-bundle.crt:ro")
        ENV_ARGS+=(-e "SSL_CERT_FILE=/etc/ssl/backbone-ca/merged-bundle.crt" -e "REQUESTS_CA_BUNDLE=/etc/ssl/backbone-ca/merged-bundle.crt")
    fi
else
    echo "  WARNING: internal CA not found at $_INTERNAL_CA_FILE — amqps:///rediss:// TLS verification will fail"
fi

echo "  Starting..."
# `docker compose images -q worker` only reports images for containers Compose has
# created (i.e. after `up`/`run`), so it's empty here since we only ever `build`.
# Reference the image's fixed tag directly instead (set via `image: mainforte-worker`
# in docker-compose.yml).
docker run -d \
    --name "$WORKER_NAME" \
    --restart unless-stopped \
    "${ENV_ARGS[@]}" \
    "${VOL_ARGS[@]}" \
    mainforte-worker

echo "  Started. Liveness: AgentWorker.last_heartbeat where container_name=$WORKER_NAME"
