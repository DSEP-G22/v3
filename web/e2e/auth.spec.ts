import { expect, test } from "@playwright/test";

import { signIn, STAFF } from "./helpers";

test("an agent lands in the console and cannot open admin or sim", async ({ page }) => {
  await signIn(page, STAFF.agent);
  await expect(page).toHaveURL(/\/console/);
  for (const path of ["/admin", "/sim"]) {
    await page.goto(path);
    await expect(page).not.toHaveURL(new RegExp(`${path}$`));
  }
});

test("an operator lands in the simulation panel", async ({ page }) => {
  await signIn(page, STAFF.operator);
  await expect(page).toHaveURL(/\/sim/);
  await expect(page.getByRole("heading", { name: "Network" })).toBeVisible();
});

test("a wrong password is refused in plain words", async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(STAFF.agent);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("That email and password do not match.")).toBeVisible();
});

test("sign up with email reaches onboarding", async ({ page }) => {
  await page.goto("/sign-up");
  await page.getByLabel("Full name").fill("Playwright Customer");
  await page.getByLabel("Email").fill(`pw-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("Correct#Horse9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding/);
});
