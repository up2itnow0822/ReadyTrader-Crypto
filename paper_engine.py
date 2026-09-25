import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from storage_paths import data_path, ensure_parent

# Largest amount, price or deposit the paper ledger accepts. float64 keeps cents exact far beyond this,
# and it keeps amount x price finite.
MAX_MAGNITUDE = 1e12
# Largest balance the ledger will hold. Deposits are capped per call by MAX_MAGNITUDE; this caps what
# repeated deposits or fills can accumulate, keeping every balance well inside float64's exact range.
MAX_BALANCE = 1e15
# Valued at 1 USD each without a market-data lookup, here and in the Risk Guardian (app/tools/trading.py).
USD_STABLES = frozenset({"USD", "USDT", "USDC", "DAI", "BUSD", "FDUSD", "TUSD", "USDP"})


def _validate_order(symbol: Any, side: Any, amount: Any, price: Any) -> Dict[str, Any]:
    """
    Normalise and validate an order. Returns {"ok": True, base, quote, symbol, side, amount, price,
    total_value} or {"ok": False, "code", "message"}. Shared by market fills and limit orders so the two
    paths cannot drift apart.
    """
    import math

    def refuse(code: str, message: str) -> Dict[str, Any]:
        return {"ok": False, "code": code, "message": message}

    parts = str(symbol or "").split("/")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return refuse("invalid_symbol", f"Symbol must look like BASE/QUOTE (e.g. BTC/USDT), got {symbol!r}")
    if ":" in str(symbol):
        # BTC/USDT:USDT is a perpetual/futures contract; the paper ledger holds spot balances only.
        return refuse("invalid_symbol", f"Paper trading simulates spot pairs; {symbol!r} is a contract symbol (use the spot pair, e.g. BTC/USDT)")
    # Asset codes are case-insensitive (usdt and USDT are one balance); the ledger keys them upper case.
    base, quote = parts[0].strip().upper(), parts[1].strip().upper()
    if base == quote or len(base) > 32 or len(quote) > 32:
        return refuse("invalid_symbol", f"Symbol must name two different assets of at most 32 characters, got {symbol!r}")

    side = str(side or "").strip().lower()
    if side not in ("buy", "sell"):
        return refuse("invalid_side", f"Side must be 'buy' or 'sell', got {side!r}")

    try:
        amount, price = float(amount), float(price)
    except (TypeError, ValueError):
        return refuse("invalid_amount", "Amount and price must be numbers")
    if not math.isfinite(amount) or amount <= 0 or amount > MAX_MAGNITUDE:
        return refuse("invalid_amount", f"Amount must be a positive number no larger than {MAX_MAGNITUDE:g}, got {amount}")
    if not math.isfinite(price) or price <= 0 or price > MAX_MAGNITUDE:
        return refuse("invalid_price", f"Price must be a positive number no larger than {MAX_MAGNITUDE:g}, got {price}")

    total_value = amount * price
    if not math.isfinite(total_value) or total_value <= 0 or total_value > MAX_BALANCE:
        return refuse("invalid_amount", "Order value (amount x price) is out of range")

    # symbol is rebuilt so the order log always agrees with the balance keys
    return {"ok": True, "base": base, "quote": quote, "symbol": f"{base}/{quote}", "side": side, "amount": amount, "price": price, "total_value": total_value}


class PaperTradingEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("READYTRADER_PAPER_DB_PATH", os.getenv("PAPER_DB_PATH", data_path("paper.db")))
        ensure_parent(self.db_path)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Create balances table
        c.execute("""CREATE TABLE IF NOT EXISTS balances
                     (user_id TEXT, asset TEXT, amount REAL, 
                      PRIMARY KEY (user_id, asset))""")
        # Create orders table
        # NOTE: Prior versions had a schema bug (duplicate column names). We create a correct schema here.
        c.execute(
            """CREATE TABLE IF NOT EXISTS orders
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id TEXT NOT NULL,
                      timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                      side TEXT NOT NULL,
                      symbol TEXT NOT NULL,
                      amount REAL NOT NULL,
                      price REAL NOT NULL,
                      total_value REAL NOT NULL,
                      type TEXT DEFAULT 'market',
                      status TEXT DEFAULT 'filled',
                      rationale TEXT,
                      pnl_realized REAL)"""
        )

        # Equity snapshots for real drawdown/daily PnL metrics
        c.execute(
            """CREATE TABLE IF NOT EXISTS equity_snapshots
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id TEXT NOT NULL,
                      timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                      equity_usd REAL NOT NULL)"""
        )

        # Net deposits in USD (each valued when it was made), so the drawdown and daily-loss rules
        # measure trading results: topping the account up is not a gain and does not end a halt.
        c.execute("CREATE TABLE IF NOT EXISTS paper_deposits (user_id TEXT PRIMARY KEY, deposits_usd REAL NOT NULL)")

        # Asset price cache (derived from executed trades; no external price feed required)
        c.execute(
            """CREATE TABLE IF NOT EXISTS asset_prices
                     (asset TEXT PRIMARY KEY,
                      price_usd REAL NOT NULL,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
        )
        conn.commit()

        # Schema Migration: ensure required columns exist for older DBs
        cols = {row[1] for row in c.execute("PRAGMA table_info(orders)").fetchall()}
        if "rationale" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN rationale TEXT")
        if "pnl_realized" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN pnl_realized REAL")
        if "type" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN type TEXT DEFAULT 'market'")
        if "status" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'filled'")
        snap_cols = {row[1] for row in c.execute("PRAGMA table_info(equity_snapshots)").fetchall()}
        if "deposits_usd" not in snap_cols:
            c.execute("ALTER TABLE equity_snapshots ADD COLUMN deposits_usd REAL")
        conn.commit()

        conn.close()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _set_asset_price_usd(self, asset: str, price_usd: float) -> None:
        if price_usd <= 0:
            return
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO asset_prices (asset, price_usd, updated_at) VALUES (?, ?, ?)",
            (asset.upper(), float(price_usd), self._now_iso()),
        )
        conn.commit()
        conn.close()

    def mark_price_usd(self, asset: str, price_usd: float) -> None:
        """Record a market price for `asset` (USD per unit) as its mark-to-market price."""
        try:
            price = float(price_usd)
        except (TypeError, ValueError):
            return
        import math

        if math.isfinite(price) and price > 0:
            self._set_asset_price_usd(asset, price)

    def _get_asset_price_usd(self, asset: str) -> Optional[float]:
        a = asset.upper()
        if a in USD_STABLES:
            return 1.0
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT price_usd FROM asset_prices WHERE asset=?", (a,))
        row = c.fetchone()
        conn.close()
        return float(row[0]) if row else None

    def get_portfolio_value_usd(self, user_id: str) -> float:
        """
        Mark-to-market portfolio using last known executed prices (derived from paper trades).
        Stablecoins are valued at $1.
        Assets without a known price are excluded (conservative).
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT asset, amount FROM balances WHERE user_id=?", (user_id,))
        rows = c.fetchall()
        conn.close()

        # Funds reserved by resting limit orders still belong to the account: a BUY holds its quote
        # value, a SELL its base amount. Leaving them out made placing an order look like a loss.
        conn = sqlite3.connect(self.db_path)
        open_orders = conn.execute("SELECT side, symbol, amount, total_value FROM orders WHERE user_id=? AND status='open'", (user_id,)).fetchall()
        conn.close()
        holdings: Dict[str, float] = {}
        for asset, amount in rows:
            if amount is not None:
                holdings[str(asset).upper()] = holdings.get(str(asset).upper(), 0.0) + float(amount)
        for side, symbol, amount, total_value in open_orders:
            base, _, quote = str(symbol).upper().partition("/")
            asset, reserved = (quote, total_value) if side == "buy" else (base, amount)
            if asset and reserved is not None:
                holdings[asset] = holdings.get(asset, 0.0) + float(reserved)

        total = 0.0
        for asset, amount in holdings.items():
            px = self._get_asset_price_usd(asset)
            if px is None:
                continue
            total += float(amount) * float(px)
        return float(total)

    def mark_day_open(self, user_id: str) -> None:
        """Record the account's value once per UTC day, at its first risk check: the daily-loss
        baseline when the account made no snapshot the day before."""
        today = self._now_iso()[:10]
        conn = sqlite3.connect(self.db_path)
        seen = conn.execute("SELECT 1 FROM equity_snapshots WHERE user_id=? AND substr(timestamp, 1, 10)=? LIMIT 1", (user_id, today)).fetchone()
        has_any = conn.execute("SELECT 1 FROM equity_snapshots WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
        conn.close()
        if has_any and not seen:
            self._snapshot_equity(user_id)

    def get_net_deposits_usd(self, user_id: str) -> float:
        """USD deposited (net of internal debits), each deposit valued at its price when it was made."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT deposits_usd FROM paper_deposits WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return float(row[0]) if row and row[0] is not None else 0.0

    def _snapshot_equity(self, user_id: str) -> None:
        equity = self.get_portfolio_value_usd(user_id)
        deposits = self.get_net_deposits_usd(user_id)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "INSERT INTO equity_snapshots (user_id, timestamp, equity_usd, deposits_usd) VALUES (?, ?, ?, ?)",
            (user_id, self._now_iso(), float(equity), float(deposits)),
        )
        conn.commit()
        conn.close()

    def get_balance(self, user_id: str, asset: str) -> float:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT amount FROM balances WHERE user_id=? AND asset=?", (user_id, str(asset or "").strip().upper()))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0.0

    def get_balances(self, user_id: str) -> dict[str, float]:
        """Get all balances for a user as a dictionary."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT asset, amount FROM balances WHERE user_id=?", (user_id,))
        rows = c.fetchall()
        conn.close()
        return {asset: float(amount) for asset, amount in rows if amount}

    def _txn(self) -> sqlite3.Connection:
        """A connection holding the write lock, so a balance check and the writes that follow are one step."""
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.execute("BEGIN IMMEDIATE")
        return conn

    @staticmethod
    def _balance_in(conn: sqlite3.Connection, user_id: str, asset: str) -> float:
        row = conn.execute("SELECT amount FROM balances WHERE user_id=? AND asset=?", (user_id, asset)).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    @staticmethod
    def _set_balance_in(conn: sqlite3.Connection, user_id: str, asset: str, amount: float) -> None:
        conn.execute("INSERT OR REPLACE INTO balances (user_id, asset, amount) VALUES (?, ?, ?)", (user_id, asset, amount))

    def deposit_result(self, user_id: str, asset: str, amount: float) -> Dict[str, Any]:
        """
        Credit (or, internally, debit with a negative amount) a balance atomically, and say in data
        whether it happened: {"ok": True, "message", "balance"} or {"ok": False, "code", "message"}.
        Codes: invalid_amount | balance_limit.
        """
        import math

        def refuse(code: str, message: str) -> Dict[str, Any]:
            return {"ok": False, "code": code, "message": message}

        asset = str(asset or "").strip().upper()
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return refuse("invalid_amount", "Deposit refused: amount must be a number")
        if not math.isfinite(amount) or abs(amount) > MAX_MAGNITUDE:
            return refuse("invalid_amount", f"Deposit refused: amount must be a finite number no larger than {MAX_MAGNITUDE:g}")

        # The deposit's USD value at today's price. An asset with no known price is valued at 0 and
        # would read as a gain once priced, so the MCP tool (deposit_paper_funds) refuses a deposit it
        # cannot price; only direct engine callers (tests, examples) can make one.
        value_usd = amount * (self._get_asset_price_usd(asset) or 0.0)
        conn = self._txn()
        try:
            new_balance = self._balance_in(conn, user_id, asset) + amount
            if abs(new_balance) > MAX_BALANCE:
                conn.execute("ROLLBACK")
                return refuse("balance_limit", f"Deposit refused: the {asset} balance may not exceed {MAX_BALANCE:g}")
            self._set_balance_in(conn, user_id, asset, new_balance)
            row = conn.execute("SELECT deposits_usd FROM paper_deposits WHERE user_id=?", (user_id,)).fetchone()
            deposits = (float(row[0]) if row and row[0] is not None else 0.0) + value_usd
            conn.execute("INSERT OR REPLACE INTO paper_deposits (user_id, deposits_usd) VALUES (?, ?)", (user_id, deposits))
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
        self._snapshot_equity(user_id)
        return {"ok": True, "message": f"Deposited {amount} {asset}. New Balance: {new_balance}", "balance": float(new_balance)}

    def deposit(self, user_id: str, asset: str, amount: float) -> str:
        """String form of deposit_result (kept for existing callers). Prefer the structured method."""
        return str(self.deposit_result(user_id, asset, amount)["message"])

    def reset_wallet(self, user_id: str) -> str:
        """Clear all balances and trade history for a user in paper mode."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM balances WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM orders WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM equity_snapshots WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM paper_deposits WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        return f"Paper wallet and history for {user_id} have been reset."

    def place_limit_order(self, user_id: str, side: str, symbol: str, amount: float, price: float) -> str:
        """
        Place a limit order. Funds are reserved in the same transaction that records the order, so an
        order can never exist without its reservation (and two concurrent orders cannot both reserve the
        same funds).
        """
        order = _validate_order(symbol, side, amount, price)
        if not order["ok"]:
            return f"Order refused: {order['message']}"
        side, symbol, amount, price, total_value = order["side"], order["symbol"], order["amount"], order["price"], order["total_value"]
        reserve_asset, reserve = (order["quote"], total_value) if side == "buy" else (order["base"], amount)

        conn = self._txn()
        try:
            have = self._balance_in(conn, user_id, reserve_asset)
            if have < reserve:
                conn.execute("ROLLBACK")
                return f"Insufficient fund. Have {have} {reserve_asset}, need {reserve}"
            if have - reserve == have:
                conn.execute("ROLLBACK")
                return "Order refused: order is too small relative to the balance to be recorded accurately"
            self._set_balance_in(conn, user_id, reserve_asset, have - reserve)
            cur = conn.execute(
                "INSERT INTO orders (user_id, side, symbol, amount, price, total_value, type, status) VALUES (?, ?, ?, ?, ?, ?, 'limit', 'open')",
                (user_id, side, symbol, amount, price, total_value),
            )
            order_id = cur.lastrowid
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
        self._snapshot_equity(user_id)
        return f"Order Placed: {side.upper()} {amount} {symbol} @ {price}. ID: {order_id}"

    def check_open_orders(self, symbol: str, current_price: float) -> List[str]:
        """
        Fill open limit orders that `current_price` crosses. Marking an order filled and crediting the
        account happen in ONE transaction: an order is never 'filled' without its credit, or credited twice.
        Returns a list of messages for filled orders.
        """
        import math

        parts = str(symbol or "").split("/")
        try:
            current_price = float(current_price)
        except (TypeError, ValueError):
            return []
        if len(parts) != 2 or not math.isfinite(current_price) or current_price <= 0:
            return []
        base, quote = parts[0].strip().upper(), parts[1].strip().upper()
        symbol = f"{base}/{quote}"

        filled: List[tuple] = []
        conn = self._txn()
        try:
            rows = conn.execute("SELECT id, user_id, side, amount, price, total_value FROM orders WHERE symbol=? AND status='open'", (symbol,)).fetchall()
            for oid, uid, side, amt, price, val in rows:
                crosses = (side == "buy" and current_price <= price) or (side == "sell" and current_price >= price)
                if not crosses:
                    continue
                credit_asset, credit = (base, amt) if side == "buy" else (quote, val)
                held = self._balance_in(conn, uid, credit_asset)
                if credit is None or not math.isfinite(float(credit)) or held + float(credit) > MAX_BALANCE:
                    continue  # leave it open rather than poison the ledger
                conn.execute("UPDATE orders SET status='filled' WHERE id=? AND status='open'", (oid,))
                self._set_balance_in(conn, uid, credit_asset, held + float(credit))
                filled.append((side, oid, uid, amt, price))
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

        filled_msgs = []
        for side, oid, uid, amt, price in filled:
            filled_msgs.append(f"Order #{oid} FILLED: {side.upper()} {amt} {symbol} @ {price}")
            if quote.upper() in USD_STABLES:
                self._set_asset_price_usd(quote, 1.0)
                self._set_asset_price_usd(base, float(price))
            self._snapshot_equity(uid)
        return filled_msgs

    def execute_trade_result(
        self,
        user_id: str,
        side: str,
        symbol: str,
        amount: float,
        price: float,
        rationale: str = "",
        *,
        update_price_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a paper trade and say, in data, whether it happened.

        Returns {"ok": True, "message", "fill": {...}} or {"ok": False, "code", "message"}.
        Nothing is written to the ledger unless the trade is valid and funded. Codes:
        invalid_symbol | invalid_side | invalid_amount | invalid_price | insufficient_funds.
        """

        def refuse(code: str, message: str) -> Dict[str, Any]:
            return {"ok": False, "code": code, "message": message}

        order = _validate_order(symbol, side, amount, price)
        if not order["ok"]:
            return order
        base, quote, symbol, side = order["base"], order["quote"], order["symbol"], order["side"]
        amount, price, total_value = order["amount"], order["price"], order["total_value"]

        # Check and move funds as ONE step. Separate read and write connections let two concurrent orders
        # both pass the balance check and overdraw, and lost each other's updates.
        spend_asset, spend = (quote, total_value) if side == "buy" else (base, amount)
        gain_asset, gain = (base, amount) if side == "buy" else (quote, total_value)
        conn = self._txn()
        try:
            have = self._balance_in(conn, user_id, spend_asset)
            if have < spend:
                conn.execute("ROLLBACK")
                return refuse("insufficient_funds", f"Insufficient fund. Have {have} {spend_asset}, need {spend}")
            held = self._balance_in(conn, user_id, gain_asset)
            if held + gain > MAX_BALANCE:
                conn.execute("ROLLBACK")
                return refuse("invalid_amount", f"Order would take the {gain_asset} balance past the ledger limit of {MAX_BALANCE:g}")
            if have - spend == have or held + gain == held:
                # float64 cannot represent this change at this balance: it would move one side of the
                # ledger and not the other (an asset bought for nothing).
                conn.execute("ROLLBACK")
                return refuse("invalid_amount", "Order is too small relative to the balance to be recorded accurately")
            self._set_balance_in(conn, user_id, spend_asset, have - spend)
            self._set_balance_in(conn, user_id, gain_asset, held + gain)
            conn.execute(
                "INSERT INTO orders (user_id, side, symbol, amount, price, total_value, rationale) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, side, symbol, amount, price, total_value, rationale),
            )
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

        # Update derived price cache (if quote looks like USD stable). Callers that fill at a synthetic
        # price (paper swap_tokens uses 1.0) pass update_price_cache=False so they cannot rewrite
        # mark-to-market and with it drawdown and PnL.
        if update_price_cache and quote.upper() in USD_STABLES:
            self._set_asset_price_usd(base, float(price))
            self._set_asset_price_usd(quote, 1.0)
        self._snapshot_equity(user_id)

        return {
            "ok": True,
            "message": f"Paper Trade Executed: {side.upper()} {amount} {symbol} @ {price}. Value: {total_value} {quote}. Rationale: {rationale}",
            "fill": {"side": side, "symbol": symbol, "amount": amount, "price": price, "total_value": total_value, "quote": quote},
        }

    def execute_trade(
        self,
        user_id: str,
        side: str,
        symbol: str,
        amount: float,
        price: float,
        rationale: str = "",
    ) -> str:
        """String form of execute_trade_result (kept for existing callers). Prefer the structured method."""
        return str(self.execute_trade_result(user_id, side, symbol, amount, price, rationale)["message"])

    def get_risk_metrics(self, user_id: str) -> Dict[str, float]:
        """
        Calculate risk metrics for the user, measured on trading results: deposits are neither gains
        nor losses, and neither end a halt nor start one.
        Returns: { 'daily_pnl_pct', 'drawdown_pct', 'max_drawdown_pct' } (fractions, e.g. 0.10).

        The account's results are chained into a performance index (time-weighted return): between
        two snapshots, the return is the change in value less the deposits made in between, over the
        value before. `drawdown_pct` is the index's CURRENT fall from its best level (what the Risk
        Guardian's drawdown rule reads); `max_drawdown_pct` is the deepest fall on record.
        `daily_pnl_pct` is the index's change since the last snapshot of the previous UTC day, or
        since the day's first snapshot when the account made none the day before. The account's value
        now (at the latest marked prices) ends the series, so a price move counts before the next trade.
        """
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT timestamp, equity_usd, deposits_usd FROM equity_snapshots WHERE user_id=? ORDER BY timestamp ASC, id ASC",
            (user_id,),
        ).fetchall()
        conn.close()

        if not rows:
            return {"daily_pnl_pct": 0.0, "drawdown_pct": 0.0, "max_drawdown_pct": 0.0}

        # Snapshots from before deposits were tracked carry NULL: counted as no deposits (the old rule).
        series = [(str(ts), float(eq), float(dep or 0.0)) for ts, eq, dep in rows]
        series.append((self._now_iso(), self.get_portfolio_value_usd(user_id), self.get_net_deposits_usd(user_id)))

        index = peak = 1.0
        max_drawdown = current_drawdown = 0.0
        levels = [(series[0][0], index)]
        for (_, prev_equity, prev_deposits), (ts, equity, deposits) in zip(series, series[1:]):
            if prev_equity > 0:
                period_return = (equity - (deposits - prev_deposits)) / prev_equity - 1.0
                index *= max(0.0, 1.0 + period_return)
            peak = max(peak, index)
            current_drawdown = 1.0 - index / peak if peak > 0 else 0.0
            max_drawdown = max(max_drawdown, current_drawdown)
            levels.append((ts, index))

        today = self._now_iso()[:10]
        yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
        before = [level for ts, level in levels if ts[:10] == yesterday]
        start = before[-1] if before else next((level for ts, level in levels if ts[:10] == today), levels[-1][1])
        daily_pct = index / start - 1.0 if start > 0 else 0.0

        return {"daily_pnl_pct": float(daily_pct), "drawdown_pct": float(current_drawdown), "max_drawdown_pct": float(max_drawdown)}
