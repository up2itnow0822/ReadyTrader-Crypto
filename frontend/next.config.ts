import type { NextConfig } from "next";

// `'unsafe-eval'` is only needed for Next's dev-mode React Refresh runtime; it must
// never ship in a production build.
const isDev = process.env.NODE_ENV !== "production";

const contentSecurityPolicy = [
  "default-src 'self'",
  "img-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "connect-src 'self' http: https: ws: wss:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig: NextConfig = {
  // Docker/production builds run as a standalone server.
  output: "standalone",

  // Runtime config (A1): the API/WS origins are resolved per-request in
  // src/app/layout.tsx from process.env, NOT baked in here at build time. Nothing in
  // this file should reference NEXT_PUBLIC_API_URL/NEXT_PUBLIC_WS_URL as a build-time
  // `env` value -- see frontend/AGENTS.md.
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
        ],
      },
    ];
  },
};

export default nextConfig;
