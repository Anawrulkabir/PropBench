import { defineConfig } from "vitest/config";

// Unit tests cover plain TypeScript modules only, so no Svelte plugin is needed here.
export default defineConfig({
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
