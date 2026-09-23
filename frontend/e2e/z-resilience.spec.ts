// Deliberately NOT using ./fixtures here: killing the API on purpose makes the browser
// log a network-level console error for the failed request, which is expected browser
// behavior for this scenario, not an app defect -- so this file is exempt from the
// zero-console-errors fixture the other specs use.
import { expect, test } from "@playwright/test";

import { API_PORT, API_URL } from "./constants";
import { killListenerOnPort, spawnApiHarness, waitForHealth } from "./apiControl";
import { loginAsAdmin } from "./fixtures";

test.describe.serial("API resilience", () => {
  test("unreachable API shows the banner + Mode unknown, and recovers once it restarts", async ({ page }) => {
    await loginAsAdmin(page);
    await expect(page.getByTestId("health-pill")).toHaveText("PAPER");

    killListenerOnPort(API_PORT);

    // Not a bare getByRole("alert"): with the API down, the approvals panel's own
    // fetch-error alert and Next's route-announcer alert are both on the page too, so
    // that query would match more than one element.
    const banner = page.getByTestId("health-banner");
    await expect(banner).toContainText(/can.?t reach the api/i, { timeout: 15_000 });
    await expect(page.getByTestId("health-pill")).toHaveText("Mode unknown", { timeout: 15_000 });
    const pillClass = await page.getByTestId("health-pill").getAttribute("class");
    expect(pillClass).not.toContain("health-pill--paper");
    expect(pillClass).not.toContain("health-pill--live");

    const replacement = spawnApiHarness(API_PORT, true);
    try {
      await waitForHealth(API_URL);
      await page.getByRole("button", { name: "Retry" }).click();

      await expect(page.getByTestId("health-pill")).toHaveText("PAPER", { timeout: 15_000 });
      await expect(banner).not.toBeVisible();
    } finally {
      replacement.kill("SIGKILL");
    }
  });
});
