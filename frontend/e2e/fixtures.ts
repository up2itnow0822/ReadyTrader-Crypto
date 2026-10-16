import { test as base, expect, type Page } from "@playwright/test";

import { API_URL, TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME } from "./constants";

interface Fixtures {
  /** Auto-applied: fails the test if the page logged a console error, threw an
   *  uncaught exception, or triggered a CSP violation. */
  consoleWatcher: void;
}

// Chromium logs this to the console itself, for ANY fetch that comes back with a
// non-2xx status -- it is the browser's own network panel noting a fact, not something
// the app's code logged, and several journeys here (wrong password, an order the
// engine refuses) deliberately provoke a 4xx/5xx response. A real app-code
// `console.error(...)` call, an uncaught exception, or a CSP violation still fails the
// test; only this one browser-generated, expected-in-a-negative-test line is exempt.
const BENIGN_RESOURCE_LOAD_ERROR = /^Failed to load resource: the server responded with a status of \d{3} /;

// Each test owns a fresh Page. Reset once per journey, not once per login attempt,
// so brute-force/lockout checks within a test still exercise real product limits.
const preparedPages = new WeakSet<Page>();
async function prepareLoginBudget(page: Page): Promise<void> {
  if (preparedPages.has(page)) return;
  const response = await page.request.post(`${API_URL}/__test/reset-login-budget`);
  expect(response.ok(), "The test-only harness must reset the journey's login budget").toBe(true);
  preparedPages.add(page);
}

export const test = base.extend<Fixtures>({
  consoleWatcher: [
    async ({ page }, use) => {
      await prepareLoginBudget(page);
      const errors: string[] = [];

      page.on("console", (msg) => {
        if (msg.type() === "error" && !BENIGN_RESOURCE_LOAD_ERROR.test(msg.text())) {
          errors.push(`console.error: ${msg.text()}`);
        }
      });
      page.on("pageerror", (err) => {
        errors.push(`pageerror: ${err.message}`);
      });

      await page.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (event) => {
          const w = window as unknown as { __cspViolations?: string[] };
          w.__cspViolations ??= [];
          w.__cspViolations.push(`${event.violatedDirective} blocked ${event.blockedURI}`);
        });
      });

      await use();

      try {
        const violations = await page.evaluate(
          () => (window as unknown as { __cspViolations?: string[] }).__cspViolations ?? []
        );
        for (const v of violations) errors.push(`CSP violation: ${v}`);
      } catch {
        // page already closed/navigated away mid-test; nothing left to collect
      }

      expect(errors, `Console errors / CSP violations recorded during this test:\n${errors.join("\n")}`).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/** Logs in through the real UI form and waits for the dashboard to appear. */
export async function loginAsAdmin(page: Page): Promise<void> {
  // Also covers the resilience journey, which intentionally skips consoleWatcher.
  await prepareLoginBudget(page);
  await page.goto("/");
  await page.getByLabel("Username").fill(TEST_ADMIN_USERNAME);
  await page.getByLabel("Password").fill(TEST_ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Pending approvals" })).toBeVisible();
}
