import { expect, type Page } from "@playwright/test";

export const STAFF_PASSWORD = process.env.SEED_STAFF_PASSWORD ?? "Console#2026";
export const CUSTOMER_PASSWORD = process.env.SEED_CUSTOMER_PASSWORD ?? "Lanka#2026";

export const STAFF = {
  agent: "agent1@lankalink.example.lk",
  admin: "admin1@lankalink.example.lk",
  operator: "operator1@lankalink.example.lk",
};
export const persona = (name: string) => `${name}@customers.lankalink.example.lk`;

export async function signIn(page: Page, email: string) {
  // Sign-in is rate limited per address. A parallel test run trips it, so back off and retry.
  for (let attempt = 0; attempt < 4; attempt++) {
    await page.goto("/sign-in");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(email.includes("@customers.") ? CUSTOMER_PASSWORD : STAFF_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    try {
      await expect(page).not.toHaveURL(/sign-in/, { timeout: 10_000 });
      return;
    } catch {
      await page.waitForTimeout(3_000 * (attempt + 1));
    }
  }
  await expect(page).not.toHaveURL(/sign-in/);
}

// Words that belong to the back office. A customer screen showing any of them has leaked.
export const BACK_OFFICE = [
  /\bSUB-\d{6}\b/, /\bOLT\b/, /\bCIR-/, /\bgrounding\b/i, /\bbundle\b/i, /\bLLM\b/, /\btriage\b/i,
  /\bconfidence\b/i, /\bpriority level\b/i, /\bnull\b/, /\bundefined\b/, /\bNaN\b/, /\u2014/,
];
