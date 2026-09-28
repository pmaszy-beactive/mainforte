import type { Request, Response, NextFunction } from "express";

// ── In-memory rate limiting for the auth endpoints ────────────────────────────
//
// A deployed site's `POST /api/auth/login` (and register / forgot-password) are
// the main brute-force attack surface, so we throttle abusive callers with a
// clear 429 response. Everything is kept in-process: a single site-template
// container serves one tenant, so a Map keyed by IP / email is enough and avoids
// pulling in Redis or another dependency.
//
// Two distinct shapes are used:
//   • Login uses FAILED-attempt accounting — the budget is only consumed by a
//     wrong password, and a successful login clears it. This keeps legitimate
//     users (who occasionally fat-finger a password) from ever being locked out.
//   • Register / forgot-password use plain per-request accounting — every call
//     counts, since there is no notion of "success vs failure" to key off.
//
// All limits are configurable via env vars (see the constants below) so an
// operator can loosen or tighten them without a code change.

interface Counter {
  count: number;
  windowStart: number;
}

function envInt(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw.trim() === "") return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/**
 * A fixed-window counter keyed by an arbitrary string. Expired windows are
 * swept lazily on access and periodically in the background so the Map can't
 * grow without bound.
 */
class WindowedCounter {
  private readonly map = new Map<string, Counter>();

  constructor(
    private readonly windowMs: number,
    private readonly max: number,
  ) {
    const timer = setInterval(() => this.sweep(), windowMs);
    // Don't keep the event loop alive just for the sweep (matters for tests and
    // graceful shutdown).
    timer.unref?.();
  }

  private sweep(): void {
    const cutoff = Date.now() - this.windowMs;
    for (const [key, entry] of this.map) {
      if (entry.windowStart < cutoff) this.map.delete(key);
    }
  }

  /** Report whether `key` is already at/over its limit, without incrementing. */
  isLimited(key: string): { limited: boolean; retryAfter: number } {
    const entry = this.map.get(key);
    if (!entry) return { limited: false, retryAfter: 0 };

    const now = Date.now();
    if (now - entry.windowStart > this.windowMs) {
      this.map.delete(key);
      return { limited: false, retryAfter: 0 };
    }

    if (entry.count >= this.max) {
      const retryAfter = Math.ceil((entry.windowStart + this.windowMs - now) / 1000);
      return { limited: true, retryAfter: Math.max(retryAfter, 1) };
    }
    return { limited: false, retryAfter: 0 };
  }

  /** Count one event against `key`, starting a fresh window if needed. */
  increment(key: string): void {
    const now = Date.now();
    const entry = this.map.get(key);
    if (!entry || now - entry.windowStart > this.windowMs) {
      this.map.set(key, { count: 1, windowStart: now });
      return;
    }
    entry.count += 1;
  }

  /** Forget all accounting for `key` (e.g. after a successful login). */
  reset(key: string): void {
    this.map.delete(key);
  }
}

function clientIp(req: Request): string {
  const forwarded = (req.headers["x-forwarded-for"] as string | undefined)
    ?.split(",")[0]
    ?.trim();
  return forwarded || req.ip || "unknown";
}

function emailKey(req: Request): string | null {
  const email = (req.body as { email?: unknown } | undefined)?.email;
  if (typeof email !== "string") return null;
  const trimmed = email.trim().toLowerCase();
  return trimmed.length > 0 ? trimmed : null;
}

function tooManyRequests(res: Response, retryAfter: number, message: string): void {
  res.setHeader("Retry-After", String(retryAfter));
  res.status(429).json({
    error: message,
    code: "RATE_LIMIT_EXCEEDED",
    retryAfter,
  });
}

// ── Login (failed-attempt accounting) ─────────────────────────────────────────

const LOGIN_WINDOW_MS = envInt("LOGIN_RATE_LIMIT_WINDOW_MS", 15 * 60 * 1000); // 15 min
const LOGIN_MAX_PER_IP = envInt("LOGIN_RATE_LIMIT_MAX_PER_IP", 20);
const LOGIN_MAX_PER_EMAIL = envInt("LOGIN_RATE_LIMIT_MAX_PER_EMAIL", 10);

const loginIpCounter = new WindowedCounter(LOGIN_WINDOW_MS, LOGIN_MAX_PER_IP);
const loginEmailCounter = new WindowedCounter(LOGIN_WINDOW_MS, LOGIN_MAX_PER_EMAIL);

/**
 * Gate `POST /auth/login`. Rejects before any password check once an IP (or a
 * targeted email) has accumulated too many recent FAILED attempts. The budget
 * is replenished by `clearLoginAttempts` on a successful login.
 */
export function loginRateLimit(req: Request, res: Response, next: NextFunction): void {
  const ip = clientIp(req);
  const ipCheck = loginIpCounter.isLimited(ip);
  if (ipCheck.limited) {
    tooManyRequests(res, ipCheck.retryAfter, "Too many failed login attempts. Please try again later.");
    return;
  }

  const email = emailKey(req);
  if (email) {
    const emailCheck = loginEmailCounter.isLimited(email);
    if (emailCheck.limited) {
      tooManyRequests(
        res,
        emailCheck.retryAfter,
        "Too many failed login attempts for this account. Please try again later.",
      );
      return;
    }
  }

  next();
}

/** Record one failed login against both the caller IP and the target email. */
export function recordFailedLogin(req: Request): void {
  loginIpCounter.increment(clientIp(req));
  const email = emailKey(req);
  if (email) loginEmailCounter.increment(email);
}

/** Clear the failed-login budget after a successful authentication. */
export function clearLoginAttempts(req: Request): void {
  loginIpCounter.reset(clientIp(req));
  const email = emailKey(req);
  if (email) loginEmailCounter.reset(email);
}

// ── Register / forgot-password (per-request accounting) ───────────────────────

function perRequestIpLimit(counter: WindowedCounter, message: string) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const ip = clientIp(req);
    const check = counter.isLimited(ip);
    if (check.limited) {
      tooManyRequests(res, check.retryAfter, message);
      return;
    }
    counter.increment(ip);
    next();
  };
}

const REGISTER_WINDOW_MS = envInt("REGISTER_RATE_LIMIT_WINDOW_MS", 60 * 60 * 1000); // 1 h
const REGISTER_MAX_PER_IP = envInt("REGISTER_RATE_LIMIT_MAX_PER_IP", 10);
const registerCounter = new WindowedCounter(REGISTER_WINDOW_MS, REGISTER_MAX_PER_IP);

const FORGOT_WINDOW_MS = envInt("FORGOT_PASSWORD_RATE_LIMIT_WINDOW_MS", 60 * 60 * 1000); // 1 h
const FORGOT_MAX_PER_IP = envInt("FORGOT_PASSWORD_RATE_LIMIT_MAX_PER_IP", 10);
const forgotCounter = new WindowedCounter(FORGOT_WINDOW_MS, FORGOT_MAX_PER_IP);

/** Gate `POST /auth/register` — throttles bulk account creation from one IP. */
export const registerRateLimit = perRequestIpLimit(
  registerCounter,
  "Too many registration attempts. Please try again later.",
);

/** Gate `POST /auth/forgot-password` — throttles reset-email spamming from one IP. */
export const forgotPasswordRateLimit = perRequestIpLimit(
  forgotCounter,
  "Too many password reset requests. Please try again later.",
);
