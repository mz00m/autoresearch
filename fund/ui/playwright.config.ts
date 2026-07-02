import { defineConfig, devices } from "@playwright/test";

/**
 * Smoke tests against a locally-running dev server. Assumes you've already
 * started `npm run dev` (port 3030). Don't auto-start it from here because
 * the dev server depends on Python state files we don't want to clobber.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3030",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
