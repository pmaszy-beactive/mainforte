import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build as esbuild } from "esbuild";
import esbuildPluginPino from "esbuild-plugin-pino";
import { mkdir, readdir, rename, rm } from "node:fs/promises";

// Plugins (e.g. 'esbuild-plugin-pino') may use `require` to resolve dependencies
globalThis.require = createRequire(import.meta.url);

const artifactDir = path.dirname(fileURLToPath(import.meta.url));

// The bundled entry. dev.sh runs `node --watch --watch-path=dist dist/<ENTRY>`,
// so the watcher both LOADS this file and watches the dist/ directory. The
// publish step below renames this file LAST so a reload is only ever triggered
// against a fully-populated dist/, and so the entry is never missing.
const ENTRY = "index.mjs";

// Atomically publish the freshly built staging dir into the live dist/ WITHOUT
// ever deleting dist/.
//
// The previous build did `rm -rf dist` *before* esbuild wrote the new output.
// `node --watch` (watching dist/) reacted to that deletion mid-build, tried to
// restart against the now-missing entry, hit MODULE_NOT_FOUND and parked
// "Waiting for file changes before restarting…" — never recovering. The inner
// API on DEV_PORT+1 stayed dead while Vite kept proxying /api and /health to a
// dead port (ECONNREFUSED). (task #778)
//
// Instead we rename each built file over the live dist/. rename(2) is atomic on
// the same filesystem (the staging dir is a sibling of dist/, so same fs), and
// crucially we NEVER remove dist/ itself — which also keeps `node --watch`'s
// directory watch alive. (Empirically, the old delete+recreate pattern silently
// stops reloading after the first rebuild because removing the watched dir
// drops the inotify watch; the rename-in-place pattern reloads reliably on
// every rebuild.) Stale files the new build no longer produces are pruned
// before the entry is swapped, and the entry is renamed LAST so once it lands
// every chunk it imports is already in place.
async function publishAtomically(stagingDir, distDir) {
  await mkdir(distDir, { recursive: true });

  const staged = await readdir(stagingDir, { withFileTypes: true });
  const stagedNames = new Set(staged.map((d) => d.name));
  if (!stagedNames.has(ENTRY)) {
    throw new Error(`build produced no ${ENTRY} in ${stagingDir}`);
  }

  // 1) Prune files in the live dist/ that the new build no longer produces, so
  //    a renamed/removed chunk does not linger. Never remove the entry here —
  //    it must stay present until its atomic replacement in step 3.
  const live = await readdir(distDir, { withFileTypes: true }).catch(() => []);
  for (const d of live) {
    if (d.name === ENTRY) continue;
    if (!stagedNames.has(d.name)) {
      await rm(path.join(distDir, d.name), { recursive: true, force: true });
    }
  }

  // 2) Move every built file EXCEPT the entry into place first (chunks, source
  //    maps, pino worker shims) so that once the entry lands all its imports
  //    already exist.
  for (const d of staged) {
    if (d.name === ENTRY) continue;
    await rename(path.join(stagingDir, d.name), path.join(distDir, d.name));
  }

  // 3) Move the entry LAST — the single atomic step that flips the served
  //    bundle and triggers `node --watch` to reload against a complete dist/.
  await rename(path.join(stagingDir, ENTRY), path.join(distDir, ENTRY));
}

async function buildAll() {
  const distDir = path.resolve(artifactDir, "dist");
  // Build into a fresh, uniquely-named staging dir (sibling of dist/ so the
  // publish renames stay on one filesystem). Force-clean first in case an
  // interrupted earlier build left a same-named dir behind.
  const stagingDir = path.resolve(
    artifactDir,
    `dist.build.${Date.now()}-${process.pid}`,
  );
  await rm(stagingDir, { recursive: true, force: true });

  try {
    await esbuild({
      entryPoints: [path.resolve(artifactDir, "src/index.ts")],
      platform: "node",
      bundle: true,
      format: "esm",
      outdir: stagingDir,
      outExtension: { ".js": ".mjs" },
      logLevel: "info",
      // Some packages may not be bundleable, so we externalize them, we can add more here as needed.
      // Some of the packages below may not be imported or installed, but we're adding them in case they are in the future.
      // Examples of unbundleable packages:
      // - uses native modules and loads them dynamically (e.g. sharp)
      // - use path traversal to read files (e.g. @google-cloud/secret-manager loads sibling .proto files)
      external: [
      "*.node",
      "sharp",
      "better-sqlite3",
      "sqlite3",
      "canvas",
      "bcrypt",
      "argon2",
      "fsevents",
      "re2",
      "farmhash",
      "xxhash-addon",
      "bufferutil",
      "utf-8-validate",
      "ssh2",
      "cpu-features",
      "dtrace-provider",
      "isolated-vm",
      "lightningcss",
      "pg-native",
      "oracledb",
      "mongodb-client-encryption",
      "nodemailer",
      "handlebars",
      "knex",
      "typeorm",
      "protobufjs",
      "onnxruntime-node",
      "@tensorflow/*",
      "@prisma/client",
      "@mikro-orm/*",
      "@grpc/*",
      "@swc/*",
      "@aws-sdk/*",
      "@azure/*",
      "@opentelemetry/*",
      "@google-cloud/*",
      "@google/*",
      "googleapis",
      "firebase-admin",
      "@parcel/watcher",
      "@sentry/profiling-node",
      "@tree-sitter/*",
      "aws-sdk",
      "classic-level",
      "dd-trace",
      "ffi-napi",
      "grpc",
      "hiredis",
      "kerberos",
      "leveldown",
      "miniflare",
      "mysql2",
      "newrelic",
      "odbc",
      "piscina",
      "realm",
      "ref-napi",
      "rocksdb",
      "sass-embedded",
      "sequelize",
      "serialport",
      "snappy",
      "tinypool",
      "usb",
      "workerd",
      "wrangler",
      "zeromq",
      "zeromq-prebuilt",
      "playwright",
      "puppeteer",
      "puppeteer-core",
      "electron",
    ],
    sourcemap: "linked",
    plugins: [
      // pino relies on workers to handle logging, instead of externalizing it we use a plugin to handle it
      esbuildPluginPino({ transports: ["pino-pretty"] })
    ],
    // Make sure packages that are cjs only (e.g. express) but are bundled continue to work in our esm output file
    banner: {
      js: `import { createRequire as __bannerCrReq } from 'node:module';
import __bannerPath from 'node:path';
import __bannerUrl from 'node:url';

globalThis.require = __bannerCrReq(import.meta.url);
globalThis.__filename = __bannerUrl.fileURLToPath(import.meta.url);
globalThis.__dirname = __bannerPath.dirname(globalThis.__filename);
    `,
      },
    });

    // esbuild succeeded — only now do we touch dist/. A FAILED build throws
    // above (before this line), leaving the previously-served dist/ completely
    // untouched so the running api-server keeps serving the last-good bundle.
    await publishAtomically(stagingDir, distDir);
  } finally {
    // Always remove the staging dir, whether the build succeeded, failed, or
    // the publish renamed every file out of it.
    await rm(stagingDir, { recursive: true, force: true });
  }
}

buildAll().catch((err) => {
  console.error(err);
  process.exit(1);
});
