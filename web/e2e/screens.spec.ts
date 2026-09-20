import { expect, test, type Page } from "@playwright/test";

import { persona, signIn, STAFF } from "./helpers";

// Desktop screenshots of every surface, for the written test report. These only capture: the
// assertions that guard behaviour live in the other specs, and the phone widths in mobile.spec.
const SHOTS = `${process.env.SHOTS_DIR ?? "test-results/screens"}/desktop`;

async function shot(page: Page, path: string, name: string, full = false) {
  await page.goto(path);
  await page.locator("main, h1").first().waitFor({ timeout: 20_000 });
  await page.waitForTimeout(2_000); // data and entrance animations settle
  await expect(page.locator("body")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: full });
}

test("public pages", async ({ page }) => {
  await shot(page, "/", "landing");
  await shot(page, "/plans", "plans");
  await shot(page, "/docs", "docs");
  await shot(page, "/sign-in", "sign-in");
});

test("customer app", async ({ page }) => {
  await signIn(page, persona("amara"));
  for (const [path, name] of [["/app", "customer-home"], ["/app/tickets", "customer-tickets"],
    ["/app/tickets/new", "customer-new-ticket"], ["/app/billing", "customer-billing"],
    ["/app/usage", "customer-usage"], ["/app/plan", "customer-plan"]]) {
    await shot(page, path, name);
  }
});

test("agent console", async ({ page }) => {
  await signIn(page, STAFF.agent);
  await shot(page, "/console", "console-inbox");
  // The table, not the phone card list: that list is in the DOM at every width, only hidden.
  const row = page.locator("tbody tr").first();
  await row.waitFor({ timeout: 15_000 }).catch(() => undefined);
  if (await row.count()) {
    await row.click();
    await page.waitForURL(/\/console\/cases\//, { timeout: 20_000 }).catch(() => undefined);
    await shot(page, new URL(page.url()).pathname, "console-case", true);
  }
});

test("admin and simulation", async ({ page }) => {
  await signIn(page, STAFF.admin);
  for (const [path, name] of [["/admin", "admin-overview"], ["/admin/models", "admin-models"],
    ["/admin/autoreply", "admin-autoreply"], ["/admin/grounding", "admin-grounding"], ["/admin/users", "admin-users"]]) {
    await shot(page, path, name);
  }
  await signIn(page, STAFF.operator);
  for (const [path, name] of [["/sim", "sim-network"], ["/sim/scenarios", "sim-incidents"], ["/sim/lab", "sim-lab"]]) {
    await shot(page, path, name);
  }
});
