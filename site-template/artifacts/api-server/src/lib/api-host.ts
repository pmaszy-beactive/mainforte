// Shared API_HOST normalizer. The platform sometimes injects API_HOST with
// a scheme prepended (e.g. "https://host.example.com"), which would produce
// malformed URLs like `wss://https://host/path` (DNS lookup fails with
// ENOTFOUND "https") when a consumer concatenates `wss://${API_HOST}`.
//
// The widget template hit and fixed this exact double-scheme outage with a
// single shared normalizer (src/lib/api-host.js); the site template never
// got the equivalent fix and built both the status WebSocket URL and the
// container-rebuild callback URL from the raw value. This module is the
// single source of truth so all site-template consumers agree.
//
// The dev-runner's `env > .env` precedence (scripts/dev-runner.sh) lets a
// scheme-prefixed value from the process environment win over the clean
// value provisioning writes to .env, so the consumer must tolerate a scheme
// either way — this is the authoritative guard.
export function normalizeApiHost(raw: string | undefined | null): string {
  if (!raw) return "";
  let h = String(raw).trim();
  h = h.replace(/^(?:https?|wss?):\/\//i, "");
  h = h.replace(/\/+$/, "");
  return h;
}
