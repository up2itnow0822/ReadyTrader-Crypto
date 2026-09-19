"use client";

import type { ReactNode } from "react";

import { useAuth } from "@/providers/AuthProvider";
import { useSidebar } from "@/providers/SidebarProvider";

import { HealthPill } from "./HealthPill";
import { Nav } from "./Nav";
import { WsStatusIndicator } from "./WsStatusIndicator";

export function AppShell({ children }: { children: ReactNode }) {
  const sidebar = useSidebar();
  const auth = useAuth();

  return (
    <div className="app-shell">
      <header className="app-header">
        <button
          type="button"
          className="hamburger"
          aria-expanded={sidebar.open}
          aria-controls="app-sidebar"
          aria-label={sidebar.open ? "Close navigation menu" : "Open navigation menu"}
          onClick={sidebar.toggle}
        >
          <span aria-hidden="true">☰</span>
        </button>
        <span className="app-header__title">ReadyTrader-Crypto</span>
        <div className="app-header__status">
          <HealthPill />
          <WsStatusIndicator />
          {auth.phase === "no-auth" && <span className="dev-note">auth disabled (dev)</span>}
          {auth.phase === "authenticated" && (
            <button type="button" className="logout-button" onClick={auth.logout}>
              Log out
            </button>
          )}
        </div>
      </header>

      <div className="app-body">
        {/*
          No `aria-hidden` here: on desktop this sidebar is always visible via CSS
          (sidebar.open only controls the mobile slide-in), so tying aria-hidden to
          that same flag hid the nav from assistive tech on every desktop page load.
          On mobile, the closed state's `visibility: hidden` (globals.css) already
          removes it from the accessibility tree on its own -- nothing extra needed.
        */}
        <aside id="app-sidebar" className={`app-sidebar ${sidebar.open ? "app-sidebar--open" : ""}`}>
          <Nav onNavigate={sidebar.close} />
        </aside>
        {sidebar.open && (
          <button
            type="button"
            className="sidebar-overlay"
            aria-label="Close navigation menu"
            onClick={sidebar.close}
          />
        )}

        <main id="main-content" className="app-main" tabIndex={-1}>
          {children}
        </main>
      </div>

      <footer className="app-footer">
        <span>ReadyTrader-Crypto operator dashboard.</span>
      </footer>
    </div>
  );
}
