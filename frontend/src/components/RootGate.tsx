"use client";

import type { ReactNode } from "react";

import { useAuth } from "@/providers/AuthProvider";

import { AppShell } from "./AppShell";
import { HealthBanner } from "./HealthBanner";
import { LiveRegion } from "./LiveRegion";
import { LoginScreen } from "./LoginScreen";
import { SkipLink } from "./SkipLink";

/**
 * Decides login-screen vs. dashboard. The health banner and the live region are
 * rendered here, above that branch, so an unreachable API or an announcement is still
 * visible on the login screen -- not just once the user is already in.
 */
export function RootGate({ children }: { children: ReactNode }) {
  const auth = useAuth();

  return (
    <>
      <SkipLink />
      <HealthBanner />
      <LiveRegion />
      {auth.phase === "authenticated" || auth.phase === "no-auth" ? (
        <AppShell>{children}</AppShell>
      ) : auth.phase === "checking" ? (
        <div className="boot-screen" role="status">
          Connecting to the API…
        </div>
      ) : (
        <LoginScreen />
      )}
    </>
  );
}
