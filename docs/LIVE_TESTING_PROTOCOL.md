# Live Trading Validation Protocol

This document defines the formal validation protocol for transitioning ReadyTrader-Crypto from paper trading to live trading. Follow this checklist before enabling live execution.

______________________________________________________________________

## Overview

The Live Trading Validation Protocol consists of 5 phases:

| Phase | Name                       | Duration  | Purpose                                    |
| :---- | :-------------------------- | :--------- | :------------------------------------------|
| 1     | Environment Validation     | 1-2 hours | Verify configuration and connectivity      |
| 2     | Paper Trading Verification | 1-7 days  | Validate strategy in simulated environment |
| 3     | Testnet Validation         | 1-3 days  | Test on-chain execution with test tokens   |
| 4     | Minimal Live Testing       | 1-3 days  | Small-value live trades                    |
| 5     | Production Deployment      | Ongoing   | Full live trading with monitoring          |

______________________________________________________________________

## Phase 1: Environment Validation

### 1.1 Configuration Checklist

```bash
# Run the environment validation script
python tools/setup_wizard.py --validate

# Expected output: All checks should pass
```

**Manual Verification:**

- [ ] `.env` file exists and is NOT committed to git
- [ ] `PAPER_MODE=true` is set initially
- [ ] `LIVE_TRADING_ENABLED=false` is set initially
- [ ] `TRADING_HALTED=true` is set initially
- [ ] All required API keys are configured
- [ ] Signer type is appropriate (`keystore` or `remote` for production)

### 1.2 Credential Verification

```bash
# Test CEX credentials (read-only)
curl -X POST http://localhost:8000/api/test-cex-auth \
  -H "Content-Type: application/json" \
  -d '{"exchange": "binance"}'

# Expected: { "ok": true, "permissions": ["read", "trade"] }
```

**Verify CEX API Key Permissions:**

- [ ] Read access (fetch balance, orders)
- [ ] Trade access (place orders)
- [ ] **NO** withdrawal access (critical security)
- [ ] IP whitelist configured (if supported)

**Verify Signer Configuration:**

```bash
# Test signer address
python -c "
from signing.factory import get_signer
signer = get_signer()
print(f'Signer address: {signer.get_address()}')
"
```

- [ ] Signer address matches expected wallet
- [ ] `ALLOW_SIGNER_ADDRESSES` is set to pin the address
- [ ] Signer policy limits are configured

### 1.3 Network Connectivity

```bash
# Test exchange connectivity
python -c "
from execution.cex_executor import CexExecutor
ex = CexExecutor('binance', auth=False)
print(ex.get_capabilities())
"

# Test RPC connectivity (for DEX)
python -c "
from execution.evm import get_web3
w3 = get_web3('ethereum')
print(f'Connected: {w3.is_connected()}, Block: {w3.eth.block_number}')
"
```

- [ ] CEX API endpoints reachable
- [ ] RPC endpoints responsive (if using DEX)
- [ ] WebSocket connections stable
- [ ] Latency acceptable (\<500ms for CEX, \<2s for RPC)

### 1.4 Security Configuration

```bash
# Run security audit
bandit -r . -c bandit.yaml
ruff check .
```

- [ ] No security vulnerabilities detected
- [ ] Secret scanning passes
- [ ] Policy engine allowlists configured:
  - [ ] `ALLOW_CHAINS` (if using DEX)
  - [ ] `ALLOW_TOKENS` (if using DEX)
  - [ ] `ALLOW_EXCHANGES` (if using CEX)
  - [ ] `ALLOW_SIGNER_ADDRESSES`
- [ ] Rate limits configured appropriately

______________________________________________________________________

## Phase 2: Paper Trading Verification

### 2.1 Paper Trading Setup

```bash
# Enable paper mode
export PAPER_MODE=true
export LIVE_TRADING_ENABLED=false

# Start the server
python app/main.py
```

### 2.2 Strategy Verification (Minimum 24 hours)

Run your trading strategy in paper mode and collect metrics:

```bash
# Run paper trading demo
python examples/paper_quick_demo.py
```

**Required Metrics:**

| Metric             | Target            | Your Result    |
| :------------------ | :------------------ | :--------------|
| Total Trades       | >20               | \_\_\_\_\_\_\_ |
| Win Rate           | Document baseline | \_\_\_\_\_\_\_ |
| Max Drawdown       | \<10%             | \_\_\_\_\_\_\_ |
| Sharpe Ratio       | Document baseline | \_\_\_\_\_\_\_ |
| Daily P&L Variance | Document baseline | \_\_\_\_\_\_\_ |

### 2.3 Risk Guardian Verification

Test that the Risk Guardian correctly blocks dangerous trades:

