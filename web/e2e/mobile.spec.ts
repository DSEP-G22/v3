import { expect, test, type Page } from "@playwright/test";

import { persona, signIn, STAFF } from "./helpers";

// Every screen at phone width: nothing may scroll sideways, and each page is kept as a
// screenshot for the test report (SHOTS_DIR, default test-results/screens/mobile).
const SHOTS = `${process.env.SHOTS_DIR ?? "test-results/screens"}/mobile`;

async function check(page: Page, path: string, name: string) {
  await page.goto(path);
  await page.locator("main, h1").first().waitFor({ timeout: 20_000 });
  await page.waitForTimeout(1_500); // data and entrance animations settle
  const over = await page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    // What sticks out past the right edge, outside any container that scrolls on its own.
    const inScroller = (el: Element) => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        const s = getComputedStyle(p);
        if (/(auto|scroll|hidden|clip)/.test(s.overflowX) && p !== document.body && p !== document.documentElement) return true;
      }
      return false;
    };
    const culprits = [...document.querySelectorAll("body *")]
      .filter((el) => el.getBoundingClientRect().right > w + 1 && !inScroller(el))
      .slice(0, 5)
      .map((el) => `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 80)}`);
    return { scroll: document.documentElement.scrollWidth, width: w, culprits };
  });
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
  expect.soft(over.scroll, `${path} scrolls sideways: ${over.culprits.join(" | ")}`).toBeLessThanOrEqual(over.width + 1);
}

test("public pages fit a phone", async ({ page }) => {
  for (const [path, name] of [["/", "landing"], ["/plans", "plans"], ["/docs", "docs"], ["/sign-in", "sign-in"], ["/sign-up", "sign-up"]]) {
    await check(page, path, name);
  }
});

test("customer pages fit a phone", async ({ page }) => {
  await signIn(page, persona("amara"));
  for (const [path, name] of [["/app", "customer-home"], ["/app/tickets", "customer-tickets"], ["/app/tickets/new", "customer-new-ticket"],
    ["/app/billing", "customer-billing"], ["/app/usage", "customer-usage"], ["/app/plan", "customer-plan"], ["/app/settings", "customer-settings"]]) {
    await check(page, path, name);
  }
  // One ticket, if the persona has any.
  await page.goto("/app/tickets");
  const first = page.locator('a[href^="/app/tickets/"]:not([href$="/new"])').first();
  await first.waitFor({ timeout: 15_000 }).catch(() => undefined); // the list loads after the page
  if (await first.count()) await check(page, (await first.getAttribute("href"))!, "customer-ticket");
});

test("console fits a phone", async ({ page }) => {
  await signIn(page, STAFF.agent);
  await check(page, "/console", "console-inbox");
  const card = page.locator("main ul li button").first();
  await card.waitFor({ timeout: 15_000 }).catch(() => undefined);
  if (await card.count()) {
    await card.click();
    await page.waitForURL(/\/console\/cases\//);
    await check(page, new URL(page.url()).pathname, "console-case");
  }
});

test("admin fits a phone", async ({ page }) => {
  await signIn(page, STAFF.admin);
  for (const [path, name] of [["/admin", "admin-overview"], ["/admin/autoreply", "admin-autoreply"], ["/admin/models", "admin-models"],
    ["/admin/grounding", "admin-grounding"], ["/admin/traces", "admin-traces"], ["/admin/users", "admin-users"]]) {
    await check(page, path, name);
  }
});

test("simulation fits a phone", async ({ page }) => {
  await signIn(page, STAFF.operator);
  for (const [path, name] of [["/sim", "sim-network"], ["/sim/scenarios", "sim-incidents"], ["/sim/customers", "sim-customers"],
    ["/sim/requests", "sim-requests"], ["/sim/lab", "sim-lab"], ["/sim/events", "sim-events"]]) {
    await check(page, path, name);
  }
});
