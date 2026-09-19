import { expect, loginAsAdmin, test } from "./fixtures";

const ROUTES = ["/", "/history", "/status", "/disclaimer"];

test.describe("Navigation and manifest", () => {
  test("every route returns 200 when logged in", async ({ page, request }) => {
    await loginAsAdmin(page);
    const token = await page.evaluate(() => sessionStorage.getItem("readytrader.auth.token"));

    for (const route of ROUTES) {
      const response = await page.goto(route);
      expect(response?.status(), `GET ${route}`).toBe(200);
    }

    // Static assets the manifest/app reference.
    for (const path of ["/manifest.json", "/sw.js", "/icon.svg", "/icons/icon-192.png", "/icons/icon-512.png"]) {
      const response = await request.get(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      expect(response.status(), `GET ${path}`).toBe(200);
    }
  });

  test("manifest.json only references real routes and existing icons", async ({ request }) => {
    const response = await request.get("/manifest.json");
    expect(response.status()).toBe(200);
    const manifest = await response.json();

    for (const icon of manifest.icons ?? []) {
      const iconResponse = await request.get(icon.src);
      expect(iconResponse.status(), `icon ${icon.src}`).toBe(200);
    }
    for (const shortcut of manifest.shortcuts ?? []) {
      expect(ROUTES).toContain(shortcut.url);
    }
  });

  test("the Docs link points at the GitHub README (not fetched -- external site)", async ({ page }) => {
    await loginAsAdmin(page);
    const docsLink = page.getByRole("link", { name: /docs/i });
    await expect(docsLink).toHaveAttribute("href", /github\.com\/.+#readme/);
    await expect(docsLink).toHaveAttribute("target", "_blank");
  });

  test("nav links removed for pages that do not exist", async ({ page }) => {
    await loginAsAdmin(page);
    for (const stale of ["/strategy", "/settings", "/security", "/portfolio", "/approvals"]) {
      await expect(page.locator(`a[href="${stale}"]`)).toHaveCount(0);
    }
  });
});

test.describe("Mobile viewport (390x844)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("hamburger opens and closes the sidebar; every route has no horizontal scroll", async ({ page }) => {
    await loginAsAdmin(page);

    const hamburger = page.getByRole("button", { name: "Open navigation menu" });
    await expect(hamburger).toBeVisible();
    await hamburger.click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();

    await page.getByRole("link", { name: "History" }).click();
    await expect(page).toHaveURL(/\/history$/);
    // Closes on navigation.
    await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();

    for (const route of ROUTES) {
      await page.goto(route);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `horizontal overflow on ${route}`).toBeLessThanOrEqual(0);
    }
  });

  test("Esc closes the sidebar", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("button", { name: "Open navigation menu" }).click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
  });
});
