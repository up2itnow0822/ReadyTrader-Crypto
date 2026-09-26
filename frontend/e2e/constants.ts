/** Ports/credentials shared between playwright.config.ts and the spec files. */
import fs from "node:fs";
import path from "node:path";

export const API_PORT = 8171;
export const NEXT_PORT = 3171;

export const API_URL = `http://127.0.0.1:${API_PORT}`;
export const WS_URL = `ws://127.0.0.1:${API_PORT}/ws`;
export const BASE_URL = `http://127.0.0.1:${NEXT_PORT}`;

// Must match frontend/e2e/api_harness.py's TEST_ADMIN_USERNAME/TEST_ADMIN_PASSWORD exactly.
export const TEST_ADMIN_USERNAME = "admin";
export const TEST_ADMIN_PASSWORD = "test-admin-password-123";

// The Python that runs e2e/api_harness.py (playwright.config.ts's webServer and apiControl.ts's
// restart share it): the repo's .venv (README quickstart) when it exists, else python3 on PATH.
// PW_PYTHON_PATH overrides either.
const REPO_VENV_PYTHON = path.join(__dirname, "..", "..", ".venv", "bin", "python");
export const HARNESS_PYTHON = process.env.PW_PYTHON_PATH || (fs.existsSync(REPO_VENV_PYTHON) ? REPO_VENV_PYTHON : "python3");
