// Locks the dev-only login seed guarantees:
//   1. seedDevUser() is IDEMPOTENT — running it repeatedly (e.g. on every
//      `node --watch` respawn) inserts the dev user once and is a no-op after.
//   2. seedDevUser() is a NO-OP under NODE_ENV=production — a deployed site must
//      always boot with an empty users table, even if the seed is invoked by
//      mistake (it hard-refuses production as defense-in-depth).
//
// seed.ts imports @workspace/db (which opens a SQLite file on import) plus
// bcrypt and the logger, so it can't be loaded from a data: URL. We point
// DATABASE_URL at a throwaway temp file BEFORE bundling/importing seed.ts, so
// the @workspace/db code bundled into it opens that throwaway file. The test
// then opens its OWN better-sqlite3 connection to the same file to create the
// users table and assert on the rows seed writes (both connections see the
// same file; SQLite commits are visible across connections).
import test from "node:test";
import assert from "node:assert";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";

const tmpDir = mkdtempSync(path.join(os.tmpdir(), "seed-test-"));
const dbFile = path.join(tmpDir, "data.db");
process.env.DATABASE_URL = `file:${dbFile}`;
process.env.NODE_ENV = "development";

const { importTsModule } = await import("./auth-test-helpers.mjs");
const { seedDevUser, DEV_SEED_EMAIL } = await importTsModule("seed.ts");

const sqlite = new Database(dbFile);

// Minimal users table matching the startup bootstrap in index.ts.
sqlite.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    password_hash TEXT  NOT NULL,
    login_count INTEGER NOT NULL DEFAULT 0,
    last_login  INTEGER,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
  );
`);

const countUsers = () =>
  sqlite.prepare("SELECT COUNT(*) AS n FROM users").get().n;
const resetUsers = () => sqlite.prepare("DELETE FROM users").run();

test("[seed] inserts the dev user in development", () => {
  resetUsers();
  process.env.NODE_ENV = "development";
  seedDevUser();
  assert.strictEqual(countUsers(), 1);
  const row = sqlite
    .prepare("SELECT email, password_hash FROM users")
    .get();
  assert.strictEqual(row.email, DEV_SEED_EMAIL.toLowerCase());
  // Password is stored hashed, never in plaintext.
  assert.ok(row.password_hash.startsWith("$2"), "password must be bcrypt-hashed");
});

test("[seed] is idempotent — repeated runs do not duplicate the dev user", () => {
  resetUsers();
  process.env.NODE_ENV = "development";
  seedDevUser();
  seedDevUser();
  seedDevUser();
  assert.strictEqual(countUsers(), 1);
});

test("[seed] is a no-op under NODE_ENV=production", () => {
  resetUsers();
  const prev = process.env.NODE_ENV;
  process.env.NODE_ENV = "production";
  try {
    seedDevUser();
  } finally {
    process.env.NODE_ENV = prev;
  }
  assert.strictEqual(countUsers(), 0, "production must boot with no seeded user");
});
