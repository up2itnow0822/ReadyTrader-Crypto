"""
Isolated execution of agent-supplied strategy code.

Threat model
------------
`strategy_code` arrives from an LLM agent. The agent reads untrusted text (news, social
feeds), so the code must be treated as attacker-controlled. The previous in-process
sandbox placed the whole `pandas` and `ta` modules (and RestrictedPython's
`utility_builtins`, which include `string`) in the strategy's globals, which made
`pd.read_csv(".env")`, `pd.read_pickle(url)` and `str.format` attribute walks reachable.

Layers (outermost first)
------------------------
1. Static pre-check in the parent: size cap, and an AST walk that rejects dunder/underscore
   names, `format`/`format_map` attribute access, and any import other than `math`.
2. A child process: empty environment (no API keys to find), empty temporary working
   directory, POSIX rlimits (CPU, address space, open files, file size 0, no core), and a
   wall-clock timeout enforced by the parent. The child reads its own limits back before
   running any strategy code and refuses to run if they were not applied (fail closed).
   File size 0 blocks writing file CONTENTS (EFBIG); it does not stop the creation of empty
   files, which can only land in the throwaway working directory that is deleted afterwards.
   On non-POSIX platforms there are no rlimits: the timeout, empty environment and layers
   1 and 3 still apply.
3. RestrictedPython inside the child, with its own `safer_getattr` and guarded
   iteration/unpacking/writes. The strategy's globals contain NO modules other than `math`.
   Candles reach the strategy as plain floats.

What this is not
----------------
It is not a filesystem jail: the child runs as the same OS user. Layers 1 and 3 remove every
known route to file or network I/O, and layer 2 means an escape finds no secrets in the
environment, cannot write file contents, and cannot spin or allocate without bound.
Operators who need a hard boundary should run the server in a container with a read-only
filesystem and no secrets on disk.

Contract
--------
Strategy code defines `on_candle(price, rsi, state) -> "buy" | "sell" | "hold"` and may
define a top-level `PARAMS` dict. `state` is a fresh dict per series.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import signal

# subprocess is the isolation boundary itself: fixed argv, no shell (see run_strategy).
import subprocess  # nosec B404
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

MAX_SOURCE_CHARS = 20_000
MAX_SERIES = 2_000
MAX_POINTS_PER_SERIES = 20_000
MAX_TOTAL_POINTS = 2_000_000  # across all series: bounds the request the parent builds and the reply budget
DEFAULT_TIMEOUT_S = 10.0
PER_SERIES_TIMEOUT_S = 0.25
MAX_TIMEOUT_S = 120.0
ADDRESS_SPACE_BYTES = 1024 * 1024 * 1024
MAX_OPEN_FILES = 32
ALLOWED_IMPORTS = frozenset({"math"})
FORBIDDEN_ATTRS = frozenset({"format", "format_map"})
VALID_ACTIONS = frozenset({"buy", "sell", "hold"})
MAX_MESSAGE_CHARS = 500
MAX_PARAMS_CHARS = 16_384
# Reply budget: fixed overhead + params + a few bytes per requested action. Anything larger is not a reply
# this protocol can produce, so the parent stops reading and kills the child instead of buffering it.
REPLY_OVERHEAD_BYTES = 64 * 1024
REPLY_BYTES_PER_POINT = 12

Point = Tuple[float, Optional[float]]


class StrategyError(Exception):
    """Raised for every way a strategy can be rejected or fail. `kind` is stable API."""

    KINDS = ("too_large", "forbidden", "compile", "runtime", "timeout", "resource", "protocol")

    def __init__(self, kind: str, message: str, *, series_idx: int | None = None, row_idx: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.series_idx = series_idx
        self.row_idx = row_idx

    def __str__(self) -> str:
        return self.message


@dataclass
class StrategyResult:
    actions: List[List[Optional[str]]]
    params: Dict[str, Any] = field(default_factory=dict)


def validate_source(source: str) -> None:
    """Static rejection in the parent. Raises StrategyError('too_large'|'compile'|'forbidden')."""
    if not isinstance(source, str) or not source.strip():
        raise StrategyError("compile", "Strategy code is empty")
    if len(source) > MAX_SOURCE_CHARS:
        raise StrategyError("too_large", f"Strategy code exceeds {MAX_SOURCE_CHARS} characters")
    try:
        tree = ast.parse(source, filename="<strategy>", mode="exec")
        nodes = list(ast.walk(tree))
    except SyntaxError as e:
        raise StrategyError("compile", f"Strategy Compilation Error: {e.msg} (line {e.lineno})") from None
    except (RecursionError, MemoryError, ValueError, OverflowError):
        # ast.parse runs in THIS process: pathological nesting must not take the server down with it.
        raise StrategyError("compile", "Strategy Compilation Error: code is too deeply nested or malformed to analyse") from None

    def private(name: object) -> bool:
        return isinstance(name, str) and name.startswith("_")

    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    raise StrategyError("forbidden", f"Importing '{alias.name}' is forbidden.")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") not in ALLOWED_IMPORTS or node.level:
                raise StrategyError("forbidden", f"Importing '{node.module}' is forbidden.")
        elif isinstance(node, ast.Attribute):
            if private(node.attr):
                raise StrategyError("forbidden", f"Access to private attribute '{node.attr}' is forbidden")
            if node.attr in FORBIDDEN_ATTRS:
                raise StrategyError("forbidden", f"Use of '.{node.attr}' is forbidden in strategy code")

        # Every other place an identifier can appear: variable names, function/class names (so no
        # `def __eq__`), argument and keyword names, import aliases, `except ... as`, global/nonlocal,
        # and match-pattern captures.
        for field_name in ("id", "name", "arg", "asname", "rest"):
            value = getattr(node, field_name, None)
            if private(value):
                raise StrategyError("forbidden", f"Use of private name '{value}' is forbidden")
        for list_field in ("names", "kwd_attrs"):
            for value in getattr(node, list_field, None) or ():
                if private(value):
                    raise StrategyError("forbidden", f"Use of private name '{value}' is forbidden")


# The first part of the child program: everything that must happen before any untrusted input is
# acted on. Kept separate so the sandbox's own probes run under exactly these conditions too.
#
# The limits are applied HERE, by the child itself, after exec. They used to be applied in a
# `preexec_fn`, i.e. in the forked child before exec - which runs Python (and an `import resource`)
# in an interval where only async-signal-safe work is allowed. In a multithreaded host such as the
# FastAPI server, a lock held by another thread at fork time can deadlock the child there; because
# `Popen()` does not return until the child execs, the parent's wall-clock timeout would never start
# and the calling worker would hang indefinitely. Session isolation now comes from
# `start_new_session=True`, which the standard library performs safely.
_CHILD_PREAMBLE = r"""
import json, math, os, sys

