import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Never reuse the developer backend or fill its persistent scan storage.
const dataDir =
  process.env.SPATIAL_E2E_DATA_DIR ||
  mkdtempSync(join(tmpdir(), "spatial-e2e-"));
process.env.SPATIAL_E2E_DATA_DIR = dataDir;
process.env.TEST_API_URL ||= "http://127.0.0.1:18114/api";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  globalTeardown: "./tests/teardown.ts",
  use: {
    baseURL: process.env.TEST_BASE_URL || "http://127.0.0.1:15174",
    viewport: { width: 1440, height: 1080 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...(process.env.PLAYWRIGHT_CHANNEL
      ? { channel: process.env.PLAYWRIGHT_CHANNEL }
      : {}),
  },
  webServer: [
    {
      command: `"${process.platform === "win32" ? "..\\backend\\.venv\\Scripts\\python.exe" : "../backend/.venv/bin/python"}" -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 18114`,
      url: "http://127.0.0.1:18114/api/health",
      env: { SPATIAL_DATA_DIR: dataDir },
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 15174",
      env: { API_PROXY_TARGET: "http://127.0.0.1:18114" },
      url: "http://127.0.0.1:15174",
      reuseExistingServer: false,
    },
  ],
});
