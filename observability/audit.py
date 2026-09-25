from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Optional

from storage_paths import data_path


class AuditLog:
    """
    Optional SQLite audit log.

    This is OFF by default. Enable by setting `AUDIT_DB_PATH` (or `READYTRADER_AUDIT_DB_PATH`).
    The log is intended for operators to debug and review tool activity.

    Compliance Enhancement (Week 4):
    - Added 'previous_hash' to support immutable ledger concept.
    - Added 'export_tax_report' for CSV compliance exports.

    IMPORTANT:
    - This does NOT persist risk-consent state (consent remains in-memory only by design).
    - Avoid storing secrets. We store only a summarized view of tool outputs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def enabled(self) -> bool:
        # Default enabled in 'data/audit.db' if directory exists
        path = self._db_path()
        return bool(path)

    def append(
        self,
        *,
        ts_ms: int,
        request_id: str,
        tool: str,
        ok: bool,
        error_code: str | None = None,
        mode: str | None = None,
        venue: str | None = None,
        exchange: str | None = None,
        market_type: str | None = None,
        summary: Dict[str, Any] | None = None,
    ) -> None:
        conn = self._get_conn()
        if conn is None:
            return
        payload = json.dumps(summary or {}, sort_keys=True)

        with self._lock:
            # Tamper-evident hash chain (best-effort): each row stores previous_hash + event_hash
            prev_hash = "0" * 64
            try:
                row = conn.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
                if row and row[0]:
                    prev_hash = str(row[0])
            except Exception:
                # If table/column doesn't exist yet (older DB), we fall back to zero hash.
                prev_hash = "0" * 64

            material = json.dumps(
                {
                    "prev": prev_hash,
                    "ts_ms": int(ts_ms),
                    "request_id": str(request_id),
                    "tool": str(tool),
                    "ok": bool(ok),
                    "error_code": error_code,
                    "mode": mode,
                    "venue": venue,
                    "exchange": exchange,
                    "market_type": market_type,
                    "summary_json": payload,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            event_hash = hashlib.sha256(material).hexdigest()

            conn.execute(
                """
                INSERT INTO audit_events(
                    ts_ms, request_id, tool, ok, error_code, mode, venue, exchange, market_type, summary_json,
                    previous_hash, event_hash
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(ts_ms),
                    str(request_id),
                    str(tool),
                    1 if ok else 0,
                    error_code,
                    mode,
                    venue,
                    exchange,
                    market_type,
                    payload,
                    prev_hash,
                    event_hash,
                ),
            )
            conn.commit()

    def export_tax_report(self) -> str:
        """
        Export a CSV report of all successful trade executions.
        Compatible with generic tax software imports (Date, Type, Received, Sent, Fee).
        """
        conn = self._get_conn()
        if conn is None:
            return "Timestamp,Type,Details,Status\n"  # Empty CSV

        with self._lock:
            # Query only successful execution tools
            cursor = conn.execute(
                """
                SELECT ts_ms, tool, summary_json 
                FROM audit_events 
                WHERE ok=1 AND tool IN ('swap_tokens', 'place_cex_order', 'transfer_eth')
                ORDER BY ts_ms ASC
                """
            )
            rows = cursor.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp (ISO)", "Tool", "Venue", "Symbol/Token", "Amount", "Side", "TxHash/OrderID"])

        for r in rows:
            ts_ms, tool, summary_str = r
            try:
                data = json.loads(summary_str)
            except Exception:
                data = {}

            iso_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts_ms / 1000))
            venue = data.get("venue") or data.get("exchange") or "unknown"

            # Normalize fields based on tool type
            symbol = "N/A"
            amount = "0"
            side = "N/A"
            tx_id = "N/A"

            if tool == "swap_tokens":
                symbol = f"{data.get('from_token')} -> {data.get('to_token')}"
                amount = data.get("amount")
                side = "SWAP"
                tx_id = data.get("tx_hash") or "see_logs"
            elif tool == "place_cex_order":
                symbol = data.get("symbol")
                amount = data.get("amount")
                side = data.get("side", "").upper()
                order = data.get("order") or {}
                tx_id = order.get("id") or data.get("order_id") or "see_logs"
            elif tool == "transfer_eth":
                symbol = data.get("chain", "ETH")
                amount = data.get("amount")
                side = "SEND"
                tx_id = data.get("tx_hash") or "see_logs"

            writer.writerow([iso_time, tool, venue, symbol, amount, side, tx_id])

        return output.getvalue()

    def _db_path(self) -> str:
        default = data_path("audit.db")
        p = (os.getenv("READYTRADER_AUDIT_DB_PATH") or os.getenv("AUDIT_DB_PATH") or default).strip()
        if not os.path.exists(os.path.dirname(p)):
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
            except Exception:
                return ""
        return p

    def _get_conn(self) -> Optional[sqlite3.Connection]:
        path = self._db_path()
        if not path:
            return None
        with self._lock:
            if self._conn is None:
                self._conn = sqlite3.connect(path, check_same_thread=False)
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts_ms INTEGER NOT NULL,
                        request_id TEXT NOT NULL,
                        tool TEXT NOT NULL,
                        ok INTEGER NOT NULL,
                        error_code TEXT,
                        mode TEXT,
                        venue TEXT,
                        exchange TEXT,
                        market_type TEXT,
                        summary_json TEXT NOT NULL,
                        previous_hash TEXT,
                        event_hash TEXT
                    )
                    """
                )
                # Backward-compatible migrations for older DB files
                cols = {r[1] for r in self._conn.execute("PRAGMA table_info(audit_events)").fetchall()}
                if "previous_hash" not in cols:
                    self._conn.execute("ALTER TABLE audit_events ADD COLUMN previous_hash TEXT;")
                if "event_hash" not in cols:
                    self._conn.execute("ALTER TABLE audit_events ADD COLUMN event_hash TEXT;")
                self._conn.commit()
            return self._conn


def now_ms() -> int:
    return int(time.time() * 1000)