def _reply(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()
    os._exit(0)  # not sys.exit: strategy code must not be able to intercept or imitate the exit

def _fail(kind, message, series_idx=None, row_idx=None):
    _reply({"ok": False, "kind": kind, "message": str(message)[:MAX_MESSAGE],
            "series_idx": series_idx, "row_idx": row_idx})

req = json.loads(sys.stdin.read())
MAX_MESSAGE, MAX_PARAMS = int(req["max_message"]), int(req["max_params"])

# Apply, then INDEPENDENTLY verify. Applying and trusting would make a silently-failed setrlimit an
# unprotected run; the verification pass is what makes this fail closed.
_apply = req.get("apply_limits") or {}
_expect = req.get("expect_limits") or {}
if _apply or _expect:
    try:
        import resource
        for lim_name, want in _apply.items():
            which = getattr(resource, lim_name)
            try:
                _soft, hard = resource.getrlimit(which)
                value = want if hard == resource.RLIM_INFINITY else min(want, hard)
                resource.setrlimit(which, (value, value))
            except (ValueError, OSError):
                pass  # the verification pass below decides whether this was fatal
        for lim_name, want in _expect.items():
            soft, _hard = resource.getrlimit(getattr(resource, lim_name))
            if soft == resource.RLIM_INFINITY or soft > want:
                _fail("resource", "sandbox limit %s was not applied (soft=%s, expected<=%s); refusing to run" % (lim_name, soft, want))
    except SystemExit:
        raise
    except Exception as e:
        _fail("resource", "sandbox limits could not be verified: %s" % (e,))
"""

# The rest of the child program: only reached once the limits above are in force.
_CHILD_BODY = r"""
try:
    from RestrictedPython import compile_restricted, safe_builtins
    from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
    from RestrictedPython.Guards import (full_write_guard, guarded_iter_unpack_sequence,
                                         guarded_unpack_sequence, safer_getattr)
except Exception as e:  # pragma: no cover - environment problem, not strategy problem
    _fail("resource", "sandbox runtime unavailable: %s" % (e,))

source, series = req["source"], req["series"]

def _import(name, *args, **kwargs):
    if name == "math":
        return math
    raise ImportError("Importing '%s' is forbidden." % (name,))

def _getitem(obj, key):
    if isinstance(key, str) and key.startswith("_"):
        raise KeyError("Access to private keys is forbidden")
    return default_guarded_getitem(obj, key)

def _inplacevar(op, x, y):
    ops = {"+=": lambda a, b: a + b, "-=": lambda a, b: a - b, "*=": lambda a, b: a * b,
           "/=": lambda a, b: a / b, "//=": lambda a, b: a // b, "%=": lambda a, b: a % b,
           "**=": lambda a, b: a ** b}
    if op not in ops:
        raise SyntaxError("In-place operator %s is not allowed" % (op,))
    return ops[op](x, y)

builtins = dict(safe_builtins)
builtins["__import__"] = _import
for name in ("min", "max", "sum", "any", "all", "enumerate", "dict", "list", "map", "filter"):
    builtins.setdefault(name, __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name))

