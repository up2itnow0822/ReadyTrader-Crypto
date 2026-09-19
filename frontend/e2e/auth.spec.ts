import { TEST_ADMIN_USERNAME } from "./constants";
import { expect, loginAsAdmin, test } from "./fixtures";

test.describe("Authentication", () => {
  test("wrong password shows an error and does not log in", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Username").fill(TEST_ADMIN_USERNAME);
    await page.getByLabel("Password").fill("definitely-wrong");
    await page.getByRole("button", { name: "Sign in" }).click();

    // Not a bare getByRole("alert"): Next's App Router always renders its own
    // role="alert" route announcer (usually empty), so that query matches 2 elements.
    await expect(page.getByTestId("login-error")).toContainText(/invalid credentials/i);
    await expect(page.getByLabel("Username")).toBeVisible();
  });

  test("right password logs in and shows the dashboard", async ({ page }) => {
    await loginAsAdmin(page);
    await expect(page.getByRole("heading", { name: "Pending approvals" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
  });

  test("logout returns to the login screen", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page.getByLabel("Username")).toBeVisible();
  });

  test("visiting /history while logged out shows the login screen, not the page", async ({ page }) => {
    await page.goto("/history");
    await expect(page.getByLabel("Username")).toBeVisible();
    await expect(page.getByRole("table")).not.toBeVisible();
  });
});
