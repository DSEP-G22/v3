import { defineConfig, devices } from "@playwright/test";

// Runs against the composed stack (scripts/up), never a dev server: the edge is the product.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.LANKA_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
