#!/usr/bin/env bash
set -euo pipefail
cd /app
if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  echo "[entrypoint] running migrations"
  alembic upgrade head
  echo "[entrypoint] migrations at: $(alembic current 2>/dev/null | tail -1)"
fi
exec uvicorn mainforte.main:app --host 0.0.0.0 --port "${APP_PORT:-8000}" --proxy-headers --forwarded-allow-ips=*
