# Strategy Sandbox

How agent-supplied strategy code is executed for `run_backtest_simulation` and the stress lab
(`stress_test_engine.run_synthetic_stress_test`, a local Python function — see
[Not an MCP tool](#not-an-mcp-tool) below). Source of truth: `strategy_sandbox.py`'s module
docstring and constants; this page restates it for operators, without inventing numbers.

## Threat model

`strategy_code` arrives from an LLM agent, which itself reads untrusted text (news, social
feeds). The code must be treated as attacker-controlled. An earlier in-process sandbox placed
the whole `pandas` and `ta` modules (and RestrictedPython's `utility_builtins`, which include
`string`) in the strategy's globals, which made things like `pd.read_csv(".env")`,
`pd.read_pickle(url)`, and `str.format` attribute walks reachable. `strategy_sandbox.py`
replaces that with isolation in a child process.

## Contract

Strategy code must define:

```python
def on_candle(price, rsi, state):
    # return "buy", "sell", or "hold"
    ...
```

and may optionally define a top-level `PARAMS` dict. `state` is a plain dict, fresh per series,
that persists across candles within that series. `price` and `rsi` arrive as plain floats (or
`rsi` is `None` on warm-up rows before enough history exists) — the strategy never sees a
DataFrame, `pandas`, or `ta`. `run_backtest_simulation` and the stress lab pre-compute RSI
outside the sandbox and hand the strategy only numbers.

## What is rejected

Two layers reject code before/while it runs, each with a stable `kind` on the resulting error:

- **Static pre-check in the parent** (`kind: "too_large"` or `"compile"` or `"forbidden"`):
  - source longer than 20,000 characters
  - a syntax error
  - any `import` other than `math`
  - any dunder or underscore-prefixed name (`_foo`, `__init__`, etc.)
  - `.format` / `.format_map` attribute access
- **RestrictedPython inside the child** (`kind: "compile"` or `"runtime"`): its own
  `safer_getattr` and guarded iteration/unpacking/writes reject anything the static check
  missed once the code actually runs. The strategy's globals contain no modules other than
  `math`.

Other failure kinds a caller may see: `"timeout"` (exceeded its time limit), `"resource"`
(hit a CPU/memory/output-size limit and was stopped), and `"protocol"` (the sandbox's internal
child/parent reply could not be parsed — always a sandbox bug, not a strategy bug).

## Isolation layers

1. The static pre-check above, run in the parent process.
1. **A child process**: empty environment (no API keys to find), an empty temporary working
   directory that is deleted afterwards, and — on POSIX — rlimits: CPU time, address space
   (1 GiB), open files (32), file size (0, which blocks writing file *contents* but not
   creating empty files in the throwaway directory), and no core dumps. The child reads its own
   limits back before running any strategy code and refuses to run if they were not applied
   (fails closed). A wall-clock timeout is enforced by the parent regardless of platform. On
   non-POSIX platforms there are no rlimits — the timeout, empty environment, and layers 1 and
   3 still apply.
1. RestrictedPython inside the child, as described above.

## What this is not

It is **not a filesystem jail** — the child runs as the same OS user. Layers 1 and 3 remove
every known route to file or network I/O, and layer 2 means an escape finds no secrets in the
environment, cannot write file contents, and cannot spin or allocate without bound. Operators
who need a hard boundary should run the server in a container with a read-only filesystem and
no secrets on disk.

## Limits (from `strategy_sandbox.py`)

| Limit                             | Value                                  |
| :-------------------------------- | :------------------------------------- |
| Max strategy source length        | 20,000 characters                      |
| Default timeout                   | 10s + 0.25s per series, capped at 120s |
| Address-space limit (POSIX child) | 1 GiB                                  |
| Open-file limit (POSIX child)     | 32                                     |
| Allowed imports                   | `math` only                            |
| Forbidden attribute access        | `.format`, `.format_map`               |
| Valid `on_candle` return values   | `"buy"`, `"sell"`, `"hold"`            |

## Not an MCP tool

`run_backtest_simulation` is the only agent-facing (MCP) entry point to this sandbox.
`stress_test_engine.run_synthetic_stress_test` also runs strategies through the same sandbox,
but it is a plain Python function used by `examples/stress_test_demo.py` — it has never been
registered as an MCP tool, and there is no agent-callable stress-test tool today.

## See also

- `docs/ERRORS.md` — the JSON shape `run_backtest_simulation` returns for a rejected strategy
- `docs/ARCHITECTURE.md` — where the sandbox sits in the execution/research flow
