"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { announce } from "./announce";
import { ApiError, apiFetch } from "./api";
import { getRuntimeConfig } from "./config";

export type WsStatus = "connecting" | "open" | "closed" | "unauthorized";

type MessageListener = (data: unknown) => void;

export interface UseWebSocketResult {
  status: WsStatus;
  subscribe: (listener: MessageListener) => () => void;
}

export const WS_MIN_BACKOFF_MS = 1000;
export const WS_MAX_BACKOFF_MS = 30000;

/**
 * Exchanges the HTTP JWT for a fresh single-use ticket before each connection.
 * The ticket is offered in a subprotocol header, never in the URL; the server only
 * echoes `readytrader`. Anonymous dev connections need no ticket. Retries use
 * exponential backoff + jitter between 1s and 30s. A close with code 1008
 * (the server's "auth rejected" code, see api_server.py's `/ws` handler) moves to
 * `unauthorized` and stops retrying -- the server will keep rejecting until the app
 * has a fresh token, and hammering it in a loop would just be noise.
 */
export function useWebSocket(token: string | null, enabled: boolean): UseWebSocketResult {
  const [internalStatus, setStatus] = useState<WsStatus>("connecting");
  // Derived, not stored: when disabled there is nothing to connect, so "closed" is
  // computed here rather than written from inside the effect below.
  const status: WsStatus = enabled ? internalStatus : "closed";
  const listenersRef = useRef(new Set<MessageListener>());
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const lastAnnouncedRef = useRef<WsStatus | null>(null);

  const subscribe = useCallback((listener: MessageListener) => {
    listenersRef.current.add(listener);
    return () => {
      listenersRef.current.delete(listener);
    };
  }, []);

  useEffect(() => {
    // A generation-local flag prevents an old session's pending ticket request
    // from opening a socket after a token change, disable, or unmount.
    let stopped = false;
    attemptRef.current = 0;

    if (!enabled) {
      return () => {
        stopped = true;
      };
    }

    const scheduleReconnect = () => {
      if (stopped) return;
      const backoff = Math.min(WS_MAX_BACKOFF_MS, WS_MIN_BACKOFF_MS * 2 ** attemptRef.current);
      const jitter = backoff * (0.5 + Math.random() * 0.5);
      attemptRef.current += 1;
      timerRef.current = setTimeout(connect, jitter);
    };

    async function connect() {
      if (stopped) return;
      const { wsUrl } = getRuntimeConfig();
      setStatus("connecting");

      let socket: WebSocket;
      try {
        let protocols: string[] | undefined;
        if (token) {
          const result = await apiFetch<{ ticket: string; expires_in: number }>("/api/auth/ws-ticket", { method: "POST" });
          if (stopped) return;
          if (!result || typeof result.ticket !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(result.ticket)) {
            throw new Error("Invalid WebSocket ticket response");
          }
          protocols = ["readytrader", `ticket.${result.ticket}`];
        }
        socket = new WebSocket(wsUrl, protocols);
      } catch (error) {
        if (stopped) return;
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          setStatus("unauthorized");
          return;
        }
        setStatus("closed");
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        attemptRef.current = 0;
        setStatus("open");
      };

      socket.onmessage = (event: MessageEvent) => {
        try {
          const data: unknown = JSON.parse(event.data as string);
          for (const listener of listenersRef.current) listener(data);
        } catch {
          // Non-JSON payload; ignore rather than crash the app.
        }
      };

      socket.onclose = (event: CloseEvent) => {
        socketRef.current = null;
        if (stopped) return;
        if (event.code === 1008) {
          setStatus("unauthorized");
          return;
        }
        setStatus("closed");
        scheduleReconnect();
      };

      socket.onerror = () => {
        // The close handler runs right after and does the reconnect bookkeeping.
      };
    }

    connect();

    return () => {
      stopped = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      const socket = socketRef.current;
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onclose = null;
        socket.onerror = null;
        socket.close();
        socketRef.current = null;
      }
    };
  }, [token, enabled]);

  useEffect(() => {
    if (lastAnnouncedRef.current === status) return;
    lastAnnouncedRef.current = status;
    if (status === "open") announce("Live feed connected.");
    else if (status === "unauthorized") announce("Live feed rejected the session. Sign in again to reconnect.");
    else if (status === "closed") announce("Live feed disconnected. Retrying.");
  }, [status]);

  return { status, subscribe };
}
