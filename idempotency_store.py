from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from storage_paths import data_path, ensure_parent


class IdempotencyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data: Dict[str, Any] = {}


class IdempotencyStore:
    """Durable execution claims plus compatibility access to legacy cached results.

    Live effects use reserve/complete, never get/set. Claims are atomically bound
    to a canonical payload before dispatch. Expired leases become uncertain, not
    available: a crashed sender may already have placed an order or broadcast.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._conn: Optional[sqlite3.Connection] = None

    @staticmethod
    def _payload_hash(payload: Dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def lookup(self, key: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Read an existing payload-bound claim without reserving or changing it.

        This precedes mutable execution gates: reporting an old effect is not a
        new execution. Missing databases stay missing; acquisition is reserve's job.
        """
        k = (key or "").strip()
        if not k:
            return None
        path = Path(self._db_path())
        if not path.is_file():
            return None
        digest = self._payload_hash(payload)
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "idempotency" in tables and conn.execute("SELECT 1 FROM idempotency WHERE key = ?", (k,)).fetchone():
                raise IdempotencyError("idempotency_legacy_record", "This key predates payload binding; reconcile its prior result before using a new key.")
            if "execution_attempts" not in tables:
                return None
            row = conn.execute(
                "SELECT payload_hash, state, lease_until, client_id, result_json, evidence_json FROM execution_attempts WHERE key = ?",
                (k,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        if row[0] != digest:
            raise IdempotencyError("idempotency_conflict", "Idempotency key is already bound to a different execution payload.")
        state = "uncertain" if row[1] == "pending" and row[2] <= time.time() else row[1]
        return {
            "acquired": False,
            "state": state,
            "owner": None,
            "client_order_id": row[3],
            "result": json.loads(row[4]) if row[4] else None,
            "evidence": json.loads(row[5]) if row[5] else {},
        }

    def reserve(self, key: str, payload: Dict[str, Any], *, lease_seconds: float = 120) -> Dict[str, Any]:
        k = (key or "").strip()
        if not k or len(k) > 256:
            raise IdempotencyError("idempotency_key_required", "Live execution requires an idempotency key of 1 to 256 characters.")
        if self._db_path() == ":memory:":
            raise IdempotencyError("idempotency_persistence_required", "Live execution claims require a persistent SQLite database.")
        digest = self._payload_hash(payload)
        now = time.time()
        owner = uuid.uuid4().hex
        client_id = "rt" + hashlib.sha256((k + ":" + digest).encode()).hexdigest()[:30]
        conn = self._get_conn()
        with self._lock:
            try:
                conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT 1 FROM idempotency WHERE key = ?", (k,)).fetchone()
                if old:
                    raise IdempotencyError("idempotency_legacy_record", "This key predates payload binding; reconcile its prior result before using a new key.")
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO execution_attempts(key, payload_hash, state, owner, lease_until, client_id) VALUES (?, ?, 'pending', ?, ?, ?)",
                    (k, digest, owner, now + max(1.0, float(lease_seconds)), client_id),
                )
                acquired = cursor.rowcount == 1
                row = conn.execute(
                    "SELECT payload_hash, state, owner, lease_until, client_id, result_json, evidence_json FROM execution_attempts WHERE key = ?",
                    (k,),
                ).fetchone()
                if row[0] != digest:
                    raise IdempotencyError("idempotency_conflict", "Idempotency key is already bound to a different execution payload.")
                state = row[1]
                if not acquired and state == "pending" and row[3] <= now:
                    state = "uncertain"
                    conn.execute("UPDATE execution_attempts SET state = 'uncertain' WHERE key = ?", (k,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "acquired": acquired,
            "state": state,
            "owner": row[2] if acquired else None,
            "client_order_id": row[4],
            "result": json.loads(row[5]) if row[5] else None,
            "evidence": json.loads(row[6]) if row[6] else {},
        }

    def record_evidence(self, key: str, owner: str, evidence: Dict[str, Any]) -> None:
        """Persist remote operation identity before the operation can escape."""
        encoded = json.dumps(evidence, sort_keys=True, allow_nan=False)
        conn = self._get_conn()
        with self._lock, conn:
            changed = conn.execute(
                "UPDATE execution_attempts SET evidence_json = ? WHERE key = ? AND owner = ? AND state = 'pending'",
                (encoded, key.strip(), owner),
            ).rowcount
            if changed != 1:
                raise IdempotencyError("idempotency_claim_lost", "Execution evidence cannot be recorded by this owner.")

    def complete(self, key: str, owner: str, result: Dict[str, Any]) -> None:
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        conn = self._get_conn()
        with self._lock, conn:
            changed = conn.execute(
                "UPDATE execution_attempts SET state = 'completed', result_json = ? WHERE key = ? AND owner = ? AND state IN ('pending', 'uncertain')",
                (encoded, key.strip(), owner),
            ).rowcount
            if changed != 1:
                raise IdempotencyError("idempotency_claim_lost", "Execution claim cannot be completed by this owner.")

    def mark_uncertain(self, key: str, owner: str) -> None:
        conn = self._get_conn()
        with self._lock, conn:
            conn.execute("UPDATE execution_attempts SET state = 'uncertain' WHERE key = ? AND owner = ? AND state = 'pending'", (key.strip(), owner))

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
                self._conn.execute("PRAGMA busy_timeout=5000;")
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
                self._conn.execute(
                    """CREATE TABLE IF NOT EXISTS execution_attempts(
                        key TEXT PRIMARY KEY,
                        payload_hash TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN ('pending', 'completed', 'uncertain')),
                        owner TEXT NOT NULL,
                        lease_until REAL NOT NULL,
                        client_id TEXT NOT NULL,
                        result_json TEXT,
                        evidence_json TEXT
                    )"""
                )
                self._conn.commit()
            return self._conn