scope = {
    "__builtins__": builtins,
    "__name__": "strategy",
    "__metaclass__": type,
    "_getattr_": safer_getattr,
    "_getitem_": _getitem,
    "_getiter_": default_guarded_getiter,
    "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
    "_unpack_sequence_": guarded_unpack_sequence,
    "_write_": full_write_guard,
    "_inplacevar_": _inplacevar,
    "math": math,
}

def _describe(e):
    # Bounded BEFORE formatting: the exception text is attacker-controlled and may be enormous.
    try:
        text = str(e)[:MAX_MESSAGE]
    except BaseException:
        text = "<unprintable>"
    return "%s: %s" % (type(e).__name__, text)

try:
    code = compile_restricted(source, "<strategy>", "exec")
    exec(code, scope, scope)
except SyntaxError as e:
    _fail("compile", "Strategy Compilation Error: %s" % (str(e)[:MAX_MESSAGE],))
except ImportError as e:
    _fail("forbidden", str(e))
except BaseException as e:  # SystemExit / KeyboardInterrupt included: nothing the strategy raises may end the child
    _fail("compile", "Strategy Compilation Error: " + _describe(e))

on_candle = scope.get("on_candle")
if not callable(on_candle):
    _fail("compile", "Strategy code must define 'def on_candle(price, rsi, state):'")

params = scope.get("PARAMS")
try:
    blob = json.dumps(params) if isinstance(params, dict) else "{}"
    params = json.loads(blob) if len(blob) <= MAX_PARAMS else {}
except BaseException:
    params = {}

out = []
for s_idx, points in enumerate(series):
    state, actions = {}, []
    for r_idx, (price, rsi) in enumerate(points):
        if rsi is None:
            actions.append(None)
            continue
        try:
            action = on_candle(price, rsi, state)
        except BaseException as e:
            _fail("runtime", _describe(e), s_idx, r_idx)
        # `is`/type check first: `action in (...)` would call an attacker-defined __eq__.
        actions.append(action if type(action) is str and action in ("buy", "sell", "hold") else "hold")
    out.append(actions)

