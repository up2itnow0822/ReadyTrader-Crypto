import { getToken, clearToken } from "./authStore";
import { getRuntimeConfig, normalizeOrigin } from "./config";

const REQUEST_TIMEOUT_MS = 8000;

export interface NormalizedApiError {
  status: number;
  code: string;
  message: string;
  suggestion?: string;
}

export class ApiError extends Error implements NormalizedApiError {
  status: number;
  code: string;
  suggestion?: string;

  constructor(fields: NormalizedApiError) {
    super(fields.message);
    this.name = "ApiError";
    this.status = fields.status;
    this.code = fields.code;
    this.suggestion = fields.suggestion;
  }
}

interface ErrorEnvelope {
  ok: false;
  error: { code?: string; message?: string; suggestion?: string };
}

function looksLikeErrorEnvelope(body: unknown): body is ErrorEnvelope {
  return (
    typeof body === "object" &&
    body !== null &&
    (body as Record<string, unknown>).ok === false &&
    typeof (body as Record<string, unknown>).error === "object" &&
    (body as Record<string, unknown>).error !== null
  );
}

function detailToMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  try {
    return JSON.stringify(detail);
  } catch {
    return "Request failed";
  }
}

async function parseErrorBody(response: Response): Promise<NormalizedApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (looksLikeErrorEnvelope(body)) {
    return {
      status: response.status,
      code: body.error.code || `HTTP_${response.status}`,
      message: body.error.message || response.statusText || "Request failed",
      suggestion: body.error.suggestion,
    };
  }

  if (body && typeof body === "object" && "detail" in (body as Record<string, unknown>)) {
    return {
      status: response.status,
      code: `HTTP_${response.status}`,
      message: detailToMessage((body as Record<string, unknown>).detail),
    };
  }

  return {
    status: response.status,
    code: `HTTP_${response.status}`,
    message: response.statusText || "Request failed",
  };
}

export interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip attaching the Authorization header (used for /api/auth/login itself). */
  skipAuth?: boolean;
  timeoutMs?: number;
}

/**
 * The one function in this app that calls `fetch` against the ReadyTrader API.
 *
 * - Adds `Authorization: Bearer <token>` from the auth store, unless `skipAuth`.
 * - Aborts after 8s and reports that as a normal (non-throwing-uncaught) ApiError.
 * - Normalizes both the `{ok:false,error:{...}}` tool envelope and FastAPI's
 *   `{detail: ...}` shape into `{status, code, message, suggestion}`.
 * - On a 401, clears the stored token so `AuthProvider` flips the app to the login
 *   screen; the caller still receives the thrown ApiError so it can stop spinners.
 */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { apiUrl } = getRuntimeConfig();
  const url = `${normalizeOrigin(apiUrl)}${path}`;

  const headers = new Headers(options.headers);
  if (options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!options.skipAuth) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (err) {
    clearTimeout(timeout);
    const aborted = err instanceof DOMException && err.name === "AbortError";
    throw new ApiError({
      status: 0,
      code: aborted ? "REQUEST_TIMEOUT" : "NETWORK_ERROR",
      message: aborted
        ? `Request to ${apiUrl} timed out after ${(options.timeoutMs ?? REQUEST_TIMEOUT_MS) / 1000}s.`
        : `Could not reach ${apiUrl}. Check the API URL and that the server is running.`,
    });
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    const normalized = await parseErrorBody(response);
    if (response.status === 401) {
      clearToken("expired");
    }
    throw new ApiError(normalized);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  try {
    return (await response.json()) as T;
  } catch {
    return undefined as T;
  }
}
