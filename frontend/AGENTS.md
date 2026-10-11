# frontend/AGENTS.md

## Purpose

Next.js 16 (App Router, React 19, TypeScript strict) operator dashboard for the
ReadyTrader-Crypto FastAPI backend (`../api_server.py`). Lets a human operator see
health/mode, review and approve/reject pending trade proposals, and read trade
history — nothing here executes trades on its own; every mutating action requires an
explicit human click through a confirm dialog.

## Ownership

- Owner: same as repo root (Agent Economy, LLC / Bill Wilson, @up2itnow0822).
- This file is a DOX child of the root `AGENTS.md`. It does not weaken any root rule
  (paper-first, fail-closed, secrets-never-committed); it adds frontend-specific
  contracts the root doc doesn't cover.
- Scope: everything under `frontend/`. Does not own `../api_server.py` or any other
  Python source — this app only ever talks to the API over HTTP/WS, and treats it as
  an external contract it cannot change.

## Local Contracts

These are load-bearing invariants. Do not "simplify" past them without updating this
file and the tests that enforce them.

- **Runtime, not build-time, config.** `src/app/layout.tsx` is `export const dynamic =
  "force-dynamic"` and resolves `{ apiUrl, wsUrl }` per request from `process.env`
  (`READYTRADER_API_URL` / `READYTRADER_WS_URL`, falling back to
  `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL`, falling back to
  `http://<request host>:8000` derived from `headers()`). Nothing reads
  `NEXT_PUBLIC_*` at build time and nothing bakes an API URL into the JS bundle — the
  same built image/`.next` output must work against any API origin the container is
  started with. `next.config.ts` must not gain an `env:` block that reintroduces
  build-time baking.
- **One fetch wrapper.** `src/lib/api.ts`'s `apiFetch<T>()` is the only place that
  calls `fetch()` against the API. It applies an 8s timeout and normalizes every
  failure (HTTP error body, non-JSON body, network error, timeout) into
  `{status, code, message, suggestion}`. It clears the auth token on any 401. Do not
  add a second fetch helper or call `fetch()` directly from a component/hook.
