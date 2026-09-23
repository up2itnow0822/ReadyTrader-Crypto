import { formatQuantity } from "./format";
import type { ApprovalSummary, PendingApproval } from "./types";

/** Builds the one-sentence, plain-language description of what a proposal will do. */
export function describeApproval(approval: Pick<PendingApproval, "kind" | "summary">): string {
  const s: ApprovalSummary = approval.summary ?? {};
  switch (approval.kind) {
    case "place_cex_order": {
      const side = s.side === "sell" ? "Sell" : "Buy";
      const amount = formatQuantity(s.amount);
      const symbol = s.symbol ?? "an unknown symbol";
      const priceText =
        s.price === null || s.price === undefined ? "at market price" : `at ${formatQuantity(s.price)}`;
      const orderType = s.order_type ?? "market";
      const exchange = s.exchange ?? "an unknown exchange";
      const marketType = s.market_type ?? "spot";
      return `${side} ${amount} ${symbol} ${priceText} (${orderType}) on ${exchange} ${marketType}`;
    }
    case "swap_tokens": {
      const amount = formatQuantity(s.amount);
      const from = s.from_token ?? "an unknown token";
      const to = s.to_token ?? "an unknown token";
      const chain = s.chain ?? "an unknown chain";
      return `Swap ${amount} ${from} for ${to} on ${chain}`;
    }
    case "transfer_eth": {
      const amount = formatQuantity(s.amount);
      const to = s.to_address ?? "an unknown address";
      const chain = s.chain ?? "an unknown chain";
      return `Transfer ${amount} ETH to ${to} on ${chain}`;
    }
    default:
      return `Execute a ${approval.kind} request`;
  }
}

const FIELD_LABELS: Record<string, string> = {
  symbol: "Symbol",
  side: "Side",
  amount: "Amount",
  order_type: "Order type",
  price: "Price",
  exchange: "Exchange",
  market_type: "Market type",
  from_token: "From token",
  to_token: "To token",
  chain: "Chain",
  rationale: "Rationale",
  to_address: "To address",
};

export interface SummaryField {
  key: string;
  label: string;
  value: string;
}

/** The raw fields for the small definition list, in a stable, readable order. */
export function summaryFields(summary: ApprovalSummary): SummaryField[] {
  return Object.entries(summary)
    .filter(([key]) => key !== "rationale") // rationale gets its own labeled block, rendered as plain text
    .map(([key, value]) => ({
      key,
      label: FIELD_LABELS[key] ?? key,
      value: value === null || value === undefined ? "—" : String(value),
    }));
}
