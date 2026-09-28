// Locks the hardening that put the entities data endpoint behind a login:
// `GET /api/entities/:source` must return 401 with no session and 200 once a
// session exists. Previously the endpoint was open, so any unauthenticated
// caller could read a tenant's data; requireAuth now gates it.
//
// This boots a real Express app wired exactly like the production server:
//   - the real express-session middleware backed by the real SqliteSessionStore
//   - the real entities router (which mounts the real requireAuth middleware)
// so the assertion exercises the genuine auth path end-to-end over HTTP.
//
// DATABASE_URL is pointed at a temp file before importing anything that touches
// @workspace/db so the entities router reads a throwaway DB (no real data, and
// the missing entities table simply yields an empty-but-200 payload).
import test from "node:test";
import assert from "node:assert";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import express from "express";
import session from "express-session";
import Database from "better-sqlite3";

const tmpDir = mkdtempSync(path.join(os.tmpdir(), "auth-gate-test-"));
process.env.DATABASE_URL = `file:${path.join(tmpDir, "data.db")}`;
process.env.NODE_ENV = "development";

const { importTsModule } = await import("./auth-test-helpers.mjs");
const { SqliteSessionStore, sessionsTableDdl } =
  await importTsModule("session-store.ts");
const entitiesRouter = (await importTsModule("../routes/entities.ts")).default;

/** Boot an app wired like the real server: session + entities router. */
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
  // Stand-in for the real login route: establishes an authenticated session.
  app.post("/login", (req, res) => {
    req.session.userId = 1;
    res.json({ ok: true });
  });
  app.use("/api", entitiesRouter);

  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}`;
  return {
    base,
    close: () =>
      new Promise((resolve) => {
        server.close(resolve);
        sessionDb.close();
      }),
  };
}

test("[auth-gate] GET /api/entities/:source returns 401 without a session", async () => {
  const { base, close } = await bootApp();
  try {
    const res = await fetch(`${base}/api/entities/stripe.sales`);
    assert.strictEqual(res.status, 401);
    const body = await res.json();
    assert.strictEqual(body.error, "Not authenticated");
  } finally {
    await close();
  }
});

test("[auth-gate] GET /api/entities/:source returns 200 with a session", async () => {
  const { base, close } = await bootApp();
  try {
    // Log in and capture the session cookie.
    const loginRes = await fetch(`${base}/login`, { method: "POST" });
    assert.strictEqual(loginRes.status, 200);
    const cookie = loginRes.headers.get("set-cookie");
    assert.ok(cookie, "login must issue a session cookie");

    const res = await fetch(`${base}/api/entities/stripe.sales`, {
      headers: { cookie: cookie.split(";")[0] },
    });
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    // The throwaway DB has no entities table → empty rows + unknown status.
    assert.deepStrictEqual(body.rows, []);
    assert.strictEqual(body.status.status, "unknown");
  } finally {
    await close();
  }
});
