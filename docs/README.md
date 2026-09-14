## Docs Index

Recommended reading order for operators and developers.

______________________________________________________________________

### 1. Getting Started

| Document          | Description                                            |
| :---------------- | :----------------------------------------------------- |
| `../README.md`    | Project overview, installation, and quick start        |
| `ARCHITECTURE.md` | System architecture and component interactions         |
| `TOOLS.md`        | Complete MCP tool catalog with signatures and examples |

### 2. Operations & Deployment

| Document                   | Description                                     |
| :------------------------- | :---------------------------------------------- |
| `../RUNBOOK.md`            | Operator runbook + incident scenarios           |
| `ERRORS.md`                | Error codes + troubleshooting guide             |
| `HERMES_INTEGRATION.md`    | Hermes stdio MCP + skill wiring                 |
| `OPS_BTC_PRODUCTION.md`    | BTC live-halted ops pack (keys, monitoring)     |
| `UAT_BTC_PRODUCTION_MINUS_DUST.md` | Production-minus-dust UAT evidence     |
| `LIVE_TESTING_PROTOCOL.md` | **NEW** Formal live trading validation protocol |
| `THREAT_MODEL.md`          | Security threat model for live trading          |
| `CUSTODY.md`               | Key custody + rotation guidance                 |
| `SECURITY_REVIEW.md`       | **NEW** Pre-production security checklist       |

### 3. Performance & Quality

| Document        | Description                               |
| :-------------- | :---------------------------------------- |
| `BENCHMARKS.md` | **NEW** Latency and throughput benchmarks |
| `SCORECARD.md`  | Strategy performance scoring              |

### 4. Connectivity & Data

| Document        | Description                                              |
| :-------------- | :------------------------------------------------------- |
| `EXCHANGES.md`  | CEX capability matrix (Supported vs Experimental)        |
| `MARKETDATA.md` | MarketDataBus (freshness scoring + plugins + guardrails) |
| `SENTIMENT.md`  | Sentiment analysis and intelligence feeds                |

### 5. Positioning & Marketing

| Document         | Description                            |
| :--------------- | :------------------------------------- |
| `POSITIONING.md` | Credibility-safe marketing + messaging |

### 6. Release & Governance

| Document                            | Description                                     |
| :---------------------------------- | :---------------------------------------------- |
| `SUPPORT_POLICY.md`                 | **NEW** Support tiers, deprecation & versioning |
| `../CHANGELOG.md`                   | Version-to-version change summary               |
| `../RELEASE_READINESS_CHECKLIST.md` | Pre-distribution checklist                      |
| `../SECURITY.md`                    | Security policy and vulnerability reporting     |
| `../CONTRIBUTING.md`                | Contribution guidelines                         |

______________________________________________________________________

## Quick Reference

### Error Code Prefixes

| Prefix       | Category               | Example                            |
| :----------- | :--------------------- | :--------------------------------- |
| `CONFIG_1xx` | Configuration errors   | `CONFIG_101` - Missing credentials |
| `POLICY_2xx` | Policy violations      | `POLICY_201` - Chain not allowed   |
| `EXEC_3xx`   | Execution failures     | `EXEC_304` - Order placement error |
| `DATA_4xx`   | Market data errors     | `DATA_401` - Stale data            |
| `NET_5xx`    | Network errors         | `NET_501` - Connection timeout     |
| `AUTH_6xx`   | Authentication errors  | `AUTH_601` - Invalid API key       |
| `VAL_7xx`    | Validation errors      | `VAL_701` - Invalid symbol         |
| `SYS_8xx`    | System errors          | `SYS_801` - Rate limited           |
| `RISK_9xx`   | Risk management errors | `RISK_901` - Position too large    |

### Key Environment Variables

```bash
# Mode Control
PAPER_MODE=true              # Paper vs live trading
LIVE_TRADING_ENABLED=false   # Must be true for live execution
TRADING_HALTED=false         # Global kill switch

# Credentials
SIGNER_TYPE=keystore         # env_private_key | keystore | remote | cb_mpc_2pc
CEX_API_KEY=xxx              # Generic CEX credentials
CEX_BINANCE_API_KEY=xxx      # Exchange-specific credentials

# Policy Limits
ALLOW_CHAINS=ethereum,base   # Allowlisted chains
ALLOW_TOKENS=ETH,USDC,BTC    # Allowlisted tokens
MAX_TRADE_AMOUNT=1000        # Maximum trade value
```

### Performance Targets

| Operation        | P50   | P95   | Max    |
| :--------------- | :---- | :---- | :----- |
| Risk Validation  | 1ms   | 5ms   | 50ms   |
| Paper Order      | 15ms  | 40ms  | 150ms  |
| CEX Order (live) | 200ms | 400ms | 2000ms |
| DEX Swap (live)  | 15s   | 20s   | 60s    |

See `BENCHMARKS.md` for detailed performance metrics.
