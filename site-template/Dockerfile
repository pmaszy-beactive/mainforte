FROM node:24-alpine AS base
WORKDIR /app

FROM base AS deps
# npm-workspaces install: the root lockfile resolves every workspace, so we copy
# the root manifest + lockfile and each workspace's package.json, then `npm ci`
# for a clean, reproducible install pinned to the committed package-lock.json.
# (No native-toolchain step here: better-sqlite3 — the only package that needed
# node-gyp — is gone; `pg` is a pure-JS driver.)
COPY package.json package-lock.json tsconfig.base.json tsconfig.json ./
COPY lib/api-spec/package.json lib/api-spec/
COPY lib/api-client-react/package.json lib/api-client-react/
COPY lib/api-zod/package.json lib/api-zod/
COPY lib/db/package.json lib/db/
COPY artifacts/api-server/package.json artifacts/api-server/
COPY artifacts/hello-world/package.json artifacts/hello-world/
COPY scripts/package.json scripts/
RUN npm ci --include=dev --no-audit --no-fund

FROM deps AS build
COPY . .
ARG APP_VERSION=0.0.0
ENV APP_VERSION=${APP_VERSION}
# vite.config.ts requires PORT/BASE_PATH even for a production build (it uses them to compute
# the dev-server proxy target and base path) even though neither value actually affects the
# static output that ships — the real runtime PORT is set below in the production stage and read
# by the Express server, not by this build step.
ENV PORT=3000
ENV BASE_PATH=/
RUN npm --workspace @workspace/hello-world run build
RUN npm --workspace @workspace/api-server run build

FROM node:24-alpine AS production
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/artifacts/api-server/dist ./artifacts/api-server/dist
COPY --from=build /app/artifacts/hello-world/dist/public ./artifacts/hello-world/dist/public
COPY --from=build /app/version.ini ./version.ini

ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000

CMD ["node", "--enable-source-maps", "./artifacts/api-server/dist/index.mjs"]
