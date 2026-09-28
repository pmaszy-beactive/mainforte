#!/bin/bash
# destroy-worker.sh — tear down one pooled mainforte agent worker container.
#
# Counterpart to deploy-worker.sh. Called by the Jenkins destroy job
# (s.jenkins_destroy_job, see db_settings.py) once _reconcile_pool
# (mainforte/tasks/system.py) decides a worker is gone for good — either
# a drained worker that finished its last in-flight job (idle_draining)
# or a live>desired scale-down victim. By that point the reconciler has
# already flipped the DB row (or the row will simply stop heartbeating
# and later disappear — reconcile does not delete AgentWorker rows here,
# only the container). This script's only job is to make the named
# container actually go away on the host.
#
# Called from the Jenkins job with the mainforte repo already checked out
# into the current directory (standard Jenkins workspace behavior) — same
# as deploy-worker.sh, though this script does not actually need the repo
# checkout itself (no build step), only `docker`.
#
# Params (Jenkins job) — must match what _reconcile_pool actually sends
# via trigger_jenkins_build(db, s.jenkins_destroy_job, {"WORKER_NAME": ...}):
#   WORKER_NAME  — the container/identity name to remove, e.g.
#                  mainforte-agent-worker-3 or mainforte-agent-worker-sandbox-1
#
# Nothing else to clean up: workers mount only the host's read-only backbone
# CA cert bind-mounts (see deploy-worker.sh's VOL_ARGS) and hold no named
# volumes of their own, so a plain stop+rm is the whole teardown. If that
# ever changes (e.g. a per-worker scratch volume is added), extend this
# script rather than assuming docker rm alone is still sufficient.
set -euo pipefail

: "${WORKER_NAME:?WORKER_NAME is required}"

echo "Destroying worker: $WORKER_NAME"

echo "  Stopping..."
docker stop "$WORKER_NAME" >/dev/null 2>&1 || echo "  (already stopped or not found)"

echo "  Removing..."
docker rm "$WORKER_NAME" >/dev/null 2>&1 || echo "  (already removed or not found)"

echo "  Done."
