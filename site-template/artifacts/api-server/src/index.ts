import app from "./app";
import { logger } from "./lib/logger";
import { notifyStarted } from "./lib/callback";
import { pool } from "@workspace/db";
import { sessionsTableDdl } from "./lib/session-store";
import { seedDevUser } from "./lib/seed";

// ── Ensure Postgres schema exists (idempotent, runs every startup) ───────────
// Kept as raw idempotent DDL (not a second migration tool) so this template's own footprint
// stays small — mainforte's own alembic-based migrations are a separate concern for mainforte's
// DB, not this site's. See PLAN.md's "Site starter template fork" > "Rewrite for Postgres".
async function ensureSchema(): Promise<void> {
  await pool.query(`
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";
    CREATE TABLE IF NOT EXISTS users (
      id            SERIAL PRIMARY KEY,
      email         TEXT NOT NULL UNIQUE,
      name          TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      login_count   INTEGER NOT NULL DEFAULT 0,
      last_login    TIMESTAMPTZ,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS password_resets (
      id          SERIAL PRIMARY KEY,
      user_id     INTEGER NOT NULL REFERENCES users(id),
      token       TEXT NOT NULL UNIQUE,
      expires_at  TIMESTAMPTZ NOT NULL,
      used_at     TIMESTAMPTZ,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    ${sessionsTableDdl()}
  `);
  logger.info("Postgres schema ready");
}

async function main(): Promise<void> {
  await ensureSchema();

  // ── Dev-only seed (NEVER runs in production) ────────────────────────────
  // Seeds a single known login so a developer or the per-site Claude builder can reach the
  // dashboard immediately. Gated on NODE_ENV (set to development by dev.sh) AND the explicit
  // SEED_DEV_USER flag dev.sh exports, so it cannot run in the production image
  // (NODE_ENV=production, flag unset). seedDevUser() also hard-refuses under
  // NODE_ENV=production as a final safety net.
  if (process.env.NODE_ENV !== "production" && process.env.SEED_DEV_USER === "1") {
    await seedDevUser();
  }

  const rawPort = process.env["PORT"];
  if (!rawPort) {
    throw new Error("PORT environment variable is required but was not provided.");
  }
  const port = Number(rawPort);
  if (Number.isNaN(port) || port <= 0) {
    throw new Error(`Invalid PORT value: "${rawPort}"`);
  }

  let listenAttempt = 0;
  const MAX_LISTEN_ATTEMPTS = 2;

  function startListening(): void {
    listenAttempt++;
    const server = app.listen(port, (err?: Error) => {
      if (err) {
        logger.error({ err }, "Error listening on port");
        process.exit(1);
      }
      logger.info({ port }, "Server listening");
      // Fire the lightweight "process is listening" ping once the server has actually bound —
      // see lib/callback.ts's docstring for why this is distinct from the Jenkins job's own
      // authoritative "ready" callback.
      void notifyStarted();
    });

    server.on("error", (err: NodeJS.ErrnoException) => {
      if (err.code === "EADDRINUSE" && listenAttempt < MAX_LISTEN_ATTEMPTS) {
        // Brief overlap with the dying --watch child; retry once after the OS has had a chance
        // to release the port. (#419)
        logger.warn({ port, attempt: listenAttempt }, "EADDRINUSE — retrying in 250ms");
        setTimeout(startListening, 250);
        return;
      }
      logger.error({ err }, "FATAL: listen failed");
      process.exit(1);
    });

    // Graceful shutdown: release the port cleanly so the respawned child (under node --watch)
    // binds on the first try. (#419)
    const shutdown = (signal: string): void => {
      logger.info({ signal }, "Closing HTTP server");
      server.close(() => process.exit(0));
      setTimeout(() => process.exit(0), 2000).unref();
    };
    process.once("SIGTERM", () => shutdown("SIGTERM"));
    process.once("SIGINT", () => shutdown("SIGINT"));
  }

  startListening();
}

main().catch((err) => {
  logger.error({ err }, "FATAL: startup failed");
  process.exit(1);
});