_reply({"ok": True, "actions": out, "params": params})
"""

_CHILD_SOURCE = _CHILD_PREAMBLE + _CHILD_BODY


def _child_limits(cpu_seconds: int) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    (limits the child applies to itself, limits it must observe before running strategy code).

    Identical in production. They are separate so a test can hand the child an empty `apply` with a
    full `expect` and prove it refuses to run rather than running unprotected.
    """
    spec = {
        "RLIMIT_CPU": int(cpu_seconds),
        "RLIMIT_AS": ADDRESS_SPACE_BYTES,
        "RLIMIT_NOFILE": MAX_OPEN_FILES,
        "RLIMIT_FSIZE": 0,
        "RLIMIT_CORE": 0,
    }
    return dict(spec), dict(spec)


def _child_env() -> Dict[str, str]:
    """Nothing from the parent. SYSTEMROOT is required for Python to start on Windows."""
    env: Dict[str, str] = {}
    if os.name == "nt" and "SYSTEMROOT" in os.environ:  # pragma: no cover
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def _coerce_series(series: Sequence[Sequence[Point]]) -> List[List[List[Optional[float]]]]:
    if len(series) > MAX_SERIES:
        raise StrategyError("too_large", f"Too many series ({len(series)} > {MAX_SERIES})")
    if sum(len(points) for points in series) > MAX_TOTAL_POINTS:
        raise StrategyError("too_large", f"Too many candles in one run (limit {MAX_TOTAL_POINTS})")
    out: List[List[List[Optional[float]]]] = []
    for points in series:
        if len(points) > MAX_POINTS_PER_SERIES:
            raise StrategyError("too_large", f"Series too long ({len(points)} > {MAX_POINTS_PER_SERIES})")
        clean: List[List[Optional[float]]] = []
        for price, rsi in points:
            p = float(price)
            r: Optional[float] = None
            if rsi is not None:
                r = float(rsi)
                if r != r:  # NaN
                    r = None
            clean.append([p, r])
        out.append(clean)
    total = sum(len(points) for points in out)
    if total > MAX_TOTAL_POINTS:
        raise StrategyError("too_large", f"Too many candles in one run ({total} > {MAX_TOTAL_POINTS})")
    return out


def _small_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**9 else None


