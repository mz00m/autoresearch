import { expect, test } from "@playwright/test";

test.describe("dashboard smoke", () => {
  test("Today page renders the core sections", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("Daily research note")).toBeVisible();
    await expect(page.getByText("Daily operations")).toBeVisible();
    await expect(page.getByText("Switch active strategy")).toBeVisible();
    // Action buttons exist
    await expect(page.getByRole("button", { name: /run morning/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /run closeout/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /refresh cards/i })).toBeVisible();
  });

  test("nav links work", async ({ page }) => {
    await page.goto("/");
    for (const [label, expectedMarker] of [
      ["Recommendations", /if you traded today/i],
      ["Sell guide", /when to sell/i],
      ["History", /history|track record/i],
      ["Strategies", /strategy library|bench/i],
      ["Compare", /counterfactual|comparison/i],
    ] as const) {
      await page.getByRole("link", { name: label }).first().click();
      // The eyebrow above the H1 is the unique page marker; H1s are dates
      // for several pages so we can't use them. The page-level eyebrow lives
      // inside <main>, distinguishing it from the nav's "paper research".
      await expect(page.locator("main .eyebrow").first()).toHaveText(expectedMarker);
    }
  });

  test("strategy picker has a params input", async ({ page }) => {
    await page.goto("/");
    const params = page.getByPlaceholder(/lookback_days/);
    await expect(params).toBeVisible();
    // Default value matches the active strategy's expected schema
    const value = await params.inputValue();
    expect(value).toMatch(/^\{.*\}$/);   // JSON object
  });

  test("refresh-cards triggers and finishes", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/");
    const btn = page.getByRole("button", { name: /refresh cards/i });
    await btn.click();
    // Should show "Running…" briefly then come back
    await expect(btn).toBeEnabled({ timeout: 90_000 });
    // Output panel should appear with exit code line
    await expect(page.getByText(/exit 0|exit -1|exit \d+/).first()).toBeVisible();
  });
});
