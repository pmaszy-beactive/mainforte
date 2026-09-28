// Locks the HTTP behaviour of the auth routes — the highest-value security
// surface in the site-template. #828 covered the session store, the production
// session-secret guard, the dev seed, and the entities auth gate; the auth
// routes themselves (register / login / logout / me / forgot- + reset-password)
// had no coverage, so a regression (login accepting a wrong password, register
// not hashing, a reusable reset token) would have been silent.
//
// Each test boots a real Express app wired exactly like the production server:
// express.json + the real express-session middleware backed by the real
// SqliteSessionStore + the real auth router (which mounts the real rate-limit
// and requireAuth middleware), so the assertions exercise the genuine path
// end-to-end over HTTP.
//
// DATABASE_URL is pointed at a throwaway temp file BEFORE bundling/importing the
// auth router, so the @workspace/db code bundled into it opens that file. The
// test opens its OWN better-sqlite3 connection to the same file to seed users /
// reset tokens and assert on the rows the routes write (both connections see
// the same WAL-mode file; commits are visible across connections). SendGrid is
// left unconfigured so sendPasswordResetEmail is a no-op — the reset flow never
// sends mail; the token is read straight from the DB instead.
import test from "node:test";
import assert from "node:assert";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import express from "express";
import session from "express-session";
import Database from "better-sqlite3";
import bcrypt from "bcrypt";

const tmpDir = mkdtempSync(path.join(os.tmpdir(), "auth-routes-test-"));
const dbFile = path.join(tmpDir, "data.db");
process.env.DATABASE_URL = `file:${dbFile}`;
process.env.NODE_ENV = "development";
// Keep sendPasswordResetEmail a no-op (it short-circuits when SendGrid is
// unconfigured) so the reset-password test never tries to send real mail.
delete process.env.SENDGRID_API_KEY;
delete process.env.SENDGRID_FROM_USER;

const { importTsModule } = await import("./auth-test-helpers.mjs");
const { SqliteSessionStore, sessionsTableDdl } =
  await importTsModule("session-store.ts");
const authRouter = (await importTsModule("../routes/auth.ts")).default;

// The test's own view of the data DB (the auth router has its own connection to
// the same file via the bundled @workspace/db). Mirror the production pragmas so
// the two connections coexist without SQLITE_BUSY.
const sqlite = new Database(dbFile);
sqlite.pragma("journal_mode = WAL");
sqlite.pragma("foreign_keys = ON");
sqlite.pragma("busy_timeout = 4000");

// Schema identical to the startup bootstrap in index.ts.
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
  CREATE TABLE IF NOT EXISTS password_resets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token       TEXT    NOT NULL UNIQUE,
    expires_at  INTEGER NOT NULL,
    used_at     INTEGER,
    created_at  INTEGER NOT NULL
  );
`);

// drizzle's `integer({ mode: "timestamp" })` stores/compares Unix SECONDS, so
// manual inserts must use seconds too or the expiry comparison breaks.
const nowSec = () => Math.floor(Date.now() / 1000);

function resetDb() {
  sqlite.exec("DELETE FROM password_resets; DELETE FROM users;");
}

async function createUser(email, password, name) {
  const hash = await bcrypt.hash(password, 12);
  const ts = nowSec();
  const info = sqlite
    .prepare(
      "INSERT INTO users (email, name, password_hash, login_count, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
    )
    .run(email.toLowerCase(), name, hash, ts, ts);
  return Number(info.lastInsertRowid);
}

function insertReset(userId, token, expiresAtSec) {
  sqlite
    .prepare(
      "INSERT INTO password_resets (user_id, token, expires_at, used_at, created_at) VALUES (?, ?, ?, NULL, ?)",
    )
    .run(userId, token, expiresAtSec, nowSec());
}

// forgot-password responds BEFORE it writes the token (fire-and-forget after the
// response), so poll the DB until the row appears.
async function waitForToken(userId, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const row = sqlite
      .prepare(
        "SELECT token FROM password_resets WHERE user_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1",
      )
      .get(userId);
    if (row) return row.token;
    await new Promise((r) => setTimeout(r, 25));
  }
  return null;
}

/** Boot an app wired like the real server: session + auth router under /api. */
async function bootApp() {
  const sessionDb = new Database(":memory:");
  sessionDb.exec(sessionsTableDdl());

  const app = express();
  app.use(express.json());
  app.use(
    session({
      secret: "test-secret",
      store: new SqliteSessionStore({ client: sessionDb }),
      resave: false,
      saveUninitialized: false,
      cookie: { secure: false, httpOnly: true, maxAge: 60 * 60 * 1000 },
    }),
  );
  app.use("/api", authRouter);

  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();
  return {
    base: `http://127.0.0.1:${port}`,
    close: () =>
      new Promise((resolve) => {
        server.close(resolve);
        sessionDb.close();
      }),
  };
}

