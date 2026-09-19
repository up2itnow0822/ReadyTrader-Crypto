#!/usr/bin/env python3
"""
TEST TOOLING -- NOT PRODUCT CODE.

api_server.py's `/api/approve-trade` only ever sees proposals created inside its OWN
process's ExecutionStore (proposals live in memory, keyed to that process; there is no
cross-process proposal bus). Live/approve-each mode is also the only mode that creates
proposals at all. Neither of those is something the frontend's tests can reach through
the normal product surface, so this script starts a real api_server process in paper
mode, seeds a handful of proposals directly into that process's own ExecutionStore, and
serves it with uvicorn -- giving the frontend's Vitest/Playwright suites something real
to talk to.

It also adds ONE extra route, `POST /__test/seed`, so a spec can seed more proposals
mid-run (e.g. a proposal that expires in a few seconds, seeded right before the
assertion that watches it expire). That route is added here, on the already-constructed
`api_server.app`, and only exists when THIS script runs the app -- it is never present
when api_server.py is imported by the real application.

Usage:
    python frontend/e2e/api_harness.py --port 8171            # API_AUTH_REQUIRED=false
    python frontend/e2e/api_harness.py --port 8171 --auth     # API_AUTH_REQUIRED=true

Always paper mode, always a temp DB (never the repo's data/ directory).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Keep these in sync with frontend/e2e/constants.ts.
TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_PASSWORD = "test-admin-password-123"
TEST_JWT_SECRET = "e2e-test-jwt-secret-do-not-use-in-production-42"  # > 32 chars

AGENT_USER_ID = "agent_zero"
STARTING_USDT = 100_000.0

BTC_ORDER_PAYLOAD = {
    "symbol": "BTC/USDT",
    "side": "buy",
    "amount": 0.01,
    "order_type": "limit",
    "price": 50000.0,
    "exchange": "binance",
    "market_type": "spot",
}


def _configure_environment(auth: bool, db_dir: Path) -> None:
    """Paper mode, no real exchange/signing, and a temp DB -- never the repo's data/."""
    os.environ["PAPER_MODE"] = "true"
    os.environ["LIVE_TRADING_ENABLED"] = "false"
    os.environ["TRADING_HALTED"] = "true"
    os.environ["SIGNER_TYPE"] = "null"
    os.environ["EXECUTION_MODE"] = "cex"
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    # DEV_MODE=true keeps api_server's production-only startup checks (which demand a
    # non-wildcard CORS origin and a few other things irrelevant to this harness) out
    # of the way, the same way tests/conftest.py and tests/test_api_server.py do.
    os.environ["DEV_MODE"] = "true"
    os.environ["READYTRADER_PAPER_DB_PATH"] = str(db_dir / "paper.db")
    os.environ["READYTRADER_EXECUTION_DB_PATH"] = str(db_dir / "execution.db")

    if auth:
        os.environ["API_AUTH_REQUIRED"] = "true"
        os.environ["API_JWT_SECRET"] = TEST_JWT_SECRET
        os.environ["API_ADMIN_USERNAME"] = TEST_ADMIN_USERNAME
        os.environ["API_ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD
    else:
        os.environ["API_AUTH_REQUIRED"] = "false"


def _seed_default_proposals(store) -> None:
    """The proposals the frontend's e2e journeys need, seeded straight into the store."""
    # 1) The happy path: approve -> confirm -> executes -> shows up in /history.
    store.create(kind="place_cex_order", payload=dict(BTC_ORDER_PAYLOAD), ttl_seconds=900)

    # 2) An XSS probe in a field the UI renders as plain text (summary.rationale).
    store.create(
        kind="swap_tokens",
        payload={
            "from_token": "ETH",
            "to_token": "USDC",
            "amount": 1.5,
            "chain": "ethereum",
            "rationale": "<img src=x onerror=alert(1)>",
        },
        ttl_seconds=900,
    )

    # 3) Expires almost immediately, to exercise the on-screen countdown/expiry.
    store.create(kind="place_cex_order", payload=dict(BTC_ORDER_PAYLOAD, amount=0.001), ttl_seconds=5)

    # 4) Costs ~5,000,000 USDT against a 100,000 USDT wallet -- the paper engine
    #    refuses it with insufficient_funds, which /api/approve-trade reports as a 422.
    store.create(kind="place_cex_order", payload=dict(BTC_ORDER_PAYLOAD, amount=100.0), ttl_seconds=900)


def create_app(auth: bool, db_dir: Path):
    _configure_environment(auth, db_dir)

    import api_server  # noqa: E402 -- must import only after env vars are set
    from execution_store import ExecutionStore  # noqa: E402
    from fastapi import Body  # noqa: E402

    # A fresh store: nothing this process might otherwise load from an on-disk
    # proposal row belonging to a different session id leaks into the seeded set.
    api_server.global_container.execution_store = ExecutionStore()
    api_server.global_container.paper_engine.deposit(AGENT_USER_ID, "USDT", STARTING_USDT)
    _seed_default_proposals(api_server.global_container.execution_store)

    @api_server.app.post("/__test/seed")
    async def _seed_extra(payload: dict = Body(...)):  # pragma: no cover -- test-only route
        """Seed one more proposal mid-run. Never present outside this harness."""
        kind = str(payload.get("kind") or "place_cex_order")
        proposal_payload = payload.get("payload") or dict(BTC_ORDER_PAYLOAD)
        ttl_seconds = int(payload.get("ttl_seconds") or 120)
        prop = api_server.global_container.execution_store.create(
            kind=kind, payload=proposal_payload, ttl_seconds=ttl_seconds
        )
        return {"request_id": prop.request_id}

    @api_server.app.post("/__test/reset-wallet")
    async def _reset_wallet():  # pragma: no cover -- test-only route
        """Top the paper wallet back up (used after the resilience test restarts the process)."""
        api_server.global_container.paper_engine.deposit(AGENT_USER_ID, "USDT", STARTING_USDT)
        return {"ok": True}

    return api_server.app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--auth", action="store_true", help="Require a JWT (API_AUTH_REQUIRED=true)")
    args = parser.parse_args()

    db_dir = Path(tempfile.mkdtemp(prefix="readytrader-e2e-"))
    app = create_app(auth=args.auth, db_dir=db_dir)

    import uvicorn

    print(
        f"[api_harness] auth={'on' if args.auth else 'off'} admin={TEST_ADMIN_USERNAME!r} db_dir={db_dir}",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
