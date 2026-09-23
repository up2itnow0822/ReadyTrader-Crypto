"use client";

import type { ReactNode } from "react";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { RootGate } from "@/components/RootGate";
import { useServiceWorker } from "@/hooks/useServiceWorker";
import { setRuntimeConfig, type RuntimeConfig } from "@/lib/config";

import { AuthProvider } from "./AuthProvider";
import { HealthProvider } from "./HealthProvider";
import { SidebarProvider } from "./SidebarProvider";
import { WebSocketProvider } from "./WebSocketProvider";

/**
 * The client boundary the server-rendered root layout hands the request-time config
 * to. Setting the runtime config store here (during render, not inside an effect)
 * means it is populated before any child's mount effect runs -- `HealthProvider`'s
 * first `/api/health` poll included.
 */
export function AppProviders({ config, children }: { config: RuntimeConfig; children: ReactNode }) {
  setRuntimeConfig(config);
  useServiceWorker();

  return (
    <ErrorBoundary>
      <HealthProvider>
        <AuthProvider>
          <WebSocketProvider>
            <SidebarProvider>
              <RootGate>{children}</RootGate>
            </SidebarProvider>
          </WebSocketProvider>
        </AuthProvider>
      </HealthProvider>
    </ErrorBoundary>
  );
}
