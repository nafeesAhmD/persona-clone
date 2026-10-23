import type { NextConfig } from "next";

/*
 * Content-Security-Policy: deliberately conservative. A full script-src/connect-src
 * policy would need nonces for Next's inline bootstrap scripts (forcing every page to
 * render dynamically) and an allowlist that tracks NEXT_PUBLIC_API_URL plus Simli /
 * LiveKit WebRTC hosts, blob: media and data: images; a mistake there silently breaks
 * voice, video calls or the app itself. These directives cannot break any of that and
 * still block clickjacking, plugin content, <base> hijacking and form exfiltration.
 */
const contentSecurityPolicy = ["frame-ancestors 'none'", "object-src 'none'", "base-uri 'self'", "form-action 'self'"].join("; ");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Microphone: this site's voice chat. Camera: the optional self-view in video calls
  // (shown only to you, never sent).
  { key: "Permissions-Policy", value: "camera=(self), geolocation=(), microphone=(self)" },
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
];

// Signed-in owner pages are never indexed; public clone pages set their own robots metadata.
const privatePages = ["/dashboard", "/profile", "/create-clone", "/clones", "/clone/:path*", "/login", "/register", "/developer", "/developer/:path*"];

// Changes on every build: the service worker is registered as /sw.js?v=<id>, so a new
// deploy is detected as an update (see components/pwa/UpdateNotice.tsx).
const buildId = process.env.NEXT_PUBLIC_BUILD_ID || new Date().toISOString().replace(/[^0-9]/g, "").slice(0, 14);

const nextConfig: NextConfig = {
  // Produces a minimal self-contained server for the Docker image.
  output: "standalone",
  // No "X-Powered-By: Next.js" header (don't advertise the stack).
  poweredByHeader: false,
  env: { NEXT_PUBLIC_BUILD_ID: buildId },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      ...privatePages.map((source) => ({ source, headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] })),
      {
        // Always fetch the service worker fresh so updates are found right away.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
      {
        source: "/manifest.webmanifest",
        headers: [{ key: "Cache-Control", value: "public, max-age=0, must-revalidate" }],
      },
      {
        // Icons keep their names across builds, so revalidate daily rather than "immutable".
        source: "/icons/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=86400, must-revalidate" }],
      },
      {
        source: "/offline",
        headers: [{ key: "X-Robots-Tag", value: "noindex" }],
      },
    ];
  },
};

export default nextConfig;