function post(base, route, body) {
  return fetch(`${base}${route}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

test("[auth-routes] register hashes the password, establishes a session, and rejects duplicates with 409", async () => {
  resetDb();
  const { base, close } = await bootApp();
  try {
    const res = await post(base, "/api/auth/register", {
      email: "NewUser@Example.com",
      password: "supersecret1",
      name: "New User",
    });
    assert.strictEqual(res.status, 201);
    const body = await res.json();
    // Email is normalised to lowercase on the way in.
    assert.strictEqual(body.user.email, "newuser@example.com");

    const cookie = res.headers.get("set-cookie");
    assert.ok(cookie, "register must establish a session cookie");

    // The password is stored bcrypt-hashed, never in plaintext.
    const row = sqlite
      .prepare("SELECT password_hash FROM users WHERE email = ?")
      .get("newuser@example.com");
    assert.ok(row, "the user row must be created");
    assert.ok(
      row.password_hash.startsWith("$2"),
      "password must be bcrypt-hashed",
    );
    assert.notStrictEqual(row.password_hash, "supersecret1");

    // The issued session authenticates a follow-up /me.
    const me = await fetch(`${base}/api/auth/me`, {
      headers: { cookie: cookie.split(";")[0] },
    });
    assert.strictEqual(me.status, 200);
    assert.strictEqual((await me.json()).email, "newuser@example.com");

    // A duplicate email (case-insensitive) is rejected with 409.
    const dup = await post(base, "/api/auth/register", {
      email: "newuser@example.com",
      password: "anotherpass1",
      name: "Dup User",
    });
    assert.strictEqual(dup.status, 409);
  } finally {
    await close();
  }
});

test("[auth-routes] login rejects bad credentials with 401 and accepts valid ones, updating loginCount/lastLogin", async () => {
  resetDb();
  const userId = await createUser("user@example.com", "correct-horse", "Test User");
  const { base, close } = await bootApp();
  try {
    // Wrong password → 401, no session.
    let res = await post(base, "/api/auth/login", {
      email: "user@example.com",
      password: "wrong-password",
    });
    assert.strictEqual(res.status, 401);
    assert.ok(!res.headers.get("set-cookie"), "a failed login issues no session");

    // Unknown email → 401.
    res = await post(base, "/api/auth/login", {
      email: "nobody@example.com",
      password: "whatever-pass",
    });
    assert.strictEqual(res.status, 401);

    // Valid credentials → 200 + a session.
    res = await post(base, "/api/auth/login", {
      email: "user@example.com",
      password: "correct-horse",
    });
    assert.strictEqual(res.status, 200);
    const cookie = res.headers.get("set-cookie");
    assert.ok(cookie, "a successful login must issue a session cookie");

    // loginCount is incremented and lastLogin is stamped.
    const row = sqlite
      .prepare("SELECT login_count, last_login FROM users WHERE id = ?")
      .get(userId);
    assert.strictEqual(row.login_count, 1);
    assert.ok(row.last_login != null, "lastLogin must be set on a valid login");

    // The session authenticates /me.
    const me = await fetch(`${base}/api/auth/me`, {
      headers: { cookie: cookie.split(";")[0] },
    });
    assert.strictEqual(me.status, 200);
  } finally {
    await close();
  }
});

test("[auth-routes] logout destroys the session so a follow-up /me returns 401", async () => {
  resetDb();
  await createUser("logout@example.com", "password123", "Logout User");
  const { base, close } = await bootApp();
  try {
    const login = await post(base, "/api/auth/login", {
      email: "logout@example.com",
      password: "password123",
    });
    assert.strictEqual(login.status, 200);
    const cookie = login.headers.get("set-cookie").split(";")[0];

    // /me works while the session is live.
    let me = await fetch(`${base}/api/auth/me`, { headers: { cookie } });
    assert.strictEqual(me.status, 200);

    // Logout destroys the session.
    const out = await fetch(`${base}/api/auth/logout`, {
      method: "POST",
      headers: { cookie },
    });
    assert.strictEqual(out.status, 200);

    // The same cookie is now unauthenticated.
    me = await fetch(`${base}/api/auth/me`, { headers: { cookie } });
    assert.strictEqual(me.status, 401);
  } finally {
    await close();
  }
});

test("[auth-routes] forgot/reset-password: a valid token resets the password once; reuse, expired, and unknown tokens all 400", async () => {
  resetDb();
  const userId = await createUser("reset@example.com", "oldpassword1", "Reset User");
  const { base, close } = await bootApp();
  try {
    // Requesting a reset always 200s (no account enumeration) and persists a
    // token out-of-band.
    const forgot = await post(base, "/api/auth/forgot-password", {
      email: "reset@example.com",
    });
    assert.strictEqual(forgot.status, 200);

    const token = await waitForToken(userId);
    assert.ok(token, "a reset token must be persisted for a known account");

    // A valid, unexpired, unused token resets the password.
    const reset = await post(base, "/api/auth/reset-password", {
      token,
      password: "newpassword1",
    });
    assert.strictEqual(reset.status, 200);

    // The new password now logs in; the old one would not.
    const login = await post(base, "/api/auth/login", {
      email: "reset@example.com",
      password: "newpassword1",
    });
    assert.strictEqual(login.status, 200);

    // Single-use: reusing the same (now-consumed) token → 400.
    const reuse = await post(base, "/api/auth/reset-password", {
      token,
      password: "anotherpass1",
    });
    assert.strictEqual(reuse.status, 400);

    // An expired (but unused) token → 400.
    const expiredToken = "expired00000000000000000000000000000000000000000000000000000000";
    insertReset(userId, expiredToken, nowSec() - 60);
    const expired = await post(base, "/api/auth/reset-password", {
      token: expiredToken,
      password: "whateverpass1",
    });
    assert.strictEqual(expired.status, 400);

    // A token that was never issued → 400.
    const unknown = await post(base, "/api/auth/reset-password", {
      token: "doesnotexist0000000000000000000000000000000000000000000000000000",
      password: "whateverpass1",
    });
    assert.strictEqual(unknown.status, 400);
  } finally {
    await close();
  }
});

test.after(() => sqlite.close());
