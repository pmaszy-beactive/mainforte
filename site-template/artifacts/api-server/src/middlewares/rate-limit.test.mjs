// Boots a throwaway Express server wired exactly like routes/auth.ts and
// asserts the auth rate limiters throttle abusive callers with a 429 while
// leaving legitimate traffic alone.
//
// rate-limit.ts is dependency-free (only type-only express imports) so it can be
// transformed on the fly with esbuild — the same pattern source-status.test.mjs
// uses — and exercised over a real HTTP server.
import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import http from "node:http";
import { transform } from "esbuild";
import express from "express";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function loadModule(env = {}) {
  const prev = {};
  for (const [k, v] of Object.entries(env)) {
    prev[k] = process.env[k];
    process.env[k] = v;
  }
  try {
    const tsSource = readFileSync(path.join(__dirname, "rate-limit.ts"), "utf8");
    const { code } = await transform(tsSource, { loader: "ts", format: "esm" });
    // Cache-bust so each load gets fresh in-memory counters.
    const url = `data:text/javascript;base64,${Buffer.from(
      `${code}\n//# ${Math.random()}`,
    ).toString("base64")}`;
    return await import(url);
  } finally {
    for (const [k, v] of Object.entries(prev)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

/** Boot an Express app exposing the login + register + forgot routes. */
async function bootApp(mod, { validPassword = "correct" } = {}) {
  const app = express();
  app.set("trust proxy", 1);
  app.use(express.json());

  app.post("/api/auth/login", mod.loginRateLimit, (req, res) => {
    const { password } = req.body ?? {};
    if (password !== validPassword) {
      mod.recordFailedLogin(req);
      res.status(401).json({ error: "Invalid email or password" });
      return;
    }
    mod.clearLoginAttempts(req);
    res.json({ message: "Login successful" });
  });

  app.post("/api/auth/register", mod.registerRateLimit, (_req, res) => {
    res.status(201).json({ message: "Registration successful" });
  });

  app.post("/api/auth/forgot-password", mod.forgotPasswordRateLimit, (_req, res) => {
    res.json({ message: "If an account with that email exists..." });
  });

  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const post = async (route, body, headers = {}) => {
    const r = await fetch(`http://127.0.0.1:${port}${route}`, {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body ?? {}),
    });
    let json = null;
    try {
      json = await r.json();
    } catch {
      json = null;
    }
    return { status: r.status, retryAfter: r.headers.get("retry-after"), body: json };
  };

  const close = () => new Promise((resolve) => server.close(resolve));
  return { post, close };
}

test("[rate-limit] login throttles repeated failures by IP with a 429", async () => {
  const mod = await loadModule({
    LOGIN_RATE_LIMIT_MAX_PER_IP: "5",
    LOGIN_RATE_LIMIT_MAX_PER_EMAIL: "100",
  });
  const { post, close } = await bootApp(mod);
  try {
    // Vary the email so the per-email limiter is never the one that trips —
    // isolates the per-IP path.
    for (let i = 0; i < 5; i++) {
      const { status } = await post(
        "/api/auth/login",
        { email: `user${i}@example.com`, password: "wrong" },
        { "x-forwarded-for": "203.0.113.7" },
      );
      assert.strictEqual(status, 401, `attempt ${i} should be a normal 401`);
    }
    const blocked = await post(
      "/api/auth/login",
      { email: "user-final@example.com", password: "wrong" },
      { "x-forwarded-for": "203.0.113.7" },
    );
    assert.strictEqual(blocked.status, 429);
    assert.strictEqual(blocked.body.code, "RATE_LIMIT_EXCEEDED");
    assert.ok(Number(blocked.retryAfter) > 0, "Retry-After header should be set");
  } finally {
    await close();
  }
});

test("[rate-limit] login throttles repeated failures by email across IPs", async () => {
  const mod = await loadModule({
    LOGIN_RATE_LIMIT_MAX_PER_IP: "100",
    LOGIN_RATE_LIMIT_MAX_PER_EMAIL: "3",
  });
  const { post, close } = await bootApp(mod);
  try {
    for (let i = 0; i < 3; i++) {
      const { status } = await post(
        "/api/auth/login",
        { email: "victim@example.com", password: "wrong" },
        { "x-forwarded-for": `198.51.100.${i}` },
      );
      assert.strictEqual(status, 401, `attempt ${i} should be a normal 401`);
    }
    const blocked = await post(
      "/api/auth/login",
      { email: "victim@example.com", password: "wrong" },
      { "x-forwarded-for": "198.51.100.250" },
    );
    assert.strictEqual(blocked.status, 429);
  } finally {
    await close();
  }
});

test("[rate-limit] a successful login clears the failed-attempt budget", async () => {
  const mod = await loadModule({
    LOGIN_RATE_LIMIT_MAX_PER_IP: "3",
    LOGIN_RATE_LIMIT_MAX_PER_EMAIL: "3",
  });
  const { post, close } = await bootApp(mod, { validPassword: "correct" });
  try {
    const ip = "192.0.2.42";
    const email = "legit@example.com";
    // Two wrong tries...
    for (let i = 0; i < 2; i++) {
      const { status } = await post(
        "/api/auth/login",
        { email, password: "wrong" },
        { "x-forwarded-for": ip },
      );
      assert.strictEqual(status, 401);
    }
    // ...then the right one, which should succeed AND reset the counters.
    const ok = await post(
      "/api/auth/login",
      { email, password: "correct" },
      { "x-forwarded-for": ip },
    );
    assert.strictEqual(ok.status, 200);

    // Budget is replenished: three more wrong tries are all plain 401s, not 429.
    for (let i = 0; i < 3; i++) {
      const { status } = await post(
        "/api/auth/login",
        { email, password: "wrong" },
        { "x-forwarded-for": ip },
      );
      assert.strictEqual(status, 401, `post-reset attempt ${i} should be 401`);
    }
  } finally {
    await close();
  }
});

test("[rate-limit] register throttles bulk account creation per IP", async () => {
  const mod = await loadModule({ REGISTER_RATE_LIMIT_MAX_PER_IP: "3" });
  const { post, close } = await bootApp(mod);
  try {
    const ip = "203.0.113.99";
    for (let i = 0; i < 3; i++) {
      const { status } = await post(
        "/api/auth/register",
        { email: `new${i}@example.com` },
        { "x-forwarded-for": ip },
      );
      assert.strictEqual(status, 201, `register ${i} should succeed`);
    }
    const blocked = await post(
      "/api/auth/register",
      { email: "new-final@example.com" },
      { "x-forwarded-for": ip },
    );
    assert.strictEqual(blocked.status, 429);
    assert.strictEqual(blocked.body.code, "RATE_LIMIT_EXCEEDED");
  } finally {
    await close();
  }
});

test("[rate-limit] forgot-password throttles reset spamming per IP", async () => {
  const mod = await loadModule({ FORGOT_PASSWORD_RATE_LIMIT_MAX_PER_IP: "2" });
  const { post, close } = await bootApp(mod);
  try {
    const ip = "203.0.113.5";
    for (let i = 0; i < 2; i++) {
      const { status } = await post(
        "/api/auth/forgot-password",
        { email: "x@example.com" },
        { "x-forwarded-for": ip },
      );
      assert.strictEqual(status, 200);
    }
    const blocked = await post(
      "/api/auth/forgot-password",
      { email: "x@example.com" },
      { "x-forwarded-for": ip },
    );
    assert.strictEqual(blocked.status, 429);
  } finally {
    await close();
  }
});
