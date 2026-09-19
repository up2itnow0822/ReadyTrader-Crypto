import type { ApiError } from "./api";
import { formatQuantity } from "./format";
import type { ApproveTradeSuccess } from "./types";

/** Maps an approve/reject failure's HTTP status to the plain-language message a trader needs. */
export function describeApprovalError(error: ApiError): string {
  const base = (() => {
    switch (error.status) {
      case 403:
        return "Not allowed";
      case 404:
        return "This proposal no longer exists";
      case 409:
        return "This proposal was already handled";
      case 410:
        return "This proposal expired";
      case 422:
        return "The engine refused this order";
      case 0:
        return "Network error";
      default:
        return "Request failed";
    }
  })();

  const detail = error.message && error.message !== base ? error.message : null;
  const suggestion = error.suggestion ? ` ${error.suggestion}` : "";
  return detail ? `${base}: ${detail}.${suggestion}`.trim() : `${base}.${suggestion}`.trim();
}

export function describeApprovalSuccess(data: ApproveTradeSuccess["data"] | undefined): string {
  const fill = data?.fill;
  if (fill && typeof fill.amount === "number" && typeof fill.price === "number") {
    const total = fill.total_value !== undefined ? ` (total ${formatQuantity(fill.total_value)} ${fill.quote ?? ""})` : "";
    return `Executed: ${formatQuantity(fill.amount)} ${fill.symbol ?? ""} @ ${formatQuantity(fill.price)}${total}`
      .replace(/\s+/g, " ")
      .trim();
  }
  return "Executed successfully.";
}

export function describeRejectSuccess(): string {
  return "Rejected. The proposal was cancelled.";
}
