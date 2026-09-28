import bcrypt from "bcrypt";
import { pool } from "@workspace/db";
import { logger } from "./logger";

/**
 * Development-only seed credentials.
 *
 * These let a developer — or the per-site Claude builder — log in immediately
 * to reach the dashboard and exercise the auth flow without registering first.
 * They are inserted ONLY in development (see `seedDevUser`) and are NEVER
 * created in production, so a deployed site always boots with an empty users
 * table.
 */
export const DEV_SEED_EMAIL = "dev@example.com";
export const DEV_SEED_PASSWORD = "devpassword123";
export const DEV_SEED_NAME = "Dev User";

/**
 * Insert the known dev user if it does not already exist. Idempotent: running
 * it repeatedly (e.g. on every `node --watch` respawn) is a no-op once the user
 * exists.
 *
 * Hard-refuses to run under NODE_ENV=production as defense-in-depth — the caller
 * already gates on the environment, but this guarantees the seed can never
 * touch a production database even if it is invoked by mistake.
 */
export async function seedDevUser(): Promise<void> {
  if (process.env.NODE_ENV === "production") {
    return;
  }

  const { rows } = await pool.query<{ id: number }>(
    "SELECT id FROM users WHERE email = $1",
    [DEV_SEED_EMAIL.toLowerCase()],
  );

  if (rows[0]) {
    logger.info({ email: DEV_SEED_EMAIL }, "Dev seed user already present");
    return;
  }

  const passwordHash = bcrypt.hashSync(DEV_SEED_PASSWORD, 12);
  await pool.query(
    `INSERT INTO users (email, name, password_hash, login_count, created_at, updated_at)
     VALUES ($1, $2, $3, 0, now(), now())`,
    [DEV_SEED_EMAIL.toLowerCase(), DEV_SEED_NAME, passwordHash],
  );

  logger.info(
    { email: DEV_SEED_EMAIL },
    "Seeded dev user (development only) — log in with the documented credentials",
  );
}
