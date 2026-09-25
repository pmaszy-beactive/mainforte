# Mainforte v3

AI staff that actually do the work. See `PLAN.md` for architecture and phases, `IDEA.md` for the brief.

## Layout

```
backend/mainforte/   FastAPI app, event bus, auth, admin, Celery tasks, Alembic migrations
frontend/            Vite + React (Capacitor-ready). Built into the api image.
Dockerfile           api image (python + built frontend)
Dockerfile.worker    agent-worker image (python + chromium + node), consumes chat,work,system queues
.deploy.env          backbone deploy config
docker-compose.yml   build-only (backbone deploy.sh)
docker-compose.dev.yml  local postgres/redis/rabbit
```

## Local dev

```bash
docker compose -f docker-compose.dev.yml -p mainforte-dev up -d
cp .env.example .env.local   # or keep the provided .env and let .env.local override the URLs
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn mainforte.main:app --app-dir backend --reload --port 8010      # 8000 is often taken on dev boxes
cd backend && uv run celery -A mainforte.celery_app worker --beat -Q chat,work,system --loglevel=info --pool=threads
# --pool=threads on macOS: the default prefork pool hits "not enough values to unpack (expected 3, got 0)"
cd frontend && pnpm install && pnpm dev                                                    # http://localhost:5173
uv run pytest
```

`.env.local` overrides `.env` (both gitignored). The provided `.env` targets the deployed backbone database and a live SendGrid key; `.env.local` must point at the local containers and blank `SENDGRID_API_KEY` so nothing real is touched from a laptop.

## Events

`mainforte.events.emit(db, "type", ws_id=..., user_id=..., actor=("user", id), payload={...})` writes the `events`
table, fans out on Redis stream `ws:<workspace_id>`, and dispatches handlers registered with
`@on("pattern", queue="chat|work|system")` as Celery tasks. The taxonomy lives in `events/types.py`.
Clients subscribe at `GET /ws?token=&workspace_id=&after=<last_event_id>` and get a Postgres replay of the gap first.

## Auth

Email+password, magic link, Google OIDC, password reset (SendGrid). JWT bearer. Superusers are listed in
`SUPPORT_USERS`; `POST /api/auth/impersonate/{user_id}` mints a session with `act_as` and every request resolves
both the real and the effective user. Impersonated sessions never get admin routes.

## Deploy

Backbone: `bash /etc/backbone/scripts/deploy.sh` reads `.deploy.env`. The api image runs Alembic on start.
Worker #1 is backbone's standard worker from `Dockerfile.worker`; more workers come from the admin page (P4).
