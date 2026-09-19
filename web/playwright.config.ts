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
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.spec/ },
    // A phone-sized Chromium (Pixel 7 touch, narrowed to a 375 wide phone), so no WebKit download is needed.
    { name: "mobile", use: { ...devices["Pixel 7"], viewport: { width: 375, height: 812 } }, testMatch: /mobile\.spec/ },
  ],
});
