/** Shapes returned by api_server.py. Keep in sync with the backend contract in AGENTS.md. */

export type HealthMode = "paper" | "live";

export interface HealthResponse {
  status: string;
  mode: HealthMode;
  timestamp: string;
  version: string;
  trading_halted: boolean;
  live_enabled: boolean;
  auth_required: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface CurrentUser {
  user_id: string;
  role: string;
}

export interface PlaceCexOrderSummary {
  symbol?: string;
  side?: string;
  amount?: number;
  order_type?: string;
  price?: number | null;
  exchange?: string;
  market_type?: string;
}

export interface SwapTokensSummary {
  from_token?: string;
  to_token?: string;
  amount?: number;
  chain?: string;
  rationale?: string;
}

export interface TransferEthSummary {
  to_address?: string;
  amount?: number;
  chain?: string;
}

export type ApprovalSummary = PlaceCexOrderSummary & SwapTokensSummary & TransferEthSummary;

export interface PendingApproval {
  request_id: string;
  kind: "place_cex_order" | "swap_tokens" | "transfer_eth" | string;
  created_at: number;
  expires_at: number;
  summary: ApprovalSummary;
}

export interface PendingApprovalsResponse {
  pending: PendingApproval[];
}

export interface TradeFill {
  side?: string;
  symbol?: string;
  amount?: number;
  price?: number;
  total_value?: number;
  quote?: string;
}

export interface ApproveTradeSuccess {
  ok: true;
  data: {
    venue?: string;
    mode?: string;
    result?: string;
    fill?: TradeFill;
  };
}

export interface RejectTradeResponse {
  ok: boolean;
}

export interface PortfolioMetrics {
  daily_pnl_pct: number;
  /** The current fall from the best result so far (what the Risk Guardian's drawdown rule reads). */
  drawdown_pct: number;
  /** The deepest fall on record. */
  max_drawdown_pct?: number;
}

export interface PaperPortfolioResponse {
  balances: Record<string, number>;
  metrics: PortfolioMetrics;
}

export interface TradeRecord {
  id: number;
  timestamp: string;
  side: string;
  symbol: string;
  amount: number;
  price: number;
  total_value: number;
  rationale: string;
}

export interface TradeHistoryResponse {
  trades: TradeRecord[];
  mode: string;
}
