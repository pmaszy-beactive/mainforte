#!/usr/bin/env bash
# Local/preview dev entrypoint: builds the API once, then runs the API
# (node --watch) and the Vite dev server side by side, and exits (letting
# whatever started this container restart it) if either one dies.
#
# This replaces beactive-claw's dev.sh, which was a thin wrapper around an
# external scripts/dev-runner.sh shared across that repo's whole fleet of
# per-tenant containers (PID-file lifecycle, an API health watchdog, an
# install-on-boot step, etc.) — that script does not exist in this repo and
# mainforte's provisioning model doesn't have an equivalent shared supervisor
# to depend on. This is a small, self-contained replacement covering only
# what this template actually needs: build once, run two dev processes,
# exit together. See PLAN.md's "Site starter template fork" section.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
API_DIR="$SCRIPT_DIR/artifacts/api-server"

# The production image bakes NODE_ENV=production (Dockerfile: the Express
# server then serves the prebuilt hello-world dist/ and sets secure cookies).
# This script is the EDITING/PREVIEW path — the frontend is served by the
# Vite dev server and the api-server runs from a freshly built dist/ under
# `node --watch`. Force development so React Fast Refresh and non-secure
# preview cookies are active.
export NODE_ENV=development

# Enable the development-only login seed (see artifacts/api-server/src/lib/seed.ts)
# so a developer or the site-editing persona can log in immediately without
# registering first. The production Docker image never runs this script, so
# deployed sites always boot with an empty users table regardless.
export SEED_DEV_USER=1

: "${PORT:?PORT environment variable is required but was not provided.}"
export API_PORT="${API_PORT:-$((PORT + 1))}"
export BASE_PATH="${BASE_PATH:-/}"

echo "[dev.sh] Installing dependencies..."
cd "$SCRIPT_DIR"
npm install --include=dev --no-audit --no-fund

echo "[dev.sh] Building API server (initial)..."
cd "$API_DIR"
node ./build.mjs

echo "[dev.sh] Starting API server on port $API_PORT..."
PORT="$API_PORT" node --enable-source-maps --watch \
  --watch-path="$API_DIR/dist" \
  "$API_DIR/dist/index.mjs" &
API_PID=$!

echo "[dev.sh] Starting Vite HMR dev server on port $PORT..."
cd "$SCRIPT_DIR"
npm run dev --workspace @workspace/hello-world &
VITE_PID=$!

echo "[dev.sh] API server (PID $API_PID) and Vite (PID $VITE_PID) running. Press Ctrl+C to stop."

cleanup() {
  kill "$API_PID" "$VITE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# wait -n returns as soon as EITHER child exits. If the API crashes we don't
# want Vite to keep serving while proxying /api to a dead port, and vice
# versa — so exit together and let the container's restart policy (or the
# Jenkins-provisioned container's own supervisor) bring the whole stack back.
set +e
wait -n
EXIT_CODE=$?
set -e
echo "[dev.sh] a child process exited (code=$EXIT_CODE) — exiting so the stack can restart"
exit "$EXIT_CODE"
