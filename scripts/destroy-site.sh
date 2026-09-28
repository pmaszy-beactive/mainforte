#!/bin/bash
# destroy-site.sh — tear down one Site's container, its HAProxy/NGINX
# registration, AND its database (unlike destroy-worker.sh, which only ever
# needs to remove a container — workers have no inbound HTTP routing).
#
# Counterpart to deploy-site.sh. Called by the Jenkins job named in
# jenkins.site_destroy_job (db_settings.py) — sites/provisioning.py's
# trigger_destroy fires it once a site is actually being deleted, not on every
# draft edit. Drops the HAProxy/NGINX registration and the database/role so
# sites don't leak orphaned subdomains or databases on every delete
# (PLAN.md's "Per-site Postgres provisioning" > "Teardown symmetry").
#
# Called from the Jenkins job with the mainforte repo already checked out into
# the current directory (standard Jenkins workspace behavior) — same as
# destroy-worker.sh, though (like that script) no build step is needed here.
#
# Params (Jenkins job) — must match what sites/provisioning.py's trigger_destroy
# actually sends via trigger_jenkins_build:
#   SITE_ID             — label only, for the log lines below
#   CONTAINER_NAME       — the container to remove, e.g. "site-babysitting-biz"
#                          (same "site-{slug}" shape deploy-site.sh constructs).
#                          Also used as deploy-light.sh's --slug — deploy-site.sh
#                          registers under --slug "$CONTAINER_NAME", so removal
#                          must match it exactly.
#   DB_NAME, DB_USER     — this site's database + role to drop (same deterministic
#                          "site_{slug}" values deploy-site.sh's DB_NAME/DB_USER used)
#   DB_ADMIN_USER, DB_ADMIN_PASSWORD  — admin Postgres credential, forwarded from
#                          db_settings.py's db.admin_* Settings, same as deploy-site.sh.
#                          Also forwarded to deploy-light.sh (as POSTGRES_ADMIN_USER/
#                          POSTGRES_ADMIN_PASS below), since --remove still needs a
#                          working connection to the shared "backbone" state database
#                          to drain HAProxy slots and delete its registration rows.
#
# Env this script expects to already be present on the Jenkins/deploy host (same
# convention as deploy-site.sh):
#   DB_HOST, DB_PORT    — defaults match deploy-site.sh's own defaults
#
# HAProxy/NGINX de-registration: handled by /etc/backbone/scripts/deploy-light.sh
# --remove, the real counterpart to the --slug/--port registration deploy-site.sh
# performs. It drains HAProxy backend slots, deletes the deploy_app_state/
# site_configs rows, removes the HAProxy/NGINX config fragments, and reloads both
# — all before this script removes the container itself, so nothing keeps routing
# to a container that's about to disappear.
#
# No dedicated drop-db.sh companion to bootstrap-db.sh exists in backbone today
# (only decommission-app.sh does this, as one small piece of a much larger,
# app-registry-coupled teardown this script deliberately does not pull in) — so
# this does the drop directly with the same direct-psql-then-docker-exec
# connection fallback bootstrap-db.sh itself uses, just for the two DROP
# statements it actually needs. If a real drop-db.sh companion script is added
# to backbone later, prefer calling that instead of maintaining this copy.
set -euo pipefail

: "${SITE_ID:?SITE_ID is required}"
: "${CONTAINER_NAME:?CONTAINER_NAME is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USER:?DB_USER is required}"
DB_ADMIN_USER="${DB_ADMIN_USER:-postgres}"
DB_ADMIN_PASSWORD="${DB_ADMIN_PASSWORD:-}"
DB_HOST="${DB_HOST:-db.activeaidemo.com}"
DB_PORT="${DB_PORT:-5432}"
DEPLOY_LIGHT_SH="/etc/backbone/scripts/deploy-light.sh"

echo "Destroying site: $SITE_ID (container=$CONTAINER_NAME, db=$DB_NAME)"

echo "  De-registering from HAProxy/NGINX via deploy-light.sh --remove..."
if [ -n "$DB_ADMIN_PASSWORD" ]; then
    POSTGRES_ADMIN_USER="$DB_ADMIN_USER" POSTGRES_ADMIN_PASS="$DB_ADMIN_PASSWORD" \
        "$DEPLOY_LIGHT_SH" --slug "$CONTAINER_NAME" --remove \
        || echo "  WARNING: deploy-light.sh --remove failed — HAProxy/NGINX registration may be orphaned for $CONTAINER_NAME, check manually."
else
    echo "  WARNING: DB_ADMIN_PASSWORD not set — deploy-light.sh --remove needs it to reach its own"
    echo "           state database. Skipping de-registration; HAProxy/NGINX config for"
    echo "           $CONTAINER_NAME will remain until removed manually or this is re-run with credentials."
fi

echo "  Stopping container..."
docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || echo "  (already stopped or not found)"

echo "  Removing container..."
docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || echo "  (already removed or not found)"

echo "  Removing image..."
docker rmi "site-template:${SITE_ID}" >/dev/null 2>&1 || echo "  (already removed or not found)"

if [ -z "$DB_ADMIN_PASSWORD" ]; then
    echo "  WARNING: DB_ADMIN_PASSWORD not set — skipping database/role drop for $DB_NAME."
    echo "           The container is gone, but $DB_NAME/$DB_USER remain on ${DB_HOST}:${DB_PORT}"
    echo "           until this is re-run with admin credentials, or dropped manually."
    echo "  Done (container only)."
    exit 0
fi

export PGPASSWORD="$DB_ADMIN_PASSWORD"
PSQL="psql -X -h $DB_HOST -p $DB_PORT -U $DB_ADMIN_USER"
CONN_METHOD="direct"
if ! $PSQL -c "SELECT 1" >/dev/null 2>&1; then
    echo "  Direct connection failed. Trying via docker exec backbone-postgres..."
    PSQL="docker exec -e PGPASSWORD=$PGPASSWORD -i backbone-postgres psql -X -h localhost -p $DB_PORT -U $DB_ADMIN_USER"
    CONN_METHOD="docker"
    if ! $PSQL -c "SELECT 1" >/dev/null 2>&1; then
        echo "ERROR: Cannot connect to PostgreSQL at ${DB_HOST}:${DB_PORT} as $DB_ADMIN_USER to drop $DB_NAME." >&2
        echo "  Container was removed; database/role were NOT dropped. Clean up $DB_NAME/$DB_USER manually." >&2
        exit 1
    fi
fi
echo "  Connected via $CONN_METHOD."

# Safe to double-quote-identifier these: DB_NAME/DB_USER are always the
# deterministic "site_{slug}" mainforte generates (see provisioning.py), never
# free text a user typed — still quoted defensively rather than trusted as-is.
echo "  Dropping database \"$DB_NAME\"..."
$PSQL -c "DROP DATABASE IF EXISTS \"$DB_NAME\";" || echo "  WARNING: DROP DATABASE failed (may have open connections) — leaving it in place."

echo "  Dropping role \"$DB_USER\"..."
$PSQL -c "DROP ROLE IF EXISTS \"$DB_USER\";" || echo "  WARNING: DROP ROLE failed (may still own objects) — leaving it in place."

echo "  Done."
