"use client";

import { createContext, useContext, type ReactNode } from "react";

import { getToken as getStoredToken } from "@/lib/authStore";
import { useWebSocket, type WsStatus } from "@/lib/useWebSocket";

import { useAuth } from "./AuthProvider";

export interface WebSocketState {
  status: WsStatus;
  subscribe: (listener: (data: unknown) => void) => () => void;
}

const WebSocketContext = createContext<WebSocketState | null>(null);

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const enabled = auth.phase === "authenticated" || auth.phase === "no-auth";
  const token = auth.phase === "authenticated" ? getStoredToken() : null;
  const { status, subscribe } = useWebSocket(token, enabled);

  return <WebSocketContext.Provider value={{ status, subscribe }}>{children}</WebSocketContext.Provider>;
}

export function useWs(): WebSocketState {
  const ctx = useContext(WebSocketContext);
  if (!ctx) throw new Error("useWs must be used within a WebSocketProvider");
  return ctx;
}
