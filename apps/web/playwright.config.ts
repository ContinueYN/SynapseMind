import { defineConfig } from "@playwright/test";

const channel =
  process.env.PLAYWRIGHT_CHANNEL ??
  (process.platform === "win32" ? "msedge" : undefined);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // One Next dev server compiles routes on demand: more concurrent first loads
  // than this starve it and every `page.goto` hits the 30s timeout. CI already
  // runs serially; locally, four is the useful ceiling (six flaked).
  workers: process.env.CI ? 1 : 4,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    ...(channel ? { channel } : {}),
  },
  webServer: [
    {
      command: "node e2e/mock-api.mjs",
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_BASE: "http://127.0.0.1:8100",
      },
    },
  ],
});
