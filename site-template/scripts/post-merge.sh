#!/bin/bash
set -e
# Tenant site-template is standardized on npm (task #721). `npm ci` installs
# exactly the committed package-lock.json (the npm equivalent of pnpm's
# --frozen-lockfile) and fails loud if the lockfile and package.json drift.
npm ci --no-audit --no-fund
npm --workspace @workspace/db run push