```python
import json

from app.tools.trading import validate_trade_risk
from intelligence import analyze_social_sentiment
from risk_manager import RiskGuardian

# Position size limit (should be blocked): 6% > 5% limit
check = json.loads(validate_trade_risk("buy", "BTC/USDT", 600, 10000))["data"]
assert not check["result"]["allowed"]

# Falling knife rule, with a hand-fed score
assert not RiskGuardian().validate_trade("buy", "BTC/USDT", 100, 10000, sentiment_score=-0.6)["allowed"]

# Falling knife data path: refresh with X/Reddit keys configured, then recompute
# the trade check. Status must be "ok"; otherwise the rule has no measurement.
refresh = analyze_social_sentiment("BTC")
check = json.loads(validate_trade_risk("buy", "BTC/USDT", 100, 10000))["data"]
assert check["sentiment"]["status"] == "ok", refresh
print(check["sentiment"])
```

- [ ] Position size limit enforced (>5% blocked)
- [ ] Daily loss limit enforced (>5% daily loss halts buys)
- [ ] Max drawdown limit enforced (>10% halts buys)
- [ ] Falling knife protection active (`sentiment.status` is `ok`; score < -0.5 blocks buys)

### 2.4 Error Handling Verification

```python
# Test error scenarios
from app.tools.execution import place_cex_order, swap_tokens

# Invalid symbol
result = place_cex_order("INVALID/PAIR", "buy", 1)
assert "error" in result.lower() or not json.loads(result)["ok"]

# Amount too large
result = place_cex_order("BTC/USDT", "buy", 1000000)
# Verify policy blocks or proper error
```

- [ ] Invalid inputs return clear error messages
- [ ] Policy violations are caught and reported
- [ ] No unexpected exceptions crash the server

### 2.5 Stress Test Verification

```bash
# Run synthetic stress tests
python examples/stress_test_demo.py
```

**Stress Test Checklist:**

- [ ] Strategy survives 200+ synthetic scenarios
- [ ] Black swan events don't cause >20% drawdown
- [ ] Recommendations reviewed and applied if appropriate

______________________________________________________________________

## Phase 3: Testnet Validation (DEX Only)

If using DEX execution, validate on testnet before mainnet.

### 3.1 Testnet Configuration

```bash
# Configure for testnet
export RPC_URL_SEPOLIA="https://sepolia.infura.io/v3/YOUR_KEY"
export ALLOW_CHAINS="sepolia"

# Use testnet tokens
# Obtain test ETH from faucet: https://sepoliafaucet.com/
```

### 3.2 Testnet Execution Tests

```python
# Test token swap on testnet
from app.tools.execution import swap_tokens

result = swap_tokens(
    from_token="ETH",
    to_token="USDC", 
    amount=0.01,
    chain="sepolia"
)
print(result)
```

**Testnet Checklist:**

- [ ] Swap transaction executes successfully
- [ ] Transaction hash returned
- [ ] Transaction confirmed on block explorer
- [ ] Gas estimation accurate
- [ ] Slippage within expected bounds

### 3.3 Approval Flow Testing

```bash
# Enable approval mode
export EXECUTION_APPROVAL_MODE=approve_each
```

- [ ] Trades create pending approvals
- [ ] Web UI displays pending approvals
- [ ] Approval flow completes successfully
- [ ] Rejection flow works correctly
- [ ] Expired approvals are cleaned up

______________________________________________________________________

## Phase 4: Minimal Live Testing

### 4.1 Graduated Value Limits

Start with minimal values and gradually increase:

| Stage | Max Trade Value | Duration | Success Criteria      |
| :---- | :---------------- | :--------| :----------------------|
| 4.1a  | $10             | 24 hours | 3+ successful trades  |
| 4.1b  | $50             | 24 hours | 5+ successful trades  |
| 4.1c  | $100            | 48 hours | 10+ successful trades |
| 4.1d  | $500            | 72 hours | 20+ successful trades |

### 4.2 Enable Live Trading (Stage 4.1a)

```bash
# CRITICAL: Start with minimal limits
export PAPER_MODE=false
export LIVE_TRADING_ENABLED=true
export TRADING_HALTED=false
export EXECUTION_APPROVAL_MODE=approve_each  # Keep manual approval
export MAX_TRADE_AMOUNT=10
export MAX_CEX_ORDER_AMOUNT=10
```

### 4.3 First Live Trade

Execute a single, minimal trade with full monitoring:

```python
# First live trade (with approval)
from app.tools.execution import place_cex_order

result = place_cex_order(
    symbol="BTC/USDT",
    side="buy",
    amount=0.0001,  # ~$10 at $100k BTC
    order_type="market",
    exchange="binance"
)
print(result)

# Approve in Web UI, then verify:
# 1. Order appears in exchange history
# 2. Balance updated correctly
# 3. Audit log entry created
```

**First Trade Checklist:**

- [ ] Order placed successfully
- [ ] Correct symbol and side
- [ ] Fill price within expected slippage
- [ ] Balance reflects the trade
- [ ] Audit log entry created
- [ ] No error logs

### 4.4 Monitoring Requirements

During minimal live testing, monitor continuously:

```bash
# Watch logs in real-time
tail -f data/audit.db  # (or use sqlite3 to query)

# Check metrics
curl http://localhost:8000/metrics
```

