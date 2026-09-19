"""
Two-step execution proposal store (Phase 6).

This is used when `EXECUTION_APPROVAL_MODE=approve_each`.
Instead of executing immediately, the server returns a proposal:
- `request_id`: lookup key
- `confirm_token`: single-use token (replay protection)
- `expires_at`: TTL deadline (prevents stale approvals)

Phase 1B: Optional SQLite persistence can be enabled for operator visibility.
Safety rules:
- Proposals are invalidated across restarts via a per-process session id (so stale approvals cannot execute).
- Risk consent is NOT persisted (consent remains in-memory only by design).
"""

from __future__ import annotations

import json
import math
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Phase 2: Webhooks for notifications
try:
    from observability.webhooks import WebhookManager
except ImportError:
    WebhookManager = None


class ProposalError(ValueError):
    """
    A proposal could not be confirmed. Subclasses ValueError so existing callers keep working.

    `reason` is stable API: unknown | expired | cancelled | executed | already_confirmed | invalid_token.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


# Fields a human approver may see, per proposal kind. A whitelist on purpose: anything a future
# producer adds to a payload stays hidden until it is reviewed and listed here. The confirm_token is
# never part of a summary.
_SUMMARY_FIELDS: Dict[str, tuple] = {
    "place_cex_order": ("symbol", "side", "amount", "order_type", "price", "exchange", "market_type"),
    "swap_tokens": ("from_token", "to_token", "amount", "chain", "rationale"),
    "transfer_eth": ("to_address", "amount", "chain"),
}
_SUMMARY_TEXT_LIMIT = 280


def summarize_payload(kind: str, payload: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Display-safe subset of a proposal payload (JSON scalars only, long text truncated).

    Non-finite numbers become None. A proposal is stored before policy validation runs, so a
    NaN or inf amount can reach this function; Starlette serializes responses with
    `allow_nan=False`, and one such value would make /api/pending-approvals return 500 for every
    operator - hiding every other valid approval - until that proposal expired.
    """
    out: Dict[str, Any] = {}
    for name in _SUMMARY_FIELDS.get(str(kind), ()):
        value = (payload or {}).get(name)
        if value is None or isinstance(value, bool):
            out[name] = value
        elif isinstance(value, (int, float)):
            number = float(value)
            out[name] = number if math.isfinite(number) else None
        else:
            out[name] = str(value)[:_SUMMARY_TEXT_LIMIT]
    return out


@dataclass
class ExecutionProposal:
    """
    A two-step execution proposal with state machine:

    States:
    - pending: created, not yet confirmed/cancelled/expired
    - confirmed: user approved, ready for execution
    - executed: execution completed (atomic - cannot re-execute)
    - cancelled: user cancelled
    - expired: TTL exceeded without confirmation
    """

    request_id: str
    confirm_token: str
    kind: str
    payload: Dict[str, Any]
    created_at: float
    expires_at: float
    confirmed_at: Optional[float] = None
    cancelled_at: Optional[float] = None
    executed_at: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None
    payload_hash: Optional[str] = None  # SHA256 of payload for idempotency validation

    @property
    def executed(self) -> bool:
        """Check if proposal has been executed."""
        return self.executed_at is not None

    @property
    def status(self) -> str:
        """Get current proposal status."""
        now = time.time()
        if self.executed_at is not None:
            return "executed"
        if self.cancelled_at is not None:
            return "cancelled"
        if self.expires_at <= now:
            return "expired"
        if self.confirmed_at is not None:
            return "confirmed"
        return "pending"


