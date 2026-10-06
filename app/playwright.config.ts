import { defineConfig } from "@playwright/test";

// GUI smoke tests (README M3): the built UI (dist/) in Chromium, driven through the same Tauri commands the
// desktop app uses, answered by the real Python worker (see e2e/fixtures.ts). Run `npm run build` first.
export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts",
  timeout: 180_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    // Use a preinstalled Chromium when one is given (e.g. offline machines); otherwise Playwright's own.
    launchOptions: process.env.PB_CHROMIUM ? { executablePath: process.env.PB_CHROMIUM } : {},
  },
});
