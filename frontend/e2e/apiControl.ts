import { execSync, spawn, type ChildProcess } from "node:child_process";
import path from "node:path";

const PYTHON = process.env.PW_PYTHON_PATH || "/home/claude/work/venv-rt/bin/python3";
const HARNESS_PATH = path.join(__dirname, "api_harness.py");

/** Used only by the resilience spec, which kills and restarts the shared API harness. */
export function killListenerOnPort(port: number): void {
  try {
    const out = execSync(`lsof -ti :${port} -sTCP:LISTEN`, { stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
    for (const pid of out.split("\n").filter(Boolean)) {
      try {
        process.kill(Number(pid), "SIGKILL");
      } catch {
        // already gone
      }
    }
  } catch {
    // lsof exits non-zero when nothing is listening on the port -- nothing to kill.
  }
}

export function spawnApiHarness(port: number, auth: boolean): ChildProcess {
  const args = [HARNESS_PATH, "--port", String(port)];
  if (auth) args.push("--auth");
  return spawn(PYTHON, args, { stdio: "ignore" });
}

export async function waitForHealth(baseUrl: string, timeoutMs = 20000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseUrl}/api/health`);
      if (res.ok) return;
    } catch (err) {
      lastError = err;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`API at ${baseUrl} did not become healthy within ${timeoutMs}ms: ${String(lastError)}`);
}
