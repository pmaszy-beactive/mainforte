/**
 * Resolve the session secret used to sign session cookies.
 *
 * In development we fall back to a fixed, clearly-insecure value so login works
 * out of the box with no setup. In production we REFUSE to start without an
 * explicit SESSION_SECRET — silently using a hardcoded fallback there would
 * make every session forgeable.
 *
 * Kept dependency-free (only reads process.env) so it can be unit-tested in
 * isolation and imported by app.ts without pulling in the whole app graph.
 */
export function resolveSessionSecret(): string {
  const secret = process.env.SESSION_SECRET;
  if (secret && secret.length > 0) {
    return secret;
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "SESSION_SECRET is required in production but was not set. Refusing to " +
        "start with an insecure fallback secret.",
    );
  }
  return "dev-only-insecure-session-secret";
}
