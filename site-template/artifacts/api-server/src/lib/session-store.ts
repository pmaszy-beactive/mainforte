import session, { type SessionData } from "express-session";
import type { Pool } from "pg";

/**
 * A minimal Postgres-backed session store for express-session.
 *
 * It reuses the SAME `pg` Pool the rest of the app already opens (`pool` from `@workspace/db`),
 * so sessions live in this site's own database and therefore survive api-server restarts —
 * including the `node --watch` respawns the dev runner performs on every rebuild. This replaces
 * express-session's default in-memory store, which loses every session on restart and leaks
 * memory because it never evicts expired entries.
 *
 * The backing table (`sessions` by default) is created idempotently by the startup schema
 * bootstrap in `index.ts`, alongside the other tables. This store assumes that table already
 * exists; it only reads/writes rows.
 *
 * Every method is async (pg queries are always async) but still matches express-session's
 * callback-based Store contract -- errors are caught and forwarded to the callback rather than
 * thrown or left as an unhandled rejection.
 */
export interface PgSessionStoreOptions {
  /** Open `pg` Pool to reuse (the app's shared `pool`). */
  pool: Pool;
  /** Table name to store sessions in. Defaults to `sessions`. */
  table?: string;
  /** Fallback TTL (ms) used only when a session has no cookie.maxAge/expires. */
  ttlMs?: number;
}

/** DDL for the session table — exported so the startup bootstrap stays in sync. */
export function sessionsTableDdl(table = "sessions"): string {
  return `
    CREATE TABLE IF NOT EXISTS ${table} (
      sid    TEXT PRIMARY KEY,
      sess   TEXT NOT NULL,
      expire TIMESTAMPTZ NOT NULL
    );
  `;
}

export class PgSessionStore extends session.Store {
  private readonly pool: Pool;
  private readonly table: string;
  private readonly defaultTtlMs: number;

  constructor(options: PgSessionStoreOptions) {
    super();
    this.pool = options.pool;
    this.table = options.table ?? "sessions";
    this.defaultTtlMs = options.ttlMs ?? 24 * 60 * 60 * 1000;
    // Evict any sessions that expired while the server was down so the table does not
    // accumulate dead rows across restarts. Fire-and-forget: the table may not exist yet
    // (bootstrap runs after app import) -- the lazy prune in get() and the startup bootstrap
    // both cover that case, so a failure here is not fatal.
    this.pool.query(`DELETE FROM ${this.table} WHERE expire <= now()`).catch(() => {});
  }

  private expiryFor(sess: SessionData): Date {
    const expires = sess.cookie?.expires;
    if (expires) {
      return new Date(expires);
    }
    return new Date(Date.now() + this.defaultTtlMs);
  }

  get = (
    sid: string,
    callback: (err: unknown, session?: SessionData | null) => void,
  ): void => {
    this.pool
      .query<{ sess: string; expire: Date }>(
        `SELECT sess, expire FROM ${this.table} WHERE sid = $1`,
        [sid],
      )
      .then(({ rows }) => {
        const row = rows[0];
        if (!row) {
          callback(null, null);
          return;
        }
        if (row.expire.getTime() <= Date.now()) {
          // Lazily evict expired sessions on read.
          this.pool.query(`DELETE FROM ${this.table} WHERE sid = $1`, [sid]).catch(() => {});
          callback(null, null);
          return;
        }
        callback(null, JSON.parse(row.sess) as SessionData);
      })
      .catch((err) => callback(err));
  };

  set = (
    sid: string,
    sess: SessionData,
    callback?: (err?: unknown) => void,
  ): void => {
    this.pool
      .query(
        `INSERT INTO ${this.table} (sid, sess, expire) VALUES ($1, $2, $3)
         ON CONFLICT (sid) DO UPDATE SET sess = excluded.sess, expire = excluded.expire`,
        [sid, JSON.stringify(sess), this.expiryFor(sess)],
      )
      .then(() => callback?.())
      .catch((err) => callback?.(err));
  };

  destroy = (sid: string, callback?: (err?: unknown) => void): void => {
    this.pool
      .query(`DELETE FROM ${this.table} WHERE sid = $1`, [sid])
      .then(() => callback?.())
      .catch((err) => callback?.(err));
  };

  touch = (
    sid: string,
    sess: SessionData,
    callback?: (err?: unknown) => void,
  ): void => {
    this.pool
      .query(`UPDATE ${this.table} SET expire = $1 WHERE sid = $2`, [this.expiryFor(sess), sid])
      .then(() => callback?.())
      .catch((err) => callback?.(err));
  };
}
