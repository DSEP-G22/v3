import { expect, test } from "@playwright/test";

import { persona, signIn, STAFF } from "./helpers";

test("the console queue opens a case with its draft and its evidence", async ({ page }) => {
  await signIn(page, STAFF.agent);
  await page.goto("/console");
  await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();
  const row = page.getByRole("link", { name: /LL-\d+/ }).first();
  if (await row.count()) {
    await row.click();
    await expect(page).toHaveURL(/\/console\/cases\//);
    await expect(page.getByText(/Draft|Reply/i).first()).toBeVisible({ timeout: 30_000 });
  }
});

test("the models map draws every stage and opens one", async ({ page }) => {
  await signIn(page, STAFF.admin);
  await page.goto("/admin/models");
  await expect(page.getByRole("heading", { name: "Models" })).toBeVisible();
  const stages = page.getByRole("button", { name: /Translate out|Draft|Diagnose|Triage|Intake/ });
  await expect(stages.first()).toBeVisible();
  await page.getByRole("button", { name: /Diagnose/ }).first().click();
  await expect(page.getByRole("button", { name: /Verify it is active/ })).toBeVisible();
});

test("a customer is kept out of the staff areas", async ({ page }) => {
  await signIn(page, persona("amara"));
  for (const path of ["/console", "/admin/models", "/sim"]) {
    await page.goto(path);
    await expect(page).not.toHaveURL(new RegExp(`${path}$`));
  }
});

test("the session survives a reload and shows on the landing page", async ({ page }) => {
  await signIn(page, persona("amara"));
  await page.goto("/");
  await expect(page.getByText(/Signed in as/i)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/Signed in as/i)).toBeVisible();
});

test("signing out ends the session", async ({ page }) => {
  await signIn(page, persona("amara"));
  await page.goto("/app");
  // The header renders after the session resolves; clicking before that clicks nothing.
  const out = page.getByRole("button", { name: /Sign out/i }).first();
  await out.waitFor({ state: "visible", timeout: 20_000 });
  await out.click();
  // Signing out lands on the website; only then is the cookie gone.
  await expect(page).toHaveURL(/localhost:\d+\/$/, { timeout: 20_000 });
  await page.goto("/app");
  await expect(page).toHaveURL(/sign-in/, { timeout: 20_000 });
});
