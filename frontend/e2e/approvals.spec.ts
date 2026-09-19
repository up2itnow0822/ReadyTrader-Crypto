import { loginAsAdmin, expect, test } from "./fixtures";
import { seedProposal } from "./seed";

function cardFor(page: import("@playwright/test").Page, sentence: string) {
  return page.locator("li.approval-card", { hasText: sentence });
}

test.describe("Header / health", () => {
  test("shows PAPER and Trading halted", async ({ page }) => {
    await loginAsAdmin(page);
    const pill = page.getByTestId("health-pill");
    await expect(pill).toHaveText("PAPER");
    await expect(page.getByText("Trading halted")).toBeVisible();
  });
});

test.describe("Approvals queue", () => {
  test("shows the seeded BTC order as a plain-language sentence", async ({ page }) => {
    await loginAsAdmin(page);
    await seedProposal(page, {
      kind: "place_cex_order",
      payload: { symbol: "BTC/USDT", side: "buy", amount: 0.05, order_type: "limit", price: 61000, exchange: "binance", market_type: "spot" },
    });
    await page.reload();

    await expect(cardFor(page, "Buy 0.05 BTC/USDT at 61,000 (limit) on binance spot")).toBeVisible();
  });

  test("approve -> dialog -> execute -> success with fill numbers, card gone, shows in history", async ({ page }) => {
    await loginAsAdmin(page);
    const sentence = "Buy 0.02 BTC/USDT at 55,000 (limit) on binance spot";
    await seedProposal(page, {
      kind: "place_cex_order",
      payload: { symbol: "BTC/USDT", side: "buy", amount: 0.02, order_type: "limit", price: 55000, exchange: "binance", market_type: "spot" },
    });
    await page.reload();

    const card = cardFor(page, sentence);
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "Approve" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(sentence);
    await expect(dialog).toContainText("PAPER");
    await dialog.getByRole("button", { name: "Approve and execute" }).click();

    // Scoped to the outcome paragraph itself, not just "somewhere in the card": the
    // card's own sentence already contains "55,000", so a card-wide text search for it
    // would match both.
    const outcome = card.getByText(/Executed:/);
    await expect(outcome).toBeVisible();
    await expect(outcome).toContainText("1,100");

    // The card stays up for a grace period so the operator can read the outcome above,
    // then drops off once that elapses (see OUTCOME_GRACE_MS in useApprovals.ts).
    await expect(cardFor(page, sentence)).not.toBeVisible({ timeout: 10_000 });

    await page.goto("/history");
    await expect(page.locator("table")).toContainText("BTC/USDT");
    await expect(page.locator("table")).toContainText("0.02");
  });

  test("an order the engine refuses shows a 422 message, not a crash", async ({ page }) => {
    await loginAsAdmin(page);
    const sentence = "Buy 50 BTC/USDT at 60,000 (limit) on binance spot";
    await seedProposal(page, {
      kind: "place_cex_order",
      payload: { symbol: "BTC/USDT", side: "buy", amount: 50, order_type: "limit", price: 60000, exchange: "binance", market_type: "spot" },
    });
    await page.reload();

    const card = cardFor(page, sentence);
    await card.getByRole("button", { name: "Approve" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Approve and execute" }).click();

    await expect(card.getByText(/refused/i)).toBeVisible();
    await expect(card.getByText(/insufficient fund/i)).toBeVisible();
    // The app kept rendering normally -- the dashboard heading is still there.
    await expect(page.getByRole("heading", { name: "Pending approvals" })).toBeVisible();
  });

  test("reject works, and an XSS rationale renders as inert plain text", async ({ page }) => {
    let dialogFired = false;
    page.on("dialog", () => {
      dialogFired = true;
    });

    await loginAsAdmin(page);
    const rationale = "<img src=x onerror=alert(1)>";
    await seedProposal(page, {
      kind: "swap_tokens",
      payload: { from_token: "ETH", to_token: "USDC", amount: 2.5, chain: "ethereum", rationale },
    });
    await page.reload();

    const sentence = "Swap 2.5 ETH for USDC on ethereum";
    const card = cardFor(page, sentence);
    await expect(card).toBeVisible();

    // The rationale must render as plain text: visible verbatim, and no <img> is created.
    await expect(card.getByText(rationale, { exact: false })).toBeVisible();
    expect(await card.locator("img").count()).toBe(0);
    expect(dialogFired).toBe(false);

    await card.getByRole("button", { name: "Reject" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Reject" }).click();

    await expect(card.getByText(/rejected/i)).toBeVisible();
    await expect(cardFor(page, sentence)).not.toBeVisible({ timeout: 10_000 });
    expect(dialogFired).toBe(false);
  });

  test("a proposal expires on screen a few seconds after being seeded", async ({ page }) => {
    await loginAsAdmin(page);
    const sentence = "Buy 0.003 BTC/USDT at 50,000 (limit) on binance spot";
    await seedProposal(page, {
      kind: "place_cex_order",
      payload: { symbol: "BTC/USDT", side: "buy", amount: 0.003, order_type: "limit", price: 50000, exchange: "binance", market_type: "spot" },
      ttl_seconds: 3,
    });
    await page.reload();

    const card = cardFor(page, sentence);
    await expect(card).toBeVisible();

    // A 3s TTL against the app's 5s approvals poll guarantees the proposal has already
    // expired server-side well before the *next* poll fires, so its removal here is
    // deterministic. (The card's own "disabled once the countdown hits zero" behavior
    // is covered precisely, with fake timers, by ApprovalCard.test.tsx -- asserting it
    // again here would race the real poll interval against the real TTL for no benefit.)
    await expect(card).not.toBeVisible({ timeout: 10_000 });
  });

  test("a double click on the confirm button sends exactly one approve request", async ({ page }) => {
    await loginAsAdmin(page);
    const sentence = "Buy 0.04 BTC/USDT at 52,000 (limit) on binance spot";
    await seedProposal(page, {
      kind: "place_cex_order",
      payload: { symbol: "BTC/USDT", side: "buy", amount: 0.04, order_type: "limit", price: 52000, exchange: "binance", market_type: "spot" },
    });
    await page.reload();

    let approveRequestCount = 0;
    page.on("request", (request) => {
      if (request.url().includes("/api/approve-trade") && request.method() === "POST") {
        approveRequestCount += 1;
      }
    });

    const card = cardFor(page, sentence);
    await card.getByRole("button", { name: "Approve" }).click();
    const confirmButton = page.getByRole("dialog").getByRole("button", { name: "Approve and execute" });
    await confirmButton.dblclick();

    await expect(card.getByText(/Executed:|refused|not allowed/i)).toBeVisible();
    expect(approveRequestCount).toBe(1);
  });
});
