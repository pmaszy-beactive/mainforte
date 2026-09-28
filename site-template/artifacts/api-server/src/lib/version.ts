import fs from "fs";
import path from "path";
import { logger } from "./logger";

export interface AppVersion {
  version: string;
}

let cachedVersion: AppVersion | null = null;

export function getVersion(): AppVersion {
  if (cachedVersion) return cachedVersion;

  const possiblePaths = [
    path.resolve(process.cwd(), "version.ini"),
    path.resolve(__dirname, "../../../version.ini"),
    path.resolve(__dirname, "../../../../version.ini"),
  ];

  for (const versionPath of possiblePaths) {
    try {
      if (fs.existsSync(versionPath)) {
        const content = fs.readFileSync(versionPath, "utf-8");
        const match = content.match(/^version\s*=\s*(.+)$/m);
        const version = match ? match[1].trim() : "0.0.0";

        cachedVersion = { version };

        logger.info({ version: cachedVersion.version, path: versionPath }, "Loaded version");
        return cachedVersion;
      }
    } catch {
      // try next path
    }
  }

  cachedVersion = { version: "0.0.0" };
  logger.warn("version.ini not found, using default 0.0.0");
  return cachedVersion;
}