def _run_child(data: bytes, workdir: str, timeout_s: float, reply_cap: int, kwargs: Dict[str, Any]) -> Tuple[Optional[int], bytes, str]:
    """
    Run the child with a BOUNDED read of its stdout. Returns (returncode, stdout, verdict) where verdict
    is "ok" | "timeout" | "too_big". The child is limited by rlimits; this keeps the PARENT bounded too:
    subprocess.run(capture_output=True) would buffer whatever the strategy manages to emit.
    stderr is discarded - nothing on it is trustworthy and nothing on it is needed.
    """
    # argv is constant (interpreter + the fixed child program). The untrusted strategy source
    # travels as JSON on stdin and never reaches argv or a shell.
    proc = subprocess.Popen(  # nosec B603
        [sys.executable, "-I", "-c", _CHILD_SOURCE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=workdir,
        env=_child_env(),
        **kwargs,
    )
    chunks: List[bytes] = []
    state = {"size": 0, "too_big": False}

    def feed() -> None:
        try:
            if proc.stdin is not None:
                proc.stdin.write(data)
                proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def drain() -> None:
        if proc.stdout is None:
            return
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                return
            state["size"] += len(chunk)
            if state["size"] > reply_cap:
                state["too_big"] = True
                return
            chunks.append(chunk)

    feeder = threading.Thread(target=feed, daemon=True)
    drainer = threading.Thread(target=drain, daemon=True)
    feeder.start()
    drainer.start()
    drainer.join(timeout_s)

    verdict = "ok"
    if state["too_big"]:
        verdict = "too_big"
    elif drainer.is_alive():
        verdict = "timeout"
    if verdict != "ok":
        _kill(proc)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill(proc)
        proc.wait(timeout=5)
    drainer.join(2)
    feeder.join(2)
    for stream in (proc.stdin, proc.stdout):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass
    return proc.returncode, b"".join(chunks), verdict


def _kill(proc: "subprocess.Popen[bytes]") -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)  # start_new_session=True: the child leads its own group
        else:  # pragma: no cover
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def run_strategy(
    source: str,
    series: Sequence[Sequence[Point]],
    *,
    timeout_s: float | None = None,
) -> StrategyResult:
    """
    Run `on_candle` over each series in an isolated child process.

    `series` is a list of series; each series is a list of `(price, rsi)` with `rsi=None`
    (or NaN) for warm-up rows, which yield a `None` action. Returns actions aligned 1:1.
    Raises StrategyError; never returns partial results.
    """
    validate_source(source)
    payload_series = _coerce_series(series)

    if timeout_s is None:
        timeout_s = DEFAULT_TIMEOUT_S + PER_SERIES_TIMEOUT_S * len(payload_series)
    timeout_s = max(1.0, min(float(timeout_s), MAX_TIMEOUT_S))

    request: Dict[str, Any] = {"source": source, "series": payload_series, "max_message": MAX_MESSAGE_CHARS, "max_params": MAX_PARAMS_CHARS}
    kwargs: Dict[str, Any] = {}
    if os.name == "posix":
        cpu_seconds = int(timeout_s) + 1
        # No preexec_fn: nothing of ours runs between fork and exec (see _CHILD_PREAMBLE).
        kwargs["start_new_session"] = True
        request["apply_limits"], request["expect_limits"] = _child_limits(cpu_seconds)
    total_points = sum(len(points) for points in payload_series)
    reply_cap = REPLY_OVERHEAD_BYTES + MAX_PARAMS_CHARS * 6 + REPLY_BYTES_PER_POINT * total_points

    workdir = tempfile.mkdtemp(prefix="rt-strategy-")
    try:
        returncode, stdout, verdict = _run_child(json.dumps(request).encode("utf-8"), workdir, timeout_s, reply_cap, kwargs)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if verdict == "timeout":
        raise StrategyError("timeout", f"Strategy exceeded the {timeout_s:.0f}s time limit and was stopped")
    if verdict == "too_big":
        raise StrategyError("resource", "Strategy produced more output than any valid reply can contain and was stopped")
    if returncode != 0:
        # Never echo anything the child wrote: on this path its output is attacker-influenced.
        if returncode is not None and returncode < 0:
            raise StrategyError("resource", f"Strategy was stopped by the sandbox (signal {-returncode}: CPU or memory limit)")
        raise StrategyError("resource", f"Strategy process ended abnormally (exit code {returncode})")

    try:
        reply = json.loads(stdout.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        raise StrategyError("protocol", "Sandbox returned an unreadable reply") from None

    if not reply.get("ok"):
        kind = reply.get("kind") if reply.get("kind") in StrategyError.KINDS else "runtime"
        message = str(reply.get("message") or "strategy failed")[: MAX_MESSAGE_CHARS + 100]
        raise StrategyError(kind, message, series_idx=_small_int(reply.get("series_idx")), row_idx=_small_int(reply.get("row_idx")))

    actions = reply.get("actions")
    if not isinstance(actions, list) or len(actions) != len(payload_series):
        raise StrategyError("protocol", "Sandbox reply does not match the request")
    for got, sent in zip(actions, payload_series):
        if not isinstance(got, list) or len(got) != len(sent):
            raise StrategyError("protocol", "Sandbox reply does not match the request")
        for a in got:
            if a is not None and a not in VALID_ACTIONS:
                raise StrategyError("protocol", "Sandbox returned an invalid action")

    params = reply.get("params")
    return StrategyResult(actions=actions, params=params if isinstance(params, dict) else {})
