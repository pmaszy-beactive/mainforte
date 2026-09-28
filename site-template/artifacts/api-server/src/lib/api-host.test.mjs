// Regression: when API_HOST is injected with a scheme prefix
// (e.g. "https://host.example.test"), the site-template must normalize it
// before building the status WebSocket URL and the container-rebuild
// callback URL. Otherwise the URL becomes `wss://https://host/...` and DNS
// lookup fails with ENOTFOUND "https" — the site never reports healthy and
// the build hangs until it is marked failed.
//
// The widget template hit this exact double-scheme outage and fixed it; this
// locks the equivalent fix for the site template so a future edit can't
// reintroduce it.
//
// This test transforms the TypeScript normalizer on the fly with esbuild
// (already a devDependency) so it runs under plain `node --test` without
// pulling in a TS test runner — the site-template is npm-standardized and
// does not depend on tsx.
import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { transform } from "esbuild";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const tsSource = readFileSync(path.join(__dirname, "api-host.ts"), "utf8");
const { code } = await transform(tsSource, { loader: "ts", format: "esm" });
const { normalizeApiHost } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
);

test("[api-host] strips a leading https:// scheme", () => {
  assert.strictEqual(normalizeApiHost("https://claw.activeaidemo.com"), "claw.activeaidemo.com");
});

test("[api-host] strips http://, ws://, wss:// schemes (case-insensitive)", () => {
  assert.strictEqual(normalizeApiHost("http://host.example.test"), "host.example.test");
  assert.strictEqual(normalizeApiHost("ws://host.example.test"), "host.example.test");
  assert.strictEqual(normalizeApiHost("wss://host.example.test"), "host.example.test");
  assert.strictEqual(normalizeApiHost("HTTPS://Host.Example.Test"), "Host.Example.Test");
});

test("[api-host] strips trailing slashes", () => {
  assert.strictEqual(normalizeApiHost("https://host.example.test/"), "host.example.test");
  assert.strictEqual(normalizeApiHost("host.example.test///"), "host.example.test");
});

test("[api-host] leaves a bare host unchanged (no behavior change)", () => {
  assert.strictEqual(normalizeApiHost("claw.activeaidemo.com"), "claw.activeaidemo.com");
  assert.strictEqual(normalizeApiHost("localhost:8000"), "localhost:8000");
});

test("[api-host] passes through empty/unset input", () => {
  assert.strictEqual(normalizeApiHost(""), "");
  assert.strictEqual(normalizeApiHost(undefined), "");
  assert.strictEqual(normalizeApiHost(null), "");
});

test("[api-host] derived WS URL has a single scheme for scheme-prefixed input", () => {
  const apiHost = normalizeApiHost("https://claw.activeaidemo.com");
  const wsUrl = `wss://${apiHost}/ws/site-status?siteId=s1&key=k1`;
  assert.strictEqual(wsUrl, "wss://claw.activeaidemo.com/ws/site-status?siteId=s1&key=k1");
  assert.ok(!/wss:\/\/(https?|wss?):\/\//.test(wsUrl), "WS URL must not contain a doubled scheme");
});

test("[api-host] derived rebuild-callback URL has a single scheme", () => {
  const apiHost = normalizeApiHost("https://claw.activeaidemo.com/");
  const protocol = apiHost.startsWith("localhost") ? "http" : "https";
  const url = `${protocol}://${apiHost}/api/sites/container/rebuild`;
  assert.strictEqual(url, "https://claw.activeaidemo.com/api/sites/container/rebuild");
  assert.ok(!/https:\/\/https/.test(url), "callback URL must not contain a doubled scheme");
});
