import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";

import { AppProviders } from "@/providers/AppProviders";

import "./globals.css";

// Runtime config (A1): this layout must be re-executed on every request, not served
// from a static/prerendered cache, so `process.env` and the request host are read
// fresh each time. That's what lets the SAME build answer with a different API/WS
// origin depending on how the running `next start` process was configured.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: {
    default: "ReadyTrader-Crypto",
    template: "%s · ReadyTrader-Crypto",
  },
  description: "Operator dashboard for the ReadyTrader-Crypto paper/live trading API.",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

interface RuntimeConfig {
  apiUrl: string;
  wsUrl: string;
}

function deriveWsUrlFromApiUrl(apiUrl: string): string {
  try {
    const parsed = new URL(apiUrl);
    parsed.protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
    parsed.pathname = "/ws";
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return "ws://localhost:8000/ws";
  }
}

async function resolveRuntimeConfig(): Promise<RuntimeConfig> {
  const requestHeaders = await headers();
  const hostHeader = requestHeaders.get("host") ?? "localhost:3100";
  const hostname = hostHeader.split(":")[0] || "localhost";

  const apiUrl =
    process.env.READYTRADER_API_URL || process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000`;
  const wsUrl = process.env.READYTRADER_WS_URL || process.env.NEXT_PUBLIC_WS_URL || deriveWsUrlFromApiUrl(apiUrl);

  return { apiUrl, wsUrl };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const config = await resolveRuntimeConfig();

  return (
    <html lang="en">
      <body>
        <AppProviders config={config}>{children}</AppProviders>
      </body>
    </html>
  );
}
