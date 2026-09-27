import type { CapacitorConfig } from "@capacitor/cli";

// webDir points at the same `dist` the API serves in prod (see README's Mobile section) --
// native builds must set VITE_API_URL to the public API origin before `npm run build`, since
// there's no same-origin API to proxy to inside a native shell.
const config: CapacitorConfig = {
  appId: "ai.beactive.mainforte",
  appName: "Mainforte",
  webDir: "dist",
};

export default config;
