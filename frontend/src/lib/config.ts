/**
 * Runtime configuration store.
 *
 * The API/WS origins are resolved on the server, per request, in `src/app/layout.tsx`
 * (a `force-dynamic` server component that reads `process.env` at request time) and
 * handed down to `<AppProviders>` as a prop. This module is the single place that
 * holds that value on the client so plain functions (not just React components) can
 * read it -- `apiFetch` and the WebSocket hook are not hooks themselves and need a
 * synchronous way to find the current origin.
 *
 * Nothing here bakes a URL in at build time: the values only ever come from the prop
 * `AppProviders` receives on a given page load.
 */

export interface RuntimeConfig {
  apiUrl: string;
  wsUrl: string;
}

const FALLBACK_CONFIG: RuntimeConfig = {
  apiUrl: "http://localhost:8000",
  wsUrl: "ws://localhost:8000/ws",
};

let current: RuntimeConfig = FALLBACK_CONFIG;
let initialized = false;

export function setRuntimeConfig(config: RuntimeConfig): void {
  current = config;
  initialized = true;
}

export function getRuntimeConfig(): RuntimeConfig {
  return current;
}

export function isRuntimeConfigInitialized(): boolean {
  return initialized;
}

/** Strip a trailing slash so callers can safely do `${apiUrl}/api/...`. */
export function normalizeOrigin(url: string): string {
  return url.replace(/\/+$/, "");
}
