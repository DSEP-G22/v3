// Screenshots of the provisioned Grafana dashboard, for the test report.
//   GRAFANA_URL=https://host/grafana GRAFANA_PASSWORD=... node scripts/grafana-shot.mjs <png dir> [from]
// The password comes from the environment, never the command line. `from` is a Grafana time
// (default now-1h), so a load test can be pictured from its start.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const [dst, from = "now-1h"] = process.argv.slice(2);
const url = process.env.GRAFANA_URL ?? "http://localhost:8080/grafana";
mkdirSync(dst, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1.25 });
await page.goto(`${url}/login`);
await page.getByTestId("data-testid Username input field").fill(process.env.GRAFANA_USER ?? "admin");
await page.getByTestId("data-testid Password input field").fill(process.env.GRAFANA_PASSWORD ?? "");
await page.getByTestId("data-testid Login button").click();
await page.waitForURL((u) => !u.pathname.endsWith("/login"), { timeout: 20_000 });

const dash = `${url}/d/lanka-link-vps/lanka-link-vps-and-services?orgId=1&from=${encodeURIComponent(from)}&to=now&refresh=`;
// Kiosk mode drops Grafana's chrome; the tall viewport lets every row lay out and load.
await page.setViewportSize({ width: 1600, height: 3200 });
await page.goto(`${dash}&kiosk`);
await page.waitForTimeout(12_000); // every panel's query
await page.screenshot({ path: join(dst, "grafana-dashboard.png"), fullPage: true });
await page.setViewportSize({ width: 1600, height: 1000 });
await page.goto(`${dash}&kiosk`);
await page.waitForTimeout(10_000);
await page.screenshot({ path: join(dst, "grafana-overview.png") });
await browser.close();
