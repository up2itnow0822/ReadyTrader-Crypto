from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Optional

from storage_paths import data_path, ensure_parent


class IdempotencyStore:
    """
    Optional idempotency store with an in-memory hot cache and optional SQLite persistence.

    Why this exists:
    - Agents often retry tool calls (network hiccups, tool timeouts, etc.).
    - For order placement / execution tools, retries can cause duplicate actions.
    - Idempotency keys let ReadyTrader-Crypto return the prior result instead of re-executing.

    Persistence is explicitly optional and OFF by default:
    - If `IDEMPOTENCY_DB_PATH` (or `READYTRADER_IDEMPOTENCY_DB_PATH`) is set, results are stored in SQLite.
    - If unset, this store is purely in-memory and resets on restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._conn: Optional[sqlite3.Connection] = None

    def clear(self) -> None:
        """
        Clear in-memory cache (useful for tests). Does not delete persisted data.
        """
        with self._lock:
            self._mem.clear()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        k = (key or "").strip()
        if not k:
            return None
        with self._lock:
            cached = self._mem.get(k)
        if cached is not None:
            return cached

        conn = self._get_conn()
        if conn is None:
            return None
        row = conn.execute("SELECT payload_json FROM idempotency WHERE key = ?", (k,)).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[0])
            if not isinstance(payload, dict):
                return None
        except Exception:
            return None
        with self._lock:
            self._mem[k] = payload
        return payload

    def set(self, key: str, payload: Dict[str, Any]) -> None:
        k = (key or "").strip()
        if not k:
            return
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        with self._lock:
            self._mem[k] = payload

        conn = self._get_conn()
        if conn is None:
            return
        now_ms = int(time.time() * 1000)
        conn.execute(
            """
            INSERT INTO idempotency(key, payload_json, created_at_ms, updated_at_ms)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, updated_at_ms=excluded.updated_at_ms
            """,
            (k, json.dumps(payload, sort_keys=True), now_ms, now_ms),
        )
        conn.commit()

    def _db_path(self) -> str:
        default = data_path("idempotency.db")
        p = (os.getenv("READYTRADER_IDEMPOTENCY_DB_PATH") or os.getenv("IDEMPOTENCY_DB_PATH") or default).strip()
        ensure_parent(p)
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
                    CREATE TABLE IF NOT EXISTS idempotency(
                        key TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        created_at_ms INTEGER NOT NULL,
                        updated_at_ms INTEGER NOT NULL
                    )
                    """
                )
                self._conn.commit()
            return self._conn
