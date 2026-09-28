import pino from "pino";
import pretty from "pino-pretty";

const isProduction = process.env.NODE_ENV === "production";

// In development we want human-readable, colorized logs. pino's `transport`
// option spawns a separate WORKER THREAD (via thread-stream) to run
// pino-pretty. When the api-server is bundled by esbuild (build.mjs), that
// worker is fragile: on boot it crashes the whole process with
// "thread-stream: this should not happen: undefined", taking the api-server
// down. Instead we run pino-pretty as a SYNCHRONOUS in-process stream — same
// pretty output, no worker thread, bundler-safe. Production stays on the
// default fast JSON-to-stdout destination (no pretty-printing, no worker).
const prettyStream = isProduction
  ? undefined
  : pretty({
      colorize: true,
      translateTime: "yyyy-mm-dd HH:MM:ss.l",
      // Drop the nested request objects so each pino-http request log renders
      // as the single formatted message line (see app.ts). pid/hostname are
      // noise; req/res/responseTime/err are already folded into that message.
      ignore: "pid,hostname,req,res,responseTime,err",
    });

export const logger = pino(
  {
    level: process.env.LOG_LEVEL ?? "info",
    timestamp: pino.stdTimeFunctions.isoTime,
    redact: [
      "req.headers.authorization",
      "req.headers.cookie",
      "res.headers['set-cookie']",
    ],
  },
  prettyStream,
);
