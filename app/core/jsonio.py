"""Shared JSON envelope encoder for MCP/API tool responses.

Every tool module in `app/tools/` returns one of two envelope shapes:

    {"ok": true, "data": {...}}
    {"ok": false, "error": {"code": ..., "message": ..., "data": {...}}}

This module is the single place that knows how to serialize those
envelopes, including how to make the common "not natively JSON
serializable" value types (pandas/numpy scalars & arrays, Decimal,
datetime/date, enums, sets, NaN/NaT) safe to encode. Unknown object
types are never silently stringified: they raise ``TypeError`` so a
missing conversion is caught instead of shipping mangled data.

pandas and numpy are optional/lazy imports: this module must not
hard-fail to import when either dependency is absent from the
environment.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional


def _optional_pandas() -> Any:
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return None
    return pd


def _optional_numpy() -> Any:
    try:
        import numpy as np  # type: ignore
    except Exception:
        return None
    return np


def _is_nan_float(value: float) -> bool:
    """True for NaN and for +/-infinity: neither is valid JSON (RFC 8259), and `json.dumps` would emit
    the bare tokens `NaN` / `Infinity`, which strict parsers (browsers' JSON.parse included) reject."""
    try:
        return not math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _sanitize(obj: Any) -> Any:
    """Recursively convert `obj` into a structure of JSON-native types.

    Raises TypeError for any object type this function does not know
    how to convert; it never falls back to `str(obj)`.
    """
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj

    if isinstance(obj, float):
        # Covers numpy.float64 too (it subclasses the built-in float).
        return None if _is_nan_float(obj) else obj

    if isinstance(obj, dict):
        return {key: _sanitize(value) for key, value in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_sanitize(value) for value in obj]

    if isinstance(obj, set):
        return [_sanitize(value) for value in sorted(obj)]

    if isinstance(obj, Enum):
        return _sanitize(obj.value)

    if isinstance(obj, Decimal):
        return float(obj)

    # pandas.Timestamp (and pandas.NaT) both subclass datetime.datetime, so
    # this must be checked before the generic datetime/date branch below —
    # otherwise NaT.isoformat() would yield the literal string "NaT".
    pd = _optional_pandas()
    if pd is not None:
        if obj is pd.NaT:
            return None
        if isinstance(obj, pd.Timestamp):
            return None if pd.isna(obj) else obj.isoformat()

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    np = _optional_numpy()
    if np is not None:
        if isinstance(obj, np.ndarray):
            return _sanitize(obj.tolist())
        if isinstance(obj, np.generic):
            return _sanitize(obj.item())

    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _default(obj: Any) -> Any:
    """`json.dumps(default=...)` fallback.

    In practice `_sanitize` already converts the whole payload before
    it reaches the encoder, so this is only exercised if some exotic
    object slips through unconverted; it applies the same rules
    (raising TypeError, never str()-ing, for anything unrecognized).
    """
    return _sanitize(obj)


def json_dumps(payload: Any) -> str:
    """Serialize an already-shaped envelope (or any payload) with the
    project-wide JSON-safety conversions and formatting."""
    return json.dumps(_sanitize(payload), indent=2, sort_keys=True, default=_default, allow_nan=False)


def json_ok(data: Optional[Dict[str, Any]] = None) -> str:
    payload = {"ok": True, "data": data or {}}
    return json_dumps(payload)


def json_err(code: str, message: str, data: Optional[Dict[str, Any]] = None) -> str:
    payload = {"ok": False, "error": {"code": code, "message": message, "data": data or {}}}
    return json_dumps(payload)
