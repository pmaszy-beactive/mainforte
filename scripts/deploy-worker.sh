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
set -euo pipefail

: "${WORKER_NAME:?WORKER_NAME is required}"
: "${API_URL:?API_URL is required}"
CELERY_QUEUES="${CELERY_QUEUES:-}"

echo "Deploying worker: $WORKER_NAME"

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

echo "  Starting..."
# `docker compose images -q worker` only reports images for containers Compose has
# created (i.e. after `up`/`run`), so it's empty here since we only ever `build`.
# Reference the image's fixed tag directly instead (set via `image: mainforte-worker`
# in docker-compose.yml).
docker run -d \
    --name "$WORKER_NAME" \
    --restart unless-stopped \
    "${ENV_ARGS[@]}" \
    mainforte-worker

echo "  Started. Liveness: AgentWorker.last_heartbeat where container_name=$WORKER_NAME"
