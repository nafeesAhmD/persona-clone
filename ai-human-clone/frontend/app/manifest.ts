import type { MetadataRoute } from "next";

/**
 * Web app manifest, served at /manifest.webmanifest (Phase 15).
 *
 * start_url is "/dashboard": an installed app is opened by people who use it, so it
 * starts where they work. Logged-out users are sent to /login by RequireAuth and
 * come back to the dashboard after signing in. "?source=pwa" is not added on
 * purpose: it would make the URL differ from normal visits for no benefit.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Clone Me",
    short_name: "Clone Me",
    description:
      "Create a consent-based AI clone that answers questions using the knowledge and style you provide.",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    // Chat, voice and video calls work in either orientation (tablets, landscape keyboards).
    orientation: "any",
    theme_color: "#0b0d14",
    background_color: "#0b0d14",
    lang: "en",
    dir: "ltr",
    categories: ["productivity", "social", "utilities"],
    prefer_related_applications: false,
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      {
        name: "Dashboard",
        short_name: "Dashboard",
        description: "Your clones",
        url: "/dashboard",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
      {
        name: "Explore clones",
        short_name: "Explore",
        description: "Public clones you can chat with",
        url: "/explore",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
      },
    ],
  };
}
