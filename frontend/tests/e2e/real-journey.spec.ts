import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import process from "node:process";

test("gated real backend conversation and planning journey", async ({ page }, testInfo) => {
  test.skip(process.env.RUN_UI_E2E !== "1", "Set RUN_UI_E2E=1 for one explicit paid flow.");
  test.skip(testInfo.project.name !== "desktop-chromium", "The real paid flow runs once, not per viewport.");
  test.setTimeout(240_000);

  const userId = randomUUID();
  const threadId = randomUUID();
  await page.addInitScript(
    ({ userIdValue, threadIdValue }) => {
      localStorage.setItem("travel-planner:user-id", userIdValue);
      localStorage.setItem("travel-planner:thread-id", threadIdValue);
    },
    { userIdValue: userId, threadIdValue: threadId },
  );

  await page.goto("/");
  await expect(page.getByRole("button", { name: "Check backend connection" })).toContainText(
    "Connected",
  );
  const composer = page.getByLabel("Describe your trip");
  await composer.fill("I want to visit Tokyo from Cleveland starting October 12, 2027 for five days.");
  await page.getByLabel("Send message").click();
  await expect(page.locator(".message-assistant").last()).toBeVisible();
  await composer.fill("One traveler, 3000 USD, photography and quiet neighborhoods.");
  await page.getByLabel("Send message").click();

  const confirm = page.getByRole("button", { name: /Confirm & Build My Trip/ });
  await expect(confirm).toBeVisible({ timeout: 60_000 });
  await confirm.click();
  await expect(page.getByRole("heading", { name: /Cleveland.*Tokyo/ })).toBeVisible({
    timeout: 180_000,
  });
  await expect(page.getByText(/not live booking inventory/)).toBeVisible();
});
