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
// Grafana's assets are a few megabytes and this link is slow; the defaults are far too tight.
page.setDefaultTimeout(180_000);
page.setDefaultNavigationTimeout(180_000);
await page.goto(`${url}/login`, { waitUntil: "domcontentloaded" });
await page.getByTestId("data-testid Username input field").fill(process.env.GRAFANA_USER ?? "admin");
await page.getByTestId("data-testid Password input field").fill(process.env.GRAFANA_PASSWORD ?? "");
await page.getByTestId("data-testid Login button").click();
await page.waitForURL((u) => !u.pathname.endsWith("/login"), { timeout: 120_000 });

const dash = `${url}/d/lanka-link-vps/lanka-link-vps-and-services?orgId=1&from=${encodeURIComponent(from)}&to=now&refresh=`;
// Kiosk mode drops Grafana's chrome; the tall viewport lets every row lay out and load.
// Wait for the panels to hold data, not for a fixed time: this link is slow. While any query
// is in flight Grafana's refresh button reads "Cancel".
async function ready(minPanels) {
  await page.waitForFunction(
    (n) => document.querySelectorAll('[data-testid="data-testid panel content"]').length >= n,
    minPanels, { timeout: 180_000 },
  );
  await page.waitForFunction(() => !document.body.innerText.includes("Loading ..."), null, { timeout: 180_000 });
  // Then simply give the queries time: over a slow link the whole dashboard takes a minute or two.
  await page.waitForTimeout(Number(process.env.GRAFANA_SETTLE_MS ?? 90_000));
}

// One navigation, two sizes: reloading this dashboard over the link costs minutes.
await page.setViewportSize({ width: 1600, height: 3400 });
await page.goto(`${dash}&kiosk`, { waitUntil: "domcontentloaded" });
await ready(20);
await page.screenshot({ path: join(dst, "grafana-dashboard.png"), fullPage: true });
await page.setViewportSize({ width: 1600, height: 1000 });
await page.waitForTimeout(3_000);
await page.screenshot({ path: join(dst, "grafana-overview.png") });
await browser.close();
