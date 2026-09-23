import type { Page } from "@playwright/test";

import { API_URL } from "./constants";

/** Seeds one more proposal straight into the harness's ExecutionStore via its test-only route. */
export async function seedProposal(
  page: Page,
  body: { kind: string; payload: Record<string, unknown>; ttl_seconds?: number }
): Promise<string> {
  const response = await page.request.post(`${API_URL}/__test/seed`, { data: body });
  if (!response.ok()) {
    throw new Error(`Failed to seed proposal: ${response.status()} ${await response.text()}`);
  }
  const json = (await response.json()) as { request_id: string };
  return json.request_id;
}