**Monitoring Checklist (Every Hour):**

- [ ] No unexpected errors in logs
- [ ] Trade count matches expectations
- [ ] P&L within acceptable bounds
- [ ] Risk metrics within limits
- [ ] WebSocket connections stable

### 4.5 Rollback Procedure

If any issues detected:

1. **Kill switch:** restart the MCP server (and the API server) with `TRADING_HALTED=true`.
   Settings are read at start-up, so an `export` in another shell does nothing to a running
   server. From then on every new order, swap and transfer is refused with `trading_halted`.
1. **Cancel resting orders:** from the MCP client, `cancel_all_cex_orders(exchange="binance")`
   (per market type, e.g. also `market_type="future"`), then `list_cex_open_orders(...)` to confirm
   nothing is left. Reads and cancels still work while halted. The exchange's own web/app UI is
   the fallback. There is no HTTP cancel endpoint.
1. **Revert to paper:** restart with `PAPER_MODE=true` and `LIVE_TRADING_ENABLED=false`.

______________________________________________________________________

## Phase 5: Production Deployment

### 5.1 Production Configuration

```bash
# Production settings
export PAPER_MODE=false
export LIVE_TRADING_ENABLED=true
export TRADING_HALTED=false
export EXECUTION_APPROVAL_MODE=auto  # Or keep approve_each for safety
export MAX_TRADE_AMOUNT=<your_limit>
export MAX_CEX_ORDER_AMOUNT=<your_limit>

# Enable observability
export OTEL_ENABLED=true
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

### 5.2 Production Monitoring Setup

**Required Dashboards:**

1. **Trade Execution Dashboard**

   - Trade count (success/failure)
   - Average latency
   - Slippage distribution

1. **Risk Dashboard**

   - Current drawdown
   - Daily P&L
   - Position exposure

1. **System Health Dashboard**

   - API latency
   - Error rate
   - WebSocket status

### 5.3 Alerting Configuration

Configure alerts for:

- [ ] Trade failure rate > 5%
- [ ] Latency > 2s
- [ ] Daily loss > 3%
- [ ] Drawdown > 7%
- [ ] WebSocket disconnection
- [ ] Rate limit warnings

### 5.4 Runbook Procedures

Document and test these procedures:

- [ ] Emergency shutdown procedure
- [ ] Manual order cancellation procedure
- [ ] Rollback to paper mode procedure
- [ ] Credential rotation procedure
- [ ] Incident response procedure

______________________________________________________________________

## Validation Sign-Off

### Phase Completion Checklist

| Phase                  | Completed | Date           | Signed By      |
| :---------------------- | :--------- | :---------------| :----------------|
| Phase 1: Environment   | ☐         | \_\_\_\_\_\_\_ | \_\_\_\_\_\_\_ |
| Phase 2: Paper Trading | ☐         | \_\_\_\_\_\_\_ | \_\_\_\_\_\_\_ |
| Phase 3: Testnet       | ☐         | \_\_\_\_\_\_\_ | \_\_\_\_\_\_\_ |
| Phase 4: Minimal Live  | ☐         | \_\_\_\_\_\_\_ | \_\_\_\_\_\_\_ |
| Phase 5: Production    | ☐         | \_\_\_\_\_\_\_ | \_\_\_\_\_\_\_ |

### Risk Acknowledgment

By signing below, I acknowledge that:

1. I have completed all validation phases
1. I understand the risks of live trading
1. I accept full responsibility for any losses
1. I have tested rollback procedures
1. I have configured appropriate risk limits

**Signature:** \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Date:** \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

______________________________________________________________________

## Appendix A: Quick Reference Commands

```bash
# Enable paper mode (safe)
export PAPER_MODE=true && export LIVE_TRADING_ENABLED=false

# Emergency stop: restart the servers with TRADING_HALTED=true, then cancel_all_cex_orders (section 4.5)
TRADING_HALTED=true python app/main.py

# Check current mode
python -c "from app.core.config import settings; print(f'Paper: {settings.PAPER_MODE}, Live: {settings.LIVE_TRADING_ENABLED}, Halted: {settings.TRADING_HALTED}')"

# Export audit log
curl http://localhost:8000/api/audit/export > trades.csv

# Run all tests
pytest --cov=. --cov-fail-under=70
```

## Appendix B: Common Issues

| Issue                   | Cause                      | Resolution                          |
| :----------------------- | :--------------------------| :-------------------------------------|
| "Live trading disabled" | LIVE_TRADING_ENABLED=false | Set to true after validation        |
| "Trading halted"        | TRADING_HALTED=true        | Set to false when ready             |
| "Exchange not allowed"  | Missing ALLOW_EXCHANGES    | Add exchange to allowlist           |
| "Rate limited"          | Too many requests          | Reduce frequency or increase limits |
| "Insufficient balance"  | Not enough funds           | Deposit or reduce order size        |

## Appendix C: Performance Benchmarks

See `docs/BENCHMARKS.md` for expected latency and throughput metrics.
