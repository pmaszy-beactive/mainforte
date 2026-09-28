// Shared helpers for the auth/session unit tests.
//
// The api-server is npm-standardized and does NOT depend on tsx, so the
// existing tests (api-host.test.mjs, source-status.test.mjs) transform a single
// dependency-free TypeScript file on the fly with esbuild and import it from a
// `data:` URL. That trick only works for modules with no runtime imports — a
// `data:` URL has no parent path, so bare specifiers like `express-session` or
// `@workspace/db` can't be resolved from it.
//
// The auth/session modules under test DO have runtime imports, so here we
// instead BUNDLE the TS entry with esbuild (`packages: "external"` keeps every
// node_modules / workspace dependency as a runtime import) and write the output
// to a temp `.mjs` file INSIDE this package directory. Importing it from a real
// path lets Node resolve those external deps from node_modules normally, while
// the module's own relative imports are bundled in. The temp file is removed
// after import (the module is already cached by then).
import { build } from "esbuild";
import { writeFile, unlink } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Real node_modules / npm dependencies are kept EXTERNAL so the bundle imports
// them from node_modules at runtime (resolvable from a real file path, and —
// for express/express-session — sharing the one instance the test also loads).
//
// `@workspace/db` and `@workspace/api-zod` are deliberately NOT in this list so
// esbuild BUNDLES their TypeScript source instead. Node can't import either at
// runtime: `@workspace/db`'s index does a directory import of `./schema`, and
// `@workspace/api-zod`'s `exports` point at a raw `.ts` file whose own imports
// are extensionless (`./generated/api`) — both unresolvable by Node's ESM
// loader. This is exactly why the production server bundles them too via
// build.mjs.
const EXTERNAL = [
  "@sendgrid/mail",
  "bcrypt",
  "better-sqlite3",
  "cookie-parser",
  "cors",
  "drizzle-orm",
  "express",
  "express-session",
  "pino",
  "pino-http",
  "pino-pretty",
  "thread-stream",
  "ws",
];

/**
 * Bundle a TypeScript module (relative to src/lib) and import it.
 * @param {string} relPath e.g. "session-store.ts" or "../routes/entities.ts"
 */
export async function importTsModule(relPath) {
  const entry = path.resolve(__dirname, relPath);
  const result = await build({
    entryPoints: [entry],
    bundle: true,
    format: "esm",
    platform: "node",
    external: EXTERNAL,
    write: false,
    logLevel: "silent",
  });
  const code = result.outputFiles[0].text;
  const tmp = path.join(
    __dirname,
    `.auth-test-${Date.now()}-${Math.random().toString(36).slice(2)}.mjs`,
  );
  await writeFile(tmp, code);
  try {
    return await import(pathToFileURL(tmp).href);
  } finally {
    await unlink(tmp).catch(() => {});
  }
}