class ExecutionStore:
    """
    In-memory store for two-step execution proposals.
    Replay protection: proposal can be confirmed only once.
    """

    def __init__(self) -> None:
        # Accessed by MCP tool handlers; keep thread-safe (even if most workloads are single-threaded).
        self._lock = threading.Lock()
        self._items: Dict[str, ExecutionProposal] = {}
        self._conn: Optional[sqlite3.Connection] = None
        # Used to invalidate any persisted proposals across restarts.
        self._session_id = secrets.token_hex(8)

    def persistence_enabled(self) -> bool:
        return bool(self._db_path())

    def _db_path(self) -> str:
        default = "data/execution.db"
        p = (os.getenv("READYTRADER_EXECUTION_DB_PATH") or os.getenv("EXECUTION_DB_PATH") or default).strip()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def _get_conn(self) -> Optional[sqlite3.Connection]:
        path = self._db_path()
        if not path:
            return None
        if self._conn is not None:
            return self._conn
        # create lazily
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_proposals(
                request_id TEXT PRIMARY KEY,
                confirm_token TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                confirmed_at REAL,
                cancelled_at REAL,
                executed_at REAL,
                execution_result_json TEXT,
                payload_hash TEXT,
                session_id TEXT NOT NULL
            )
            """
        )
        # Migration: add new columns if they don't exist (for existing databases)
        try:
            self._conn.execute("ALTER TABLE execution_proposals ADD COLUMN executed_at REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            self._conn.execute("ALTER TABLE execution_proposals ADD COLUMN execution_result_json TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE execution_proposals ADD COLUMN payload_hash TEXT")
        except sqlite3.OperationalError:
            pass
        self._conn.commit()
        return self._conn

    def _persist(self, p: ExecutionProposal) -> None:
        """
        Persist a proposal best-effort (only if EXECUTION_DB_PATH is set).
        """
        conn = self._get_conn()
        if conn is None:
            return

        # Compute payload hash for idempotency validation
        import hashlib

        payload_json = json.dumps(p.payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()[:16]

        execution_result_json = json.dumps(p.execution_result) if p.execution_result else None

        conn.execute(
            """
            INSERT INTO execution_proposals(
                request_id, confirm_token, kind, payload_json, created_at, expires_at,
                confirmed_at, cancelled_at, executed_at, execution_result_json, payload_hash, session_id
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
              confirmed_at=excluded.confirmed_at,
              cancelled_at=excluded.cancelled_at,
              executed_at=excluded.executed_at,
              execution_result_json=excluded.execution_result_json
            """,
            (
                p.request_id,
                p.confirm_token,
                p.kind,
                payload_json,
                float(p.created_at),
                float(p.expires_at),
                p.confirmed_at,
                p.cancelled_at,
                p.executed_at,
                execution_result_json,
                payload_hash,
                self._session_id,
            ),
        )
        conn.commit()

    def _load(self, request_id: str) -> Optional[ExecutionProposal]:
        """
        Load a proposal from SQLite if persistence is enabled.

        Only proposals created in the *current process session* are considered valid.
        """
        conn = self._get_conn()
        if conn is None:
            return None
        row = conn.execute(
            """
            SELECT
              request_id,
              confirm_token,
              kind,
              payload_json,
              created_at,
              expires_at,
              confirmed_at,
              cancelled_at,
              executed_at,
              execution_result_json,
              payload_hash,
              session_id
            FROM execution_proposals
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if not row:
            return None
        if row[11] != self._session_id:
            return None
        try:
            payload = json.loads(row[3]) if row[3] else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        try:
            execution_result = json.loads(row[9]) if row[9] else None
        except Exception:
            execution_result = None
        return ExecutionProposal(
            request_id=str(row[0]),
            confirm_token=str(row[1]),
            kind=str(row[2]),
            payload=payload,
            created_at=float(row[4]),
            expires_at=float(row[5]),
            confirmed_at=float(row[6]) if row[6] is not None else None,
            cancelled_at=float(row[7]) if row[7] is not None else None,
            executed_at=float(row[8]) if row[8] is not None else None,
            execution_result=execution_result,
            payload_hash=str(row[10]) if row[10] else None,
        )

    def create(self, *, kind: str, payload: Dict[str, Any], ttl_seconds: int = 120) -> ExecutionProposal:
        with self._lock:
            now = time.time()
            request_id = secrets.token_hex(12)
            confirm_token = secrets.token_hex(16)
            prop = ExecutionProposal(
                request_id=request_id,
                confirm_token=confirm_token,
                kind=kind,
                payload=payload,
                created_at=now,
                expires_at=now + ttl_seconds,
            )
            self._items[request_id] = prop
            self._persist(prop)

            # Phase 2: Notification callback
            if WebhookManager:
                # Best effort only: the proposal is already stored, so a notification problem (or an
                # odd payload) must not surface as "proposal failed" while a live proposal stays pending.
                try:
                    amount = float(payload.get("amount") or 0.0)
                    symbol = str(payload.get("symbol") or payload.get("from_token", "Unknown"))
                    WebhookManager.notify_approval_required(kind=kind, amount=amount, symbol=symbol, request_id=request_id)
                except Exception:
                    pass

            return prop

    def get(self, request_id: str) -> Optional[ExecutionProposal]:
        with self._lock:
            p = self._items.get(request_id)
            if p is not None:
                return p
            p2 = self._load(request_id)
            if p2 is not None:
                self._items[request_id] = p2
            return p2

    def list_pending(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            pending = []
            for p in self._items.values():
                if p.cancelled_at or p.confirmed_at:
                    continue
                if p.expires_at <= now:
                    continue
                pending.append(
                    {
                        "request_id": p.request_id,
                        "kind": p.kind,
                        "created_at": p.created_at,
                        "expires_at": p.expires_at,
                        "summary": summarize_payload(p.kind, p.payload),
                    }
                )
            # Optionally merge persisted proposals (same-session only) that aren't loaded yet.
            conn = self._get_conn()
            if conn is not None:
                rows = conn.execute(
                    """
                    SELECT request_id, kind, created_at, expires_at, payload_json
                    FROM execution_proposals
                    WHERE session_id = ? AND confirmed_at IS NULL AND cancelled_at IS NULL AND expires_at > ?
                    """,
                    (self._session_id, float(now)),
                ).fetchall()
                seen = {p["request_id"] for p in pending}
                for rid, kind, created_at, expires_at, payload_json in rows:
                    if str(rid) in seen:
                        continue
                    try:
                        payload = json.loads(payload_json) if payload_json else {}
                    except Exception:
                        payload = {}
                    pending.append(
                        {
                            "request_id": str(rid),
                            "kind": str(kind),
                            "created_at": float(created_at),
                            "expires_at": float(expires_at),
                            "summary": summarize_payload(str(kind), payload if isinstance(payload, dict) else {}),
                        }
                    )
            return {"pending": pending}

    def token_matches(self, request_id: str, confirm_token: str) -> bool:
        """Constant-time check of a proposal's confirm token. False for unknown proposals. Changes nothing."""
        with self._lock:
            p = self._items.get(request_id) or self._load(request_id)
            if not p or not isinstance(confirm_token, str):
                return False
            return secrets.compare_digest(p.confirm_token, confirm_token)

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            p = self._items.get(request_id) or self._load(request_id)
            if not p:
                return False
            if p.confirmed_at is not None:
                return False
            if p.cancelled_at is not None:
                return False
            p.cancelled_at = time.time()
            self._items[request_id] = p
            self._persist(p)
            return True

    def _confirmable(self, request_id: str) -> ExecutionProposal:
        """State checks shared by both confirm paths. Caller holds the lock."""
        p = self._items.get(request_id) or self._load(request_id)
        if not p:
            raise ProposalError("unknown", "Unknown request_id")
        if p.expires_at <= time.time():
            raise ProposalError("expired", "Proposal expired")
        if p.cancelled_at is not None:
            raise ProposalError("cancelled", "Proposal cancelled")
        if p.executed_at is not None:
            raise ProposalError("executed", "Proposal already executed")
        if p.confirmed_at is not None:
            raise ProposalError("already_confirmed", "Proposal already confirmed")
        return p

    def _mark_confirmed(self, p: ExecutionProposal) -> ExecutionProposal:
        p.confirmed_at = time.time()
        self._items[p.request_id] = p
        self._persist(p)
        return p

    def confirm(self, request_id: str, confirm_token: str) -> ExecutionProposal:
        """Single-use confirmation by the token issued with the proposal."""
        with self._lock:
            p = self._confirmable(request_id)
            if not isinstance(confirm_token, str) or not secrets.compare_digest(p.confirm_token, confirm_token):
                raise ProposalError("invalid_token", "Invalid confirm_token")
            return self._mark_confirmed(p)

    def confirm_as_operator(self, request_id: str, *, operator: str) -> ExecutionProposal:
        """
        Single-use confirmation WITHOUT the confirm token.

        The caller is responsible for having authenticated `operator` as a human approver (the HTTP
        API does this with an admin JWT). Never expose this path to MCP tools: the agent that created a
        proposal must not be able to confirm it. Same state checks and single-use guarantee as confirm().
        """
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError("operator is required")
        with self._lock:
            return self._mark_confirmed(self._confirmable(request_id))

    def mark_executed(self, request_id: str, result: Optional[Dict[str, Any]] = None) -> bool:
        """
        Mark a proposal as executed (atomic - prevents double-execution).

        This must be called after successful execution to prevent the same
        proposal from being executed again.

        Args:
            request_id: The proposal request ID
            result: Optional execution result to store

        Returns:
            True if marked successfully, False if already executed or not found
        """
        with self._lock:
            p = self._items.get(request_id) or self._load(request_id)
            if not p:
                return False
            if p.executed_at is not None:
                return False  # Already executed
            if p.confirmed_at is None:
                return False  # Not confirmed yet
            p.executed_at = time.time()
            p.execution_result = result
            self._items[request_id] = p
            self._persist(p)
            return True

    def is_executed(self, request_id: str) -> bool:
        """Check if a proposal has been executed."""
        with self._lock:
            p = self._items.get(request_id) or self._load(request_id)
            if not p:
                return False
            return p.executed_at is not None
