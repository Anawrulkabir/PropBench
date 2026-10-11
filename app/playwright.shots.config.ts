import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// README screenshots (e2e/readme.shots.ts); not part of the test run.
export default defineConfig({ ...base, testMatch: "**/*.shots.ts" });
