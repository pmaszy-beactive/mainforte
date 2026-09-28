// Locks the SqliteSessionStore guarantees that replaced express-session's
// default in-memory store:
//   1. Sessions live in the same SQLite file the app already opens, so they
//      SURVIVE an api-server restart (incl. the `node --watch` respawns the dev
//      runner does on every rebuild) — modelled here by closing the DB and
//      reopening it with a fresh store, exactly like a process restart.
//   2. Expired sessions are EVICTED — both eagerly when a new store boots
//      (so the table can't accumulate dead rows across restarts) and lazily on
//      read — instead of leaking forever the way the in-memory store does.
//
// session-store.ts imports express-session at runtime, so it can't be loaded
// from a data: URL; importTsModule bundles it (deps kept external) and imports
// it from a real path. See auth-test-helpers.mjs.
import test from "node:test";
import assert from "node:assert";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { importTsModule } from "./auth-test-helpers.mjs";

const { SqliteSessionStore, sessionsTableDdl } =
  await importTsModule("session-store.ts");

// Promisified store ops so each test reads top-to-bottom.
const pset = (store, sid, sess) =>
  new Promise((resolve, reject) =>
    store.set(sid, sess, (err) => (err ? reject(err) : resolve())),
  );
const pget = (store, sid) =>
  new Promise((resolve, reject) =>
    store.get(sid, (err, sess) => (err ? reject(err) : resolve(sess))),
  );

function sessionWithExpiry(userId, expiresAtMs) {
  return {
    cookie: {
      originalMaxAge: expiresAtMs - Date.now(),
      expires: new Date(expiresAtMs).toISOString(),
      httpOnly: true,
      path: "/",
    },
    userId,
  };
}

async function withDbFile(fn) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "session-store-test-"));
  const file = path.join(dir, "data.db");
  try {
    return await fn(file);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

test("[session-store] a session set before a restart is still valid after restart", async () => {
  await withDbFile(async (file) => {
    const future = Date.now() + 60 * 60 * 1000;

    // --- process lifetime #1: write a session, then "shut down". ---
    let db = new Database(file);
    db.exec(sessionsTableDdl());
    let store = new SqliteSessionStore({ client: db });
    await pset(store, "sid-live", sessionWithExpiry(42, future));
    db.close();

    // --- process lifetime #2: reopen the SAME file with a fresh store. ---
    db = new Database(file);
    store = new SqliteSessionStore({ client: db });
    const restored = await pget(store, "sid-live");
    db.close();

    assert.ok(restored, "session should survive the restart");
    assert.strictEqual(restored.userId, 42);
  });
});

test("[session-store] sessions that expired while down are evicted on restart", async () => {
  await withDbFile(async (file) => {
    const past = Date.now() - 1000;
    const future = Date.now() + 60 * 60 * 1000;

    let db = new Database(file);
    db.exec(sessionsTableDdl());
    let store = new SqliteSessionStore({ client: db });
    await pset(store, "sid-dead", sessionWithExpiry(1, past));
    await pset(store, "sid-live", sessionWithExpiry(2, future));
    db.close();

    // Booting a new store prunes rows whose expire <= now.
    db = new Database(file);
    store = new SqliteSessionStore({ client: db });
    const remaining = db
      .prepare("SELECT sid FROM sessions ORDER BY sid")
      .all()
      .map((r) => r.sid);
    const dead = await pget(store, "sid-dead");
    const live = await pget(store, "sid-live");
    db.close();

    assert.deepStrictEqual(remaining, ["sid-live"], "dead row pruned on boot");
    assert.strictEqual(dead, null, "expired session must not be returned");
    assert.ok(live, "unexpired session must still be returned");
  });
});

test("[session-store] expired session is evicted lazily on read", async () => {
  await withDbFile(async (file) => {
    const db = new Database(file);
    db.exec(sessionsTableDdl());
    const store = new SqliteSessionStore({ client: db });
    await pset(store, "sid-x", sessionWithExpiry(7, Date.now() - 5000));

    const got = await pget(store, "sid-x");
    const row = db.prepare("SELECT sid FROM sessions WHERE sid = ?").get("sid-x");
    db.close();

    assert.strictEqual(got, null, "expired session reads as null");
    assert.strictEqual(row, undefined, "and is deleted from the table on read");
  });
});

test("[session-store] destroy removes a session", async () => {
  await withDbFile(async (file) => {
    const db = new Database(file);
    db.exec(sessionsTableDdl());
    const store = new SqliteSessionStore({ client: db });
    await pset(store, "sid-d", sessionWithExpiry(9, Date.now() + 60_000));

    await new Promise((resolve, reject) =>
      store.destroy("sid-d", (err) => (err ? reject(err) : resolve())),
    );
    const got = await pget(store, "sid-d");
    db.close();

    assert.strictEqual(got, null);
  });
});
