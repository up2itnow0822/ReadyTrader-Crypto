import json
import math
import os
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from storage_paths import data_path, ensure_parent

MAX_SYMBOL_BYTES = 64
MAX_AGENT_BYTES = 128
MAX_REASONING_BYTES = 8192
MAX_META_BYTES = 4096
MAX_TTL_SECONDS = 86400
MAX_AGENT_INSIGHTS = 1000
MAX_TOTAL_INSIGHTS = 5000
MAX_READ_INSIGHTS = 100
MAX_DATABASE_BYTES = 128 * 1024 * 1024
VALID_SIGNALS = frozenset({"bullish", "bearish", "neutral"})


def _bounded_text(value: str, name: str, cap: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > cap or len(value.encode("utf-8")) > cap:
        raise ValueError(f"{name} must be nonblank and at most {cap} UTF-8 bytes")
    return value


@dataclass
class MarketInsight:
    insight_id: str
    symbol: str
    agent_id: str
    signal: str  # "bullish", "bearish", "neutral"
    confidence: float  # 0.0 to 1.0
    reasoning: str
    timestamp_ms: int
    expires_at_ms: int
    meta: Dict[str, Any]


class InsightStore:
    """
    Persistent store for Market Insights shared between agents (Phase 3).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("READYTRADER_INSIGHT_DB_PATH", os.getenv("INSIGHT_DB_PATH", data_path("insights.db")))
        ensure_parent(self.db_path)
        self._init_db()

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.db_path, timeout=2)) as conn:
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            conn.execute(f"PRAGMA max_page_count={MAX_DATABASE_BYTES // page_size}")
            conn.execute("PRAGMA journal_size_limit=1048576")
            with conn:
                yield conn

    def _prune(self, conn, now_ms):
        conn.execute("DELETE FROM insights WHERE expires_at_ms <= ? OR timestamp_ms < ?", (now_ms, now_ms - MAX_TTL_SECONDS * 1000))

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS insights (
                    insight_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT,
                    timestamp_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL,
                    meta_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_insight_symbol ON insights(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_insight_expiry ON insights(expires_at_ms)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_insight_agent ON insights(agent_id)")
            self._prune(conn, int(time.time() * 1000))
            # Apply retention to pre-upgrade stores too, rather than preserving an unbounded backlog.
            conn.execute(
                "DELETE FROM insights WHERE rowid IN (SELECT rowid FROM "
                "(SELECT rowid, ROW_NUMBER() OVER (PARTITION BY agent_id ORDER BY timestamp_ms DESC) AS rank FROM insights) "
                "WHERE rank > ?)",
                (MAX_AGENT_INSIGHTS,),
            )
            conn.execute(
                "DELETE FROM insights WHERE rowid NOT IN (SELECT rowid FROM insights ORDER BY timestamp_ms DESC LIMIT ?)",
                (MAX_TOTAL_INSIGHTS,),
            )

    def post_insight(
        self, symbol: str, agent_id: str, signal: str, confidence: float, reasoning: str, ttl_seconds: int = 3600, meta: Optional[Dict[str, Any]] = None
    ) -> MarketInsight:  # noqa: E501
        symbol = _bounded_text(symbol, "symbol", MAX_SYMBOL_BYTES).upper()
        _bounded_text(symbol, "symbol", MAX_SYMBOL_BYTES)
        agent_id = _bounded_text(agent_id, "agent_id", MAX_AGENT_BYTES)
        reasoning = _bounded_text(reasoning, "reasoning", MAX_REASONING_BYTES)
        if not isinstance(signal, str) or signal.lower() not in VALID_SIGNALS:
            raise ValueError("signal must be bullish, bearish, or neutral")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1 or not math.isfinite(confidence):
            raise ValueError("confidence must be a finite number in [0, 1]")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be an integer in [1, {MAX_TTL_SECONDS}]")
        if meta is not None and not isinstance(meta, dict):
            raise ValueError("meta must be an object")
        try:
            meta_json = json.dumps(meta or {}, ensure_ascii=False, allow_nan=False)
            if len(meta_json.encode("utf-8")) > MAX_META_BYTES:
                raise ValueError("meta is too large")
        except (TypeError, RecursionError) as exc:
            raise ValueError("meta must be bounded JSON") from exc
        now_ms = int(time.time() * 1000)
        insight_id = secrets.token_hex(8)
        expires_at_ms = now_ms + (ttl_seconds * 1000)

        insight = MarketInsight(
            insight_id=insight_id,
            symbol=symbol.upper(),
            agent_id=agent_id,
            signal=signal.lower(),
            confidence=float(confidence),
            reasoning=reasoning,
            timestamp_ms=now_ms,
            expires_at_ms=expires_at_ms,
            meta=meta or {},
        )

        with self._connect() as conn:
            # Serialize cleanup, quota checks, and insertion across all processes sharing the DB.
            conn.execute("BEGIN IMMEDIATE")
            self._prune(conn, now_ms)
            count = conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
            agent_count = conn.execute("SELECT COUNT(*) FROM insights WHERE agent_id = ?", (agent_id,)).fetchone()[0]
            if count >= MAX_TOTAL_INSIGHTS or agent_count >= MAX_AGENT_INSIGHTS:
                raise ValueError("Insight storage quota exceeded; wait for existing insights to expire")
            conn.execute(
                """
                INSERT INTO insights (insight_id, symbol, agent_id, signal, confidence, reasoning, timestamp_ms, expires_at_ms, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    insight.insight_id,
                    insight.symbol,
                    insight.agent_id,
                    insight.signal,
                    insight.confidence,
                    insight.reasoning,
                    insight.timestamp_ms,
                    insight.expires_at_ms,
                    meta_json,
                ),
            )
        return insight

    def get_latest_insights(self, symbol: Optional[str] = None, limit: int = 5) -> List[MarketInsight]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_READ_INSIGHTS:
            raise ValueError(f"limit must be an integer in [1, {MAX_READ_INSIGHTS}]")
        if symbol is not None:
            _bounded_text(symbol, "symbol", MAX_SYMBOL_BYTES)
        now_ms = int(time.time() * 1000)
        query = "SELECT * FROM insights WHERE expires_at_ms > ?"
        params = [now_ms]

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())

        query += " ORDER BY timestamp_ms DESC LIMIT ?"
        params.append(limit)

        results = []
        with self._connect() as conn:
            self._prune(conn, now_ms)
            cursor = conn.execute(query, params)
            for row in cursor:
                results.append(self._row_to_insight(row))
        return results

    def get_insight(self, insight_id: str) -> Optional[MarketInsight]:
        query = "SELECT * FROM insights WHERE insight_id = ?"
        with self._connect() as conn:
            self._prune(conn, int(time.time() * 1000))
            row = conn.execute(query, (insight_id,)).fetchone()
            if row:
                return self._row_to_insight(row)
        return None

    def _row_to_insight(self, row) -> MarketInsight:
        return MarketInsight(
            insight_id=row[0],
            symbol=row[1],
            agent_id=row[2],
            signal=row[3],
            confidence=row[4],
            reasoning=row[5],
            timestamp_ms=row[6],
            expires_at_ms=row[7],
            meta=json.loads(row[8]) if row[8] else {},
        )
