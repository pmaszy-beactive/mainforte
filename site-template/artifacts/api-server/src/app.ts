import express, { type Express } from "express";
import cors from "cors";
import session from "express-session";
import cookieParser from "cookie-parser";
import pinoHttp, { type Options } from "pino-http";
import type { IncomingMessage, ServerResponse } from "http";
import path from "path";
import fs from "fs";
import { pool } from "@workspace/db";
import router from "./routes";
import { logger } from "./lib/logger";
import { getVersion } from "./lib/version";
import { PgSessionStore } from "./lib/session-store";
import { resolveSessionSecret } from "./lib/session-secret";

const app: Express = express();

// Render each completed request as one compact line, e.g.
// `GET /api/rebuild-status 200 1ms`. The query string is stripped and the
// nested req/res/responseTime objects are suppressed by pino-pretty (see
// lib/logger.ts) so high-frequency polling doesn't flood the dev console.
function formatRequestLine(
  method: string | undefined,
  url: string | undefined,
  statusCode: number,
  responseTime: number,
): string {
  const path = (url ?? "").split("?")[0];
  return `${method} ${path} ${statusCode} ${Math.round(responseTime)}ms`;
}

app.use(
  pinoHttp({
    logger,
    customSuccessMessage(req, res, responseTime) {
      return formatRequestLine(req.method, req.url, res.statusCode, responseTime);
    },
    // pino-http (v10) passes responseTime as a 4th argument to the error
    // message builder at runtime even though its type only declares three.
    customErrorMessage: ((
      req: IncomingMessage,
      res: ServerResponse,
      _err: Error,
      responseTime: number,
    ) =>
      formatRequestLine(
        req.method,
        req.url,
        res.statusCode,
        responseTime,
      )) as Options["customErrorMessage"],
    // Successful liveness probes (`GET /health` → 2xx) fire every couple of
    // seconds and just drown out useful output, so suppress their
    // "request completed" line. A non-2xx /health (a real problem) is still
    // logged at warn/error like any other request.
    customLogLevel(req, res, err) {
      const url = req.url?.split("?")[0];
      if (url === "/health" && res.statusCode >= 200 && res.statusCode < 300 && !err) {
        return "silent";
      }
      if (res.statusCode >= 500 || err) {
        return "error";
      }
      if (res.statusCode >= 400) {
        return "warn";
      }
      return "info";
    },
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);

// mainforte's own subdomain scheme: a site is reachable at its preview host while in draft
// (proxied by mainforte's own backend, see sites/routes.py's preview_site) and at
// `{slug}.mainforte.ai` once published. Both are derivable from SUBDOMAIN (== Site.slug, set as
// a Jenkins job param — see sites/provisioning.py) plus the shared parent domain, rather than an
// env var the container has to be told to guess (the old REPLIT_DOMAINS/REPLIT_DEV_DOMAIN
// scheme this replaces).
const siteSubdomain = process.env.SUBDOMAIN;
const parentDomain = process.env.PARENT_DOMAIN || "mainforte.ai";
const allowedOrigins = siteSubdomain
  ? [`https://${siteSubdomain}.${parentDomain}`, `https://${parentDomain}`]
  : [];

app.use(
  cors({
    origin: allowedOrigins.length > 0 ? allowedOrigins : true,
    credentials: true,
  }),
);
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(cookieParser());

app.set("trust proxy", 1);

app.use(
  session({
    secret: resolveSessionSecret(),
    // Persist sessions in the same Postgres DB the app already connects to (this site's own
    // DATABASE_URL -- see PLAN.md's "Per-site Postgres provisioning") so they survive api-server
    // restarts (incl. `node --watch` respawns) and don't leak memory the way express-session's
    // default in-memory store does.
    store: new PgSessionStore({
      pool,
      ttlMs: 24 * 60 * 60 * 1000,
    }),
    resave: false,
    saveUninitialized: false,
    cookie: {
      secure: process.env.NODE_ENV === "production",
      httpOnly: true,
      maxAge: 24 * 60 * 60 * 1000,
      sameSite: "lax",
    },
  }),
);

app.get("/health", (_req, res) => {
  const version = getVersion();
  res.json({ status: "ok", version: version.version });
});

app.use("/api", router);

const staticDir = path.resolve(__dirname, "../../hello-world/dist/public");
const indexHtml = path.join(staticDir, "index.html");
if (process.env.NODE_ENV === "production" && fs.existsSync(indexHtml)) {
  app.use(express.static(staticDir));
  app.get("/*splat", (_req, res) => {
    res.sendFile(indexHtml, (err) => {
      if (err) {
        res.status(404).send("Not found");
      }
    });
  });
  logger.info({ staticDir }, "Serving static frontend");
} else if (process.env.NODE_ENV === "production") {
  logger.warn({ staticDir, indexHtml }, "Static frontend not built — run the hello-world build first");
}

export default app;
