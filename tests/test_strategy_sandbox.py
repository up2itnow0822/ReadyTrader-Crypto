"""
Security contract for agent-supplied strategy code (strategy_sandbox.py).

Every attack vector is its own test and must be rejected for a stated REASON. A test that
only asserts "some error happened" passes on a typo, which is how the previous
`test_file_access_prevention` stayed green while `pd.read_csv` could read any file.

Layers are tested independently: the static pre-check alone, the in-child RestrictedPython
layer alone (pre-check disabled), and the process boundary alone (environment, limits).
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd
import pytest

import strategy_sandbox as sb
from backtest_engine import BacktestEngine
from strategy_sandbox import StrategyError, run_strategy
from stress_test_engine import run_synthetic_stress_test

SERIES = [[(100.0 + i, None if i < 3 else float(20 + i * 2)) for i in range(40)]]
HOLD = 'def on_candle(price, rsi, state):\n    return "hold"\n'
SECRET = "CANARY_SECRET=do-not-leak-7f3a"
posix_only = pytest.mark.skipif(os.name != "posix", reason="rlimits are POSIX-only")


def _rejected(source: str, **kwargs) -> StrategyError:
    with pytest.raises(StrategyError) as exc:
        run_strategy(source, SERIES, **kwargs)
    return exc.value


# --------------------------------------------------------------------------- legitimate use


def test_legit_strategy_returns_aligned_actions_and_params():
    src = (
        'PARAMS = {"lo": 30, "hi": 70}\n'
        "def on_candle(price, rsi, state):\n"
        '    if rsi < PARAMS["lo"]:\n        return "buy"\n'
        '    if rsi > PARAMS["hi"]:\n        return "sell"\n'
        '    return "hold"\n'
    )
    out = run_strategy(src, SERIES)
    actions = out.actions[0]
    assert len(actions) == len(SERIES[0])
    assert actions[:3] == [None, None, None], "warm-up rows (rsi=None) carry no action"
    assert set(actions[3:]) <= {"buy", "sell", "hold"}
    assert "buy" in actions and "sell" in actions
    assert out.params == {"lo": 30, "hi": 70}


def test_state_persists_within_a_series_and_resets_between_series():
    src = 'def on_candle(price, rsi, state):\n    state["n"] = state.get("n", 0) + 1\n    return "buy" if state["n"] == 2 else "hold"\n'
    out = run_strategy(src, [SERIES[0], SERIES[0]])
    for actions in out.actions:
        live = [a for a in actions if a is not None]
        assert live[1] == "buy" and live.count("buy") == 1, "second live candle of EACH series buys exactly once"


def test_math_is_available_and_unknown_actions_become_hold():
    src = 'import math\ndef on_candle(price, rsi, state):\n    return "buy" if math.sqrt(price) > 10.2 else "banana"\n'
    live = [a for a in run_strategy(src, SERIES).actions[0] if a is not None]
    assert "buy" in live and "banana" not in live and "hold" in live


# --------------------------------------------------------------------------- static pre-check (layer 1)


@pytest.mark.parametrize(
    "name,source,needle",
    [
        ("import os", "import os\n" + HOLD, "Importing 'os' is forbidden"),
        ("from os import path", "from os import path\n" + HOLD, "is forbidden"),
        ("relative import", "from . import x\n" + HOLD, "is forbidden"),
        ("import subprocess as math", "import subprocess as math\n" + HOLD, "Importing 'subprocess' is forbidden"),
        ("__import__", 'x = __import__("os")\n' + HOLD, "private name '__import__'"),
        ("str.format walk", 'def on_candle(p, r, s):\n    return "{0.__class__}".format(s)\n', "'.format' is forbidden"),
        ("format_map walk", 'def on_candle(p, r, s):\n    return "{a.__class__}".format_map({"a": s})\n', "'.format_map' is forbidden"),
        ("f-string dunder walk", 'def on_candle(p, r, s):\n    return f"{s.__class__.__mro__}"\n', "private attribute"),
        ("dunder attribute", "def on_candle(p, r, s):\n    return s.__class__\n", "private attribute '__class__'"),
        ("single underscore attribute", "def on_candle(p, r, s):\n    return s._private\n", "private attribute '_private'"),
        ("private global", "def on_candle(p, r, s):\n    global _getattr_\n    return 1\n", "private name"),
    ],
)
def test_static_precheck_rejects(name, source, needle):
    err = _rejected(source)
    assert err.kind == "forbidden", f"{name}: expected kind=forbidden, got {err.kind}: {err.message}"
    assert needle in err.message, f"{name}: {err.message}"


def test_oversized_source_is_rejected_before_any_process_starts(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("a child process was started for an oversized strategy")

    monkeypatch.setattr(sb.subprocess, "Popen", boom)
    err = _rejected(HOLD + "#" * (sb.MAX_SOURCE_CHARS + 1))
    assert err.kind == "too_large"


def test_syntax_error_is_a_compile_error_with_line_number():
    err = _rejected("def on_candle(p, r, s)\n    return 1\n")
    assert err.kind == "compile" and "line 1" in err.message


def test_missing_on_candle_is_a_compile_error():
    err = _rejected("x = 1\n")
    assert err.kind == "compile" and "on_candle" in err.message


# --------------------------------------------------------------------------- no capabilities in scope (layer 3)


@pytest.mark.parametrize("module", ["pd", "ta", "string", "random", "os", "sys", "np", "json"])
def test_no_module_is_reachable_from_strategy_globals(module):
    """The route that actually leaked: `pd.read_csv(path)`. Modules are absent, not filtered."""
    err = _rejected(f"x = {module}\n" + HOLD)
    assert err.kind == "compile"
    assert "NameError" in err.message and f"'{module}'" in err.message


@pytest.mark.parametrize(
    "builtin", ["open", "eval", "exec", "compile", "getattr", "globals", "locals", "vars", "input", "breakpoint", "type", "memoryview", "object", "super"]
)
def test_dangerous_builtins_are_not_defined(builtin):
    err = _rejected(f"def on_candle(p, r, s):\n    x = {builtin}\n    return 'hold'\n")
    assert err.kind in {"runtime", "compile"}, "RestrictedPython refuses some names (e.g. breakpoint) at compile time, which is earlier and stronger"
    assert builtin in err.message, err.message
    if err.kind == "runtime":
        assert "NameError" in err.message
        assert err.row_idx == 3, "first live candle is row 3; row index must be reported"


# Reviewed 2026-09-19 against RestrictedPython 8.1, and again against 8.4 (which adds `Ellipsis`: an inert
# constant - not callable, attribute walks on it are refused by both layers): none of these grants file, network, import or
# introspection capability (setattr/delattr are the guarded versions and refuse every write; see the
# next test). If an upgrade changes this set the test fails ON PURPOSE: review the new names before
# updating the pin.
REVIEWED_BUILTINS = frozenset(
    "Ellipsis False None True __build_class__ _getattr_ abs all any bool bytes callable chr complex delattr dict divmod "
    "enumerate filter float hash hex id int isinstance issubclass len list map max min oct ord pow range repr "
    "round setattr slice sorted str sum tuple zip".split()
)


def test_exposed_builtin_surface_is_exactly_the_reviewed_set():
    from RestrictedPython import safe_builtins

    extras = {"min", "max", "sum", "any", "all", "enumerate", "dict", "list", "map", "filter"}
    exposed = {n for n in set(safe_builtins) | extras if not (isinstance(safe_builtins.get(n), type) and issubclass(safe_builtins[n], BaseException))}
    assert exposed == REVIEWED_BUILTINS, f"added: {sorted(exposed - REVIEWED_BUILTINS)} removed: {sorted(REVIEWED_BUILTINS - exposed)}"


@pytest.mark.parametrize(
    "name,source",
    [
        ("setattr on a module", 'import math\ndef on_candle(p, r, s):\n    setattr(math, "sqrt", 1)\n    return "hold"\n'),
        ("setattr on own function", 'def f():\n    return 1\ndef on_candle(p, r, s):\n    setattr(f, "x", 1)\n    return "hold"\n'),
        ("delattr on a module", 'import math\ndef on_candle(p, r, s):\n    delattr(math, "sqrt")\n    return "hold"\n'),
        ("attribute assignment", 'import math\ndef on_candle(p, r, s):\n    math.sqrt = 1\n    return "hold"\n'),
        ("own class instance", 'class C:\n    pass\ndef on_candle(p, r, s):\n    c = C()\n    c.x = 1\n    return "hold"\n'),
    ],
)
def test_attribute_writes_are_refused(name, source):
    """`setattr`/`delattr` ARE defined (RestrictedPython's guarded versions); what matters is that they cannot write."""
    err = _rejected(source)
    assert err.kind == "runtime", f"{name}: {err.kind}: {err.message}"
    assert "attribute-less object" in err.message, f"{name}: {err.message}"


@pytest.mark.parametrize(
    "name,source",
    [
        ("str.format walk", 'def on_candle(p, r, s):\n    return "{0.__class__}".format(s)\n'),
        ("dunder attribute", "def on_candle(p, r, s):\n    return s.__class__\n"),
        ("import os", "import os\n" + HOLD),
        ("__import__", 'x = __import__("os")\n' + HOLD),
    ],
)
def test_inner_layer_holds_with_the_static_precheck_disabled(monkeypatch, name, source):
    """Defence in depth must be real: with layer 1 switched off, RestrictedPython alone still refuses."""
    monkeypatch.setattr(sb, "validate_source", lambda source: None)
    err = _rejected(source)
    assert err.kind in {"compile", "forbidden", "runtime"}, f"{name}: {err.kind}: {err.message}"
    assert "<class" not in err.message, f"{name}: attribute walk leaked a class repr: {err.message}"


# --------------------------------------------------------------------------- process boundary (layer 2)


def test_infinite_loop_is_stopped_by_the_wall_clock():
    t0 = time.time()
    err = _rejected("def on_candle(p, r, s):\n    while True:\n        pass\n", timeout_s=2.0)
    assert err.kind == "timeout"
    assert time.time() - t0 < 6.0, "the parent must not wait past the limit"


@posix_only
def test_memory_bomb_is_stopped():
    err = _rejected("def on_candle(p, r, s):\n    x = [0] * (10 ** 10)\n    return 'hold'\n", timeout_s=10.0)
    assert err.kind in {"runtime", "resource"}
    assert "MemoryError" in err.message or "limit" in err.message


def _probe_child(monkeypatch, body: str) -> dict:
    """
    Run `body` as the child program through the REAL argv/env/cwd/rlimit configuration.

    The probe is prefixed with the production preamble, which is where the child now applies and
    verifies its own rlimits - so a probe observes exactly the conditions strategy code does.
    """
    probe = sb._CHILD_PREAMBLE + "\n" + body + '\n_reply({"ok": False, "kind": "runtime", "message": json.dumps(report)})\n'
    monkeypatch.setattr(sb, "_CHILD_SOURCE", probe)
    return json.loads(_rejected(HOLD).message)


def test_child_environment_contains_nothing_from_the_parent(monkeypatch):
    monkeypatch.setenv("CEX_API_SECRET", "parent-secret-value")
    monkeypatch.setenv("API_JWT_SECRET", "another-parent-secret")
    report = _probe_child(monkeypatch, 'report = {"env": dict(os.environ), "cwd": os.listdir(".")}')
    assert "CEX_API_SECRET" not in report["env"] and "API_JWT_SECRET" not in report["env"]
    assert "parent-secret-value" not in json.dumps(report)
    inherited = set(report["env"]) & set(os.environ) - {"LC_CTYPE", "SYSTEMROOT"}
    assert not inherited, f"child inherited parent variables: {sorted(inherited)}"
    assert report["cwd"] == [], "child starts in an empty throwaway directory"


@posix_only
def test_child_cannot_write_file_contents(monkeypatch):
    body = (
        "report = {}\n"
        "try:\n"
        '    with open("out.bin", "wb") as f:\n'
        '        f.write(b"x" * 4096); f.flush(); os.fsync(f.fileno())\n'
        '    report["write"] = "wrote %d bytes" % os.path.getsize("out.bin")\n'
        "except OSError as e:\n"
        '    report["write"] = "blocked errno=%s" % e.errno\n'
    )
    report = _probe_child(monkeypatch, body)
    assert report["write"].startswith("blocked"), report


@posix_only
def test_child_refuses_to_run_when_limits_were_not_applied(monkeypatch):
    """Fail closed: a limit that silently failed to apply must not mean an unprotected run."""
    real = sb._child_limits  # capture before patching, or the lambda recurses into itself
    monkeypatch.setattr(sb, "_child_limits", lambda cpu_seconds: ({}, real(cpu_seconds)[1]))
    err = _rejected(HOLD)
    assert err.kind == "resource" and "was not applied" in err.message


@posix_only
def test_nothing_of_ours_runs_between_fork_and_exec():
    """
    preexec_fn runs Python in the forked child before exec, where only async-signal-safe work is
    allowed; in a multithreaded host it can deadlock there, and Popen() does not return until exec,
    so the parent's timeout would never start. The child applies its own limits after exec instead.
    """
    import inspect
    import io
    import tokenize

    src = inspect.getsource(sb)
    # Strip comments: this file *discusses* preexec_fn at length, and a guard that matched prose
    # would fail on its own explanation. Strings are kept - start_new_session is a kwargs key.
    code = "".join(" " if tok.type == tokenize.COMMENT else tok.string for tok in tokenize.generate_tokens(io.StringIO(src).readline))
    assert "preexec_fn" not in code, "preexec_fn must not be used"
    assert "setsid" not in code, "session isolation must not be done by hand in the child"
    assert "start_new_session" in code, "session isolation must come from start_new_session"


@posix_only
def test_the_child_applies_the_limits_it_then_verifies(monkeypatch):
    """The limits really are in force inside the child, not merely requested by the parent."""
    import resource

    report = _probe_child(
        monkeypatch,
        "import resource\n"
        "report = {name: resource.getrlimit(getattr(resource, name))[0]\n"
        '          for name in ("RLIMIT_AS", "RLIMIT_NOFILE", "RLIMIT_FSIZE", "RLIMIT_CORE")}\n',
    )
    assert report["RLIMIT_FSIZE"] == 0 and report["RLIMIT_CORE"] == 0
    assert 0 < report["RLIMIT_AS"] <= sb.ADDRESS_SPACE_BYTES
    assert 0 < report["RLIMIT_NOFILE"] <= sb.MAX_OPEN_FILES
    assert resource.getrlimit(resource.RLIMIT_FSIZE)[0] != 0, "the PARENT must be unaffected"


def test_garbage_reply_from_the_child_is_a_protocol_error(monkeypatch):
    monkeypatch.setattr(sb, "_CHILD_SOURCE", 'import sys\nsys.stdin.read()\nsys.stdout.write("not json")\n')
    assert _rejected(HOLD).kind == "protocol"


def test_forged_actions_from_the_child_are_rejected(monkeypatch):
    forged = (
        "import json, sys\nreq = json.loads(sys.stdin.read())\n"
        'sys.stdout.write(json.dumps({"ok": True, "actions": [["rm -rf"] * len(req["series"][0])], "params": {}}))\n'
    )
    monkeypatch.setattr(sb, "_CHILD_SOURCE", forged)
    assert _rejected(HOLD).kind == "protocol"


# --------------------------------------------------------------------------- the PARENT stays bounded too
# Found by an independent red-team pass on the first version of this sandbox: the child was limited,
# but the parent buffered whatever the strategy could emit, and let parser/BaseException cases through.


def test_a_huge_exception_message_is_capped_before_it_reaches_the_parent():
    err = _rejected('def on_candle(p, r, s):\n    raise ValueError("Q" * 20_000_000)\n')
    assert err.kind == "runtime" and len(err.message) <= sb.MAX_MESSAGE_CHARS + 100
    assert err.message.startswith("ValueError: QQQ")


def test_oversized_params_are_dropped_not_returned():
    out = run_strategy('PARAMS = {"k": "P" * 20_000_000}\n' + HOLD, SERIES)
    assert out.params == {}
    assert run_strategy('PARAMS = {"k": "small"}\n' + HOLD, SERIES).params == {"k": "small"}


@pytest.mark.parametrize(
    "name,source,kind",
    [
        ("SystemExit in on_candle", 'def on_candle(p, r, s):\n    raise SystemExit("VERIFIED BY SANDBOX: all checks passed")\n', "runtime"),
        ("SystemExit at import", 'raise SystemExit("VERIFIED BY SANDBOX")\n' + HOLD, "compile"),
        ("KeyboardInterrupt", 'def on_candle(p, r, s):\n    raise KeyboardInterrupt("x")\n', "runtime"),
        ("GeneratorExit", "def on_candle(p, r, s):\n    raise GeneratorExit()\n", "runtime"),
    ],
)
def test_base_exceptions_are_the_strategys_error_never_the_sandboxs_voice(name, source, kind):
    """The strategy may not end the child, and may not choose the text of a sandbox-level (`resource`) error."""
    err = _rejected(source)
    assert err.kind == kind, f"{name}: {err.kind}: {err.message}"
    assert "Strategy process" not in err.message and "sandbox" not in err.message.lower().replace("verified by sandbox", "")
    assert any(f"{exc}: " in err.message or err.message.endswith(f"{exc}: ") for exc in ("SystemExit", "KeyboardInterrupt", "GeneratorExit")), (
        "labelled as the exception it is"
    )


@pytest.mark.parametrize(
    "name,expr",
    [("unary chain", "-" * 3000 + "1"), ("binop chain", "1+" * 6000 + "1"), ("attribute chain", "a" + ".b" * 6000), ("nested lists", "[" * 500 + "]" * 500)],
)
def test_pathological_nesting_is_a_compile_error_not_a_parent_crash(name, expr):
    err = _rejected(f"x = {expr}\n" + HOLD)
    assert err.kind in {"compile", "forbidden"}, f"{name}: {err.kind}"


@pytest.mark.parametrize(
    "name,source",
    [
        ("dunder method", "class E(str):\n    def __eq__(self, other):\n        return True\n" + HOLD),
        ("dunder class", "class __X:\n    pass\n" + HOLD),
        ("private function", "def _helper():\n    return 1\n" + HOLD),
        ("private argument", "def f(_x):\n    return 1\n" + HOLD),
        ("dunder keyword", "def f(**k):\n    return 1\ndef on_candle(p, r, s):\n    f(__class__=1)\n    return 'hold'\n"),
        ("except as private", "try:\n    x = 1\nexcept Exception as _e:\n    pass\n" + HOLD),
        ("import alias", "import math as _m\n" + HOLD),
        ("match capture", "def on_candle(p, r, s):\n    match s:\n        case {**_rest}:\n            return 'hold'\n    return 'hold'\n"),
    ],
)
def test_private_names_are_rejected_everywhere_an_identifier_can_appear(name, source):
    err = _rejected(source)
    assert err.kind == "forbidden" and "private" in err.message, f"{name}: {err.kind}: {err.message}"


def test_an_action_object_cannot_run_attacker_code_in_the_comparison():
    out = run_strategy('class A(str):\n    pass\ndef on_candle(p, r, s):\n    return A("buy")\n', SERIES)
    assert {a for a in out.actions[0] if a is not None} == {"hold"}, "only exact str actions count"


def test_a_flood_on_stdout_is_cut_off_and_the_child_killed(monkeypatch):
    flood = 'import sys\nsys.stdin.read()\nwhile True:\n    sys.stdout.write("x" * 65536)\n'
    monkeypatch.setattr(sb, "_CHILD_SOURCE", flood)
    t0 = time.time()
    err = _rejected(HOLD, timeout_s=20.0)
    assert err.kind == "resource" and "more output" in err.message
    assert time.time() - t0 < 10.0, "cut off by size, long before the timeout"


def test_stderr_is_never_echoed(monkeypatch):
    monkeypatch.setattr(sb, "_CHILD_SOURCE", 'import sys\nsys.stdin.read()\nsys.stderr.write("TRUST ME " * 1000)\nsys.exit(3)\n')
    err = _rejected(HOLD)
    assert err.kind == "resource" and "TRUST ME" not in err.message and "exit code 3" in err.message


def test_total_request_size_is_bounded_before_any_process_starts(monkeypatch):
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("a child process was started for an oversized request")

    monkeypatch.setattr(sb.subprocess, "Popen", boom)
    monkeypatch.setattr(sb, "MAX_TOTAL_POINTS", 1_000)
    with pytest.raises(StrategyError) as exc:
        run_strategy(HOLD, [[(1.0, 50.0)] * 600, [(1.0, 50.0)] * 600])
    assert exc.value.kind == "too_large"


# --------------------------------------------------------------------------- through both engines


def _candles(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, n))))
    return pd.DataFrame(
        {"timestamp": pd.date_range("2026-01-01", periods=n, freq="h"), "open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1.0}
    )


@pytest.fixture
def engine():
    eng = BacktestEngine.__new__(BacktestEngine)  # no exchange client / network
    eng.fetch_ohlcv = lambda *a, **k: _candles()
    return eng


@pytest.fixture
def canary_file(tmp_path):
    path = tmp_path / "canary.env"
    path.write_text(SECRET + "\n")
    return path


def _read_csv_attack(path) -> str:
    return f'leak = pd.read_csv(r"{path}", header=None)\ndef on_candle(price, rsi, state):\n    raise ValueError("EXFIL:" + str(leak.iloc[0, 0]))\n'


def test_backtest_engine_read_csv_canary_does_not_leak(engine, canary_file):
    """Reproduces the original finding on its own, so the .format guard cannot mask it."""
    result = engine.run(_read_csv_attack(canary_file), "BTC/USDT")
    blob = json.dumps(result)
    assert "do-not-leak" not in blob and "CANARY_SECRET" not in blob
    assert "error" in result and "'pd'" in result["error"], result


def test_stress_engine_read_csv_canary_does_not_leak(canary_file):
    with pytest.raises(StrategyError) as exc:
        run_synthetic_stress_test(strategy_code=_read_csv_attack(canary_file), config={"scenarios": 3, "length": 60})
    assert "do-not-leak" not in exc.value.message and "'pd'" in exc.value.message


@pytest.mark.parametrize(
    "name,source,needle",
    [
        ("format walk", 'def on_candle(p, r, s):\n    raise ValueError("{0.__class__.__mro__}".format(s))\n', "'.format' is forbidden"),
        ("import os", "import os\n" + HOLD, "Importing 'os' is forbidden"),
        ("dunder", "def on_candle(p, r, s):\n    return s.__class__\n", "private attribute"),
    ],
)
def test_both_engines_reject_with_the_reason(engine, name, source, needle):
    result = engine.run(source, "BTC/USDT")
    assert needle in result.get("error", ""), f"backtest/{name}: {result}"
    assert result.get("error_kind") == "forbidden"
    with pytest.raises(StrategyError) as exc:
        run_synthetic_stress_test(strategy_code=source, config={"scenarios": 3, "length": 60})
    assert exc.value.kind == "forbidden" and needle in exc.value.message, f"stress/{name}"


def test_both_engines_survive_an_infinite_loop(engine, monkeypatch):
    monkeypatch.setattr(sb, "DEFAULT_TIMEOUT_S", 1.5)
    monkeypatch.setattr(sb, "PER_SERIES_TIMEOUT_S", 0.0)
    spin = "def on_candle(p, r, s):\n    while True:\n        pass\n"
    t0 = time.time()
    result = engine.run(spin, "BTC/USDT")
    assert result.get("error_kind") == "timeout", result
    with pytest.raises(StrategyError) as exc:
        run_synthetic_stress_test(strategy_code=spin, config={"scenarios": 3, "length": 60})
    assert exc.value.kind == "timeout"
    assert time.time() - t0 < 12.0


def test_backtest_runtime_error_keeps_its_documented_shape(engine):
    result = engine.run("def on_candle(p, r, s):\n    return 1 / 0\n", "BTC/USDT")
    assert result["error"].startswith("Runtime error in strategy at row "), result
    assert "ZeroDivisionError" in result["error"]


def test_a_rejected_strategy_is_refused_before_any_scenario_is_generated(monkeypatch):
    """
    The stress engine batches every scenario into one sandbox run, so run_strategy() is called after
    the generation loop. Source validation must happen BEFORE it: `scenarios` and `length` come from
    the caller and every frame is retained, so `import os` plus a large config would otherwise burn
    CPU and memory before the strategy was ever looked at.
    """
    import synthetic_market

    def boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("a scenario was generated for a strategy that cannot run")

    monkeypatch.setattr(synthetic_market, "generate_synthetic_ohlcv", boom)
    with pytest.raises(StrategyError) as exc:
        run_synthetic_stress_test(strategy_code="import os\n" + HOLD, config={"scenarios": 5_000, "length": 5_000})
    assert exc.value.kind == "forbidden" and "Importing 'os' is forbidden" in exc.value.message
