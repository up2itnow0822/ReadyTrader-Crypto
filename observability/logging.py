from __future__ import annotations

import contextvars
import json
import os
import time
import uuid
from typing import Any, Dict, Optional

_CURRENT_CTX: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "readytrader_log_ctx",
    default=None,
)


def get_current_context() -> Optional[Dict[str, Any]]:
    return _CURRENT_CTX.get()


def set_current_context(ctx: Optional[Dict[str, Any]]) -> None:
    _CURRENT_CTX.set(ctx)


_LEVELS = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40}


def _level_value(level: str) -> int:
    return _LEVELS.get(str(level or "").strip().lower(), 20)


def _min_level_value() -> int:
    # Prefer explicit READYTRADER_LOG_LEVEL, fallback to LOG_LEVEL.
    raw = (os.getenv("READYTRADER_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "info").strip().lower()
    return _level_value(raw)


_SENSITIVE_KEYWORDS = ("secret", "password", "token", "private", "mnemonic", "api_key", "apikey", "seed")


def redact(value: Any) -> Any:
    """
    Best-effort redaction for logs. This is defensive: ReadyTrader-Crypto should avoid logging secrets entirely.
    """
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k).lower()
            if any(x in ks for x in _SENSITIVE_KEYWORDS):
                out[k] = "***REDACTED***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(x) for x in value]
    if isinstance(value, tuple):
        return [redact(x) for x in value]
    return value


def build_log_context(*, tool: str, request_id: str | None = None, flow_id: str | None = None) -> Dict[str, Any]:
    """
    Build a per-invocation context object for structured logs.

    We keep this intentionally minimal to avoid leaking sensitive data.
    """
    ctx = {
        "tool": tool,
        "request_id": str(request_id or uuid.uuid4()),
        "ts_ms": int(time.time() * 1000),
        "service": os.getenv("READYTRADER_SERVICE_NAME", "readytrader"),
    }
    if flow_id:
        ctx["flow_id"] = str(flow_id)
    return ctx


def log_event(event: str, *, ctx: Dict[str, Any], data: Optional[Dict[str, Any]] = None, level: str = "info") -> None:
    """
    Emit a single-line JSON log event to stdout.
    """
    if _level_value(level) < _min_level_value():
        return
    payload = dict(ctx)
    # The time of THIS event: a context built once (the API server's) would otherwise stamp every
    # line with the moment the process started.
    payload["ts_ms"] = int(time.time() * 1000)
    payload["level"] = str(level).upper()
    payload["event"] = event
    if data:
        payload["data"] = redact(data)
    print(json.dumps(payload, sort_keys=True))
