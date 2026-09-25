# ---- frontend ----
FROM node:22-slim AS frontend
RUN corepack enable && corepack prepare pnpm@10 --activate
WORKDIR /fe
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install
COPY frontend/ ./
RUN pnpm build

# ---- api ----
FROM python:3.12-slim-bookworm AS api
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_SYSTEM_PYTHON=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl postgresql-client \
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
ENV PYTHONPATH=/app/backend PORT=8000
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "mainforte.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
