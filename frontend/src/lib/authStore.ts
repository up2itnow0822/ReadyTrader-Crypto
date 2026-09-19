/**
 * Holds the JWT in memory, mirrored to sessionStorage (never localStorage -- a JWT in
 * localStorage survives tab close and is readable by any script on the origin for as
 * long as the browser profile lives; sessionStorage is cleared when the tab closes).
 *
 * This is a plain module store (not a React context) so `apiFetch` -- a plain async
 * function, not a hook -- can read and clear the token synchronously, including the
 * "on 401, log the user out" rule from anywhere `apiFetch` is called.
 */

const STORAGE_KEY = "readytrader.auth.token";

export type ClearReason = "manual" | "expired";

type Listener = (token: string | null, reason?: ClearReason) => void;

let token: string | null = null;
const listeners = new Set<Listener>();

function readStoredToken(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredToken(value: string | null): void {
  try {
    if (value === null) {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } else {
      window.sessionStorage.setItem(STORAGE_KEY, value);
    }
  } catch {
    // sessionStorage unavailable (private browsing, disabled storage, SSR) -- the
    // in-memory copy still works for the lifetime of this page.
  }
}

let hydrated = false;
function hydrateOnce(): void {
  if (hydrated) return;
  hydrated = true;
  if (typeof window !== "undefined") {
    token = readStoredToken();
  }
}

export function getToken(): string | null {
  hydrateOnce();
  return token;
}

export function setToken(next: string): void {
  hydrateOnce();
  token = next;
  writeStoredToken(next);
  for (const listener of listeners) listener(token, "manual");
}

export function clearToken(reason: ClearReason = "manual"): void {
  hydrateOnce();
  if (token === null) return;
  token = null;
  writeStoredToken(null);
  for (const listener of listeners) listener(token, reason);
}

export function subscribeToken(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Test-only escape hatch so unit tests can reset the module between cases. */
export function __resetAuthStoreForTests(): void {
  token = null;
  hydrated = false;
  listeners.clear();
  writeStoredToken(null);
}
