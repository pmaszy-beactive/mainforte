# ---- frontend ----
FROM node:22-slim AS frontend
RUN corepack enable && corepack prepare pnpm@10 --activate
WORKDIR /fe
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install
COPY frontend/ ./
# Vite inlines import.meta.env.VITE_* into the built JS at `pnpm build` time -- there is no
# runtime env var that can reach it later, so these must be passed as --build-arg to `docker
# build` (ticket T02749: Save Card silently did nothing because this image was always built
# with VITE_PUBLIC_STRIPE_PUBLISHABLE_KEY unset, so stripePromise is null in every deployed
# build, not just this dev machine).
ARG VITE_PUBLIC_STRIPE_PUBLISHABLE_KEY
ARG VITE_API_URL
ENV VITE_PUBLIC_STRIPE_PUBLISHABLE_KEY=${VITE_PUBLIC_STRIPE_PUBLISHABLE_KEY}
ENV VITE_API_URL=${VITE_API_URL}
RUN pnpm build

# ---- api ----
FROM python:3.12-slim-bookworm AS api
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_SYSTEM_PYTHON=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl postgresql-client openssh-client \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml
COPY backend/ ./backend/
COPY alembic.ini ./
COPY --from=frontend /fe/dist ./frontend/dist
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh
ENV PYTHONPATH=/app/backend APP_PORT=8000
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
