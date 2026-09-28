// Locks the production hardening of resolveSessionSecret (extracted from app.ts
// into session-secret.ts so it is testable in isolation): production REFUSES to
// boot without an explicit SESSION_SECRET rather than silently falling back to a
// hardcoded — and therefore forgeable — secret, while development keeps working
// out of the box.
//
// The module is dependency-free (only reads process.env), so it is transformed
// on the fly with esbuild and imported from a data: URL — the same pattern
// api-host.test.mjs / source-status.test.mjs use.
import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { transform } from "esbuild";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const tsSource = readFileSync(path.join(__dirname, "session-secret.ts"), "utf8");
const { code } = await transform(tsSource, { loader: "ts", format: "esm" });
const { resolveSessionSecret } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
);

// Snapshot + restore the two env vars each test touches so tests don't leak.
function withEnv(env, fn) {
  const prev = {
    NODE_ENV: process.env.NODE_ENV,
    SESSION_SECRET: process.env.SESSION_SECRET,
  };
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  try {
    return fn();
  } finally {
    for (const k of ["NODE_ENV", "SESSION_SECRET"]) {
      if (prev[k] === undefined) delete process.env[k];
      else process.env[k] = prev[k];
    }
  }
}

test("[session-secret] throws in production when SESSION_SECRET is unset", () => {
  withEnv({ NODE_ENV: "production", SESSION_SECRET: undefined }, () => {
    assert.throws(
      () => resolveSessionSecret(),
      /SESSION_SECRET is required in production/,
    );
  });
});

test("[session-secret] throws in production when SESSION_SECRET is empty", () => {
  withEnv({ NODE_ENV: "production", SESSION_SECRET: "" }, () => {
    assert.throws(() => resolveSessionSecret(), /SESSION_SECRET is required/);
  });
});

test("[session-secret] returns the explicit secret in production", () => {
  withEnv({ NODE_ENV: "production", SESSION_SECRET: "super-secret-value" }, () => {
    assert.strictEqual(resolveSessionSecret(), "super-secret-value");
  });
});

test("[session-secret] falls back to the dev secret in development", () => {
  withEnv({ NODE_ENV: "development", SESSION_SECRET: undefined }, () => {
    assert.strictEqual(
      resolveSessionSecret(),
      "dev-only-insecure-session-secret",
    );
  });
});

test("[session-secret] prefers an explicit secret even in development", () => {
  withEnv({ NODE_ENV: "development", SESSION_SECRET: "my-dev-secret" }, () => {
    assert.strictEqual(resolveSessionSecret(), "my-dev-secret");
  });
});
