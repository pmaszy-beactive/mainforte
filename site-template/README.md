# site-template

The starter template mainforte's site-provisioning Jenkins job clones for every new **Site**
(the "describe a business in chat, get a real running app" feature — see the main mainforte
repo's `PLAN.md` for the full design). Each site is its own copy of this tree: its own git
history, its own container, its own Postgres database. This template evolves independently in
mainforte's own repo from this point on — it is a one-time fork, not a submodule or a live
dependency of anything in `beactive-claw`.

## Stack

- **Frontend** (`artifacts/hello-world/`): React + Vite, Tailwind, shadcn/radix components.
- **Backend** (`artifacts/api-server/`): Express 5, session auth (email/password + password
  reset), served from the same origin as the frontend in production.
- **Database**: Postgres, via `drizzle-orm/node-postgres` (`lib/db/`). Every site gets its own
  database and role on the same shared Postgres cluster mainforte's own backend uses — see the
  main repo's `PLAN.md` ("Per-site Postgres provisioning") for how credentials are minted and
  handed to the container. This app only ever reads `DATABASE_URL` from its environment; it never
  assembles a connection string from parts and never sees the admin credential that created it.
- **API contract**: `lib/api-spec/` (OpenAPI) → generated into `lib/api-zod/` (Zod schemas) and
  `lib/api-client-react/` (typed React Query hooks) via `orval`. Edit `openapi.yaml`, then
  regenerate — don't hand-edit the generated packages.

## How a site boots

1. mainforte's Jenkins provisioning job clones this template, runs
   `backbone/deploy/scripts/bootstrap-db.sh` to create the site's own Postgres role + database,
   and starts the container with `DATABASE_URL`, `PORT`, `SUBDOMAIN`, `CALLBACK_URL`, and
   `CONTAINER_API_KEY` set.
2. On boot, `artifacts/api-server/src/index.ts` idempotently ensures the schema exists
   (`CREATE TABLE IF NOT EXISTS ...` — no separate migration tool; keep it that way, this
   template's own footprint should stay small), then starts listening.
3. Once the HTTP server confirms it's listening, `lib/callback.ts`'s `notifyStarted()` sends one
   `POST ${CALLBACK_URL}` with `Authorization: Bearer ${CONTAINER_API_KEY}` — a lightweight
   "the app process is up" signal. The Jenkins pipeline step itself sends the *authoritative*
   "ready" callback (with `container_name`/`dev_port`, which this in-container code has no way to
   know) once it confirms the container is up.
4. From then on, mainforte's site-editing persona reads/writes this container's files directly
   (scoped, sandboxed tool calls — see the main repo's `tools/catalog.py`) while the user watches
   changes live in a preview iframe pointed at the dev server.

There is no outbound control-plane connection from this app back to mainforte beyond that one
startup ping — no persistent WebSocket, no heartbeat loop, no in-container command-and-control.
mainforte pulls (files, logs) rather than this app pushing.

## Local development

```bash
PORT=5000 BASE_PATH=/ ./dev.sh
```

`dev.sh` installs dependencies, builds the API once, then runs the API (`node --watch`) and the
Vite dev server side by side, exiting (so a supervisor can restart the whole stack) if either one
dies. It forces `NODE_ENV=development` and seeds one known dev login
(`dev@example.com` / `devpassword123` — see `artifacts/api-server/src/lib/seed.ts`) so you can
reach the dashboard immediately; this seed can never run in the production image.

Requires a reachable `DATABASE_URL` (a local Postgres works fine — the schema bootstrap creates
its own tables on first boot).

Other useful commands, run from the repo root:

```bash
npm run typecheck   # tsc --noEmit across every workspace
npm run build        # typecheck, then build every workspace
```

## Production image

```bash
docker build -t site-template .
docker run -e DATABASE_URL=... -e SUBDOMAIN=... -e CALLBACK_URL=... -e CONTAINER_API_KEY=... \
  -p 3000:3000 site-template
```

The production image bakes `NODE_ENV=production` and serves the prebuilt frontend from the same
Express process — no Vite dev server, no `dev.sh` involved.

## Layout

```
artifacts/hello-world/   React + Vite frontend
artifacts/api-server/    Express backend (auth, dashboard, health, version routes)
lib/db/                  Drizzle schema + Postgres pool (DATABASE_URL)
lib/api-spec/            OpenAPI source of truth
lib/api-zod/             Generated Zod schemas (do not hand-edit)
lib/api-client-react/    Generated React Query client (do not hand-edit)
scripts/                 Repo-local dev tooling (git hooks setup, etc.)
dev.sh                   Local/preview entrypoint (see above)
Dockerfile                Production image build
```
