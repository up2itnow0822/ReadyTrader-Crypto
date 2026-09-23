import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

import { API_PORT, API_URL, BASE_URL, NEXT_PORT } from "./e2e/constants";

const PYTHON = process.env.PW_PYTHON_PATH || "/home/claude/work/venv-rt/bin/python3";
const REPORT_DIR = process.env.PW_REPORT_DIR || "/home/claude/work/discovery/m4/playwright-report";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // One worker: the resilience spec kills/restarts the shared API harness process, and
  // several tests count network requests -- both need a single, deterministic timeline.
  workers: 1,
  retries: 0,
  reporter: [["line"], ["html", { outputFolder: REPORT_DIR, open: "never" }]],
  timeout: 30_000,
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.PW_EXECUTABLE_PATH ? { executablePath: process.env.PW_EXECUTABLE_PATH } : {},
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `${PYTHON} ${path.join(__dirname, "e2e", "api_harness.py")} --port ${API_PORT} --auth`,
      url: `${API_URL}/api/health`,
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      // The build must already exist (see package.json's "pree2e" script) -- this only
      // starts the already-built production server, matching how it runs in Docker.
      command: `npm run start -- -p ${NEXT_PORT}`,
      url: BASE_URL,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        READYTRADER_API_URL: API_URL,
        READYTRADER_WS_URL: `ws://127.0.0.1:${API_PORT}/ws`,
      },
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
