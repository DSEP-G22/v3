import { expect, test } from "@playwright/test";

import { BACK_OFFICE, persona, signIn } from "./helpers";

const PAGES = ["/app", "/app/billing", "/app/usage", "/app/plan", "/app/settings", "/app/support"];

test("immersion: no customer page shows back office words", async ({ page }) => {
  await signIn(page, persona("amara"));
  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const text = await page.locator("body").innerText();
    for (const word of BACK_OFFICE) expect(text, `${path} shows ${word}`).not.toMatch(word);
  }
});

test("a chat message is acknowledged and shows progress", async ({ page }) => {
  await signIn(page, persona("nadia"));
  await page.goto("/app/support");
  await page.getByRole("textbox").fill("My internet drops every evening around eight");
  await page.keyboard.press("Enter");
  await expect(page.getByText("My internet drops every evening around eight")).toBeVisible();
  // Stage chips arrive over SSE within the ack budget; the reply itself may be held for an agent.
  await expect(page.getByTestId("stage-chip").first()).toBeVisible({ timeout: 15_000 });
});