- **`HealthProvider` is the sole source of mode/reachability.** Nothing else polls
  `/api/health` or independently decides "paper" vs "live" vs "unknown". A consumer
  that is not sure whether the API is reachable must render the `"unknown"` state —
  **`"unknown" must never be styled as either `paper` or `live`**; this is a safety
  property (an operator must never be shown a false "safe, it's paper mode" reading
  when the app cannot actually confirm the mode). `HealthPill`'s
  `health-pill--unknown|paper|live` classes and the tests in
  `src/providers/HealthProvider.test.tsx` encode this rule.
- **Token storage.** The JWT lives in memory + `sessionStorage`
  (`readytrader.auth.token`, in `src/lib/authStore.ts`) only. Never `localStorage`,
  never a cookie, never logged.
- **No `dangerouslySetInnerHTML`, ever.** Proposal `rationale` and other
  operator-supplied/agent-supplied text are untrusted and are rendered as plain text
  (React's default escaping) — see `ApprovalCard.tsx` and its XSS test. If a future
  feature seems to need HTML rendering, it needs a sanitizer and a new decision here
  first, not an inline exception.
- **Service worker does not cache.** `public/sw.js` and
  `src/hooks/useServiceWorker.ts` only unregister old registrations and clear old
  caches. Do not turn this back into an offline/asset cache without re-deciding the
  staleness-vs-safety tradeoff for a trading dashboard (a cached "trading halted"
  reading is worse than no reading).
- **Approvals are two-step and double-submit-safe.** `useApprovals.act()` guards with
  a synchronous `useRef` set *before* any `await`, so a double-click or double-Enter
  sends exactly one HTTP request. The confirm dialog restates the trade sentence and
  the current mode (PAPER / LIVE — real funds / MODE UNKNOWN) before the operator can
  confirm.
- **An acted-on approval stays visible for a grace period.** A proposal stops being
  "pending" server-side the instant it is confirmed, whether that confirmation went on
  to execute, fail, or get rejected — the very next poll would otherwise erase its card
  (and the fill/error message on it) before the operator can read it. `useApprovals`
  keeps it rendered for `OUTCOME_GRACE_MS` (6s) after that. Do not remove this in favor
  of "just refresh immediately" without re-solving that problem some other way.
- **Auth fails closed when the API has never answered.** `HealthProvider.loaded` means
  "a request finished", not "it succeeded" — `AuthProvider` deliberately does not wait
  for a *successful* health check to decide the auth phase. If it did, a first load
  during an API outage would be stuck on "Connecting to the API…" forever, with no way
  to even reach the sign-in form once the API came back. Unknown `authRequired` is
  treated the same as `true`.
- **No `eslint-disable`, `@ts-ignore`, or `any` to silence a lint/type error.** Fix
  the underlying code. (E.g. the `react-hooks/set-state-in-effect` violations in this
  codebase were fixed by deriving state, using `useSyncExternalStore`, or moving the
  `setState` into the render body per React's "adjust state during render" pattern —
  not by disabling the rule.)
- **`frontend/e2e/api_harness.py` is test tooling, not product code.** It seeds
  proposals directly into the API process's own `ExecutionStore` (a real deployment
  gets them from the MCP server through a shared `EXECUTION_SESSION_ID`). Seeded payloads
  carry `"paper_mode": true`, because the API executes a proposal only in the mode it was
  made in. It serves fixed market prices (`FIXED_PRICES`) instead of calling an exchange,
  because paper orders fill at the market price and pass the Risk Guardian. It must never
  be imported by, or shipped with, the actual Next.js app, and its `/__test/seed` route
  only exists on that harness process, never on a real deployment.

## Work Guidance

- Keep `src/lib/`, `src/providers/`, `src/hooks/`, `src/components/` boundaries: pure
  helpers in `lib/`, app-wide state in `providers/`, data-fetching+polling logic in
  `hooks/`, presentation in `components/`. Pages under `src/app/**/page.tsx` should
  stay thin (metadata + render a view component).
- Every formatter in `src/lib/format.ts` must be null-safe and return `"—"`
  (`MISSING_VALUE`) rather than throwing or producing `NaN`/`undefined` text — the API
  can and does omit/partially-fill fields.
- New dependencies: keep `npm audit` at zero findings, including
  `devDependencies`. Check before adding, not after. `npm audit --omit=dev` is
  not the gate — it hides eslint/tsc toolchain advisories.
- Ports for local dev/e2e must come from the 3100-3199 (Next) / 8100-8199 (API)
  ranges used by this repo's other worktrees, to avoid colliding with a sibling
  worktree's servers.
- In Playwright specs, don't assert on a bare `page.getByRole("alert")`: Next's App
  Router always renders its own `role="alert"` route announcer (usually empty), and
  the approvals panel and the health banner can each have their own alert live at the
  same time. Use a `data-testid` (`login-error`, `health-banner`, `health-pill`,
  `ws-status`) or scope the query to a specific element instead.

## Verification

Run from `frontend/`:

- `npm run lint` — ESLint (`eslint-config-next`), must be clean (no errors, no
  warnings suppressed).
- `npm run typecheck` — `tsc --noEmit`, must be clean.
- `npm audit` — must report 0 vulnerabilities, including `devDependencies`.
  Enforced on every PR by `make security` / `.github/workflows/ci.yml`.
- `npm test` — Vitest unit/integration tests (formatters, `apiFetch`, `AuthProvider`,
  `HealthProvider`, `ApprovalCard`, `useApprovals`, `useWebSocket`).
- `npm run build` — production Next.js build (also required before `npm run e2e`,
  which runs it automatically via the `pree2e` script).
- `npm run e2e` — Playwright end-to-end tests. Starts two local `webServer`s per
  `playwright.config.ts`: the Python test harness (`e2e/api_harness.py`, paper mode,
  temp DB, run with the repo's `.venv/bin/python` when it exists, else `python3`;
  `PW_PYTHON_PATH` overrides) and `next start`. The HTML report goes to
  `frontend/playwright-report/` (`PW_REPORT_DIR` overrides). Deliberately `workers: 1` / `fullyParallel: false` —
  one spec kills and restarts the harness process to test reconnection, and several
  specs assert exact request counts.
- Backend contract check after any API-facing change: from the repo root,
  `pytest tests/test_api_health_contract.py` (the one new backend test file this
  worktree is allowed to add) plus the full suite to confirm no regression.

## Child DOX Index

(none — no child AGENTS.md files under `frontend/` yet)
