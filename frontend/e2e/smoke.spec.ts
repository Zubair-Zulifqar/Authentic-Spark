import { expect, test } from "@playwright/test";

test("dev sign-in shows agency overview and client workspace", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email").fill("admin@spark.example");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Agency overview" })).toBeVisible();
  await page.getByRole("link", { name: "Clients" }).click();
  await page.getByText("Riverbend Food Bank").click();
  await expect(page.getByRole("tab", { name: "Email" })).toBeVisible();
});
