import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from storage_paths import data_path, ensure_parent


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

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
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

    def post_insight(
        self, symbol: str, agent_id: str, signal: str, confidence: float, reasoning: str, ttl_seconds: int = 3600, meta: Optional[Dict[str, Any]] = None
    ) -> MarketInsight:  # noqa: E501
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

        with sqlite3.connect(self.db_path) as conn:
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
                    json.dumps(insight.meta),
                ),
            )
        return insight

    def get_latest_insights(self, symbol: Optional[str] = None, limit: int = 5) -> List[MarketInsight]:
        now_ms = int(time.time() * 1000)
        query = "SELECT * FROM insights WHERE expires_at_ms > ?"
        params = [now_ms]

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())

        query += " ORDER BY timestamp_ms DESC LIMIT ?"
        params.append(limit)

        results = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            for row in cursor:
                results.append(self._row_to_insight(row))
        return results

    def get_insight(self, insight_id: str) -> Optional[MarketInsight]:
        query = "SELECT * FROM insights WHERE insight_id = ?"
        with sqlite3.connect(self.db_path) as conn:
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
