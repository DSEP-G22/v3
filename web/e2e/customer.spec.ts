import { expect, test } from "@playwright/test";

import { BACK_OFFICE, persona, signIn } from "./helpers";

const PAGES = ["/app", "/app/billing", "/app/usage", "/app/plan", "/app/settings", "/app/tickets"];

test("immersion: no customer page shows back office words", async ({ page }) => {
  await signIn(page, persona("amara"));
  for (const path of PAGES) {
    await page.goto(path);
    // Never networkidle: the live updates stream stays open for as long as the page is open.
    await page.waitForLoadState("domcontentloaded");
    await expect(page.locator("main")).toBeVisible();
    await page.waitForTimeout(1_500);
    const text = await page.locator("body").innerText();
    for (const word of BACK_OFFICE) expect(text, `${path} shows ${word}`).not.toMatch(word);
  }
});

test("opening a ticket is acknowledged and shows progress", async ({ page }) => {
  await signIn(page, persona("nadia"));
  await page.goto("/app/tickets/new");
  const text = `My internet drops every evening around eight (${Date.now()})`;
  await page.getByPlaceholder("Tell us what is happening").fill(text);
  await page.getByRole("button", { name: "Open ticket" }).click();
  // The acknowledgement is the ticket page itself: the pipeline runs behind it.
  await expect(page).toHaveURL(/\/app\/tickets\/\w/, { timeout: 15_000 });
  await expect(page.getByText(text)).toBeVisible();
  await expect(page.getByText("Waiting on us")).toBeVisible();
});
