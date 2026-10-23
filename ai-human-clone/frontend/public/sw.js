/*
 * Clone Me service worker (Phase 15). Hand-written, no dependencies.
 *
 * Caches ONLY:
 *   - precache: the /offline page, the web manifest and the app icons;
 *   - runtime (cache-first): same-origin GET /_next/static/* (content-hashed build
 *     assets, incl. self-hosted fonts), /icons/*, and font files.
 * NEVER caches: /api/* or anything on the API origin, cross-origin requests, non-GET
 * requests, requests with Authorization / Range headers, responses with
 * Cache-Control no-store/private, HTML pages (navigations are network-only and fall
 * back to /offline when the network fails), RSC/data requests, audio/video, avatars,
 * documents and every other path not on the allowlist above.
 *
 * Updates: a new build registers /sw.js?v=<build id>; the new worker installs and
 * WAITS until the page sends {type: "SKIP_WAITING"} (the "Update now" button).
 * {type: "CLEAR_CACHES"} wipes every cache this worker owns (sent on logout).
 */

const params = new URL(self.location.href).searchParams;
const VERSION = (params.get("v") || "dev").replace(/[^A-Za-z0-9._-]/g, "").slice(0, 64) || "dev";
const API_ORIGIN = safeOrigin(params.get("api"));

const CACHE_PREFIX = "ahc-";
const PRECACHE = CACHE_PREFIX + "precache-" + VERSION;
const RUNTIME = CACHE_PREFIX + "runtime-" + VERSION;
const OFFLINE_URL = "/offline";
const RUNTIME_MAX_ENTRIES = 200;

const PRECACHE_URLS = [
  OFFLINE_URL,
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/maskable-512.png",
  "/icons/apple-touch-icon.png",
];

const STATIC_PREFIXES = ["/_next/static/", "/icons/"];
const FONT_EXTENSION = /\.(woff2?|ttf|otf)$/i;
const NEVER_PREFIXES = ["/api/", "/_next/image", "/_next/data/", "/media/", "/uploads/", "/avatars/", "/documents/"];
const MEDIA_EXTENSION = /\.(mp3|wav|ogg|oga|webm|m4a|aac|mp4|mov|m4v|pdf|docx?|txt|csv)$/i;

function safeOrigin(value) {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

/**
 * Decides how a request is handled: "static" (cache-first), "navigate"
 * (network-only with offline fallback) or "bypass" (the browser handles it; never cached).
 * `req` is {url, method, mode, destination, headers: {get(name)}}.
 */
function strategyFor(req, scopeOrigin) {
  let url;
  try {
    url = new URL(req.url);
  } catch {
    return "bypass";
  }
  if ((req.method || "GET").toUpperCase() !== "GET") return "bypass";
  if (API_ORIGIN && url.origin === API_ORIGIN) return "bypass";
  if (url.origin !== scopeOrigin) return "bypass";
  if (NEVER_PREFIXES.some((prefix) => url.pathname === prefix.replace(/\/$/, "") || url.pathname.startsWith(prefix))) {
    return "bypass";
  }
  if (req.mode === "navigate") return "navigate";
  const headers = req.headers;
  if (headers && (headers.get("authorization") || headers.get("range") || headers.get("rsc"))) return "bypass";
  if (req.destination === "audio" || req.destination === "video" || req.destination === "document") return "bypass";
  if (url.search && !url.pathname.startsWith("/_next/static/")) return "bypass";
  if (MEDIA_EXTENSION.test(url.pathname)) return "bypass";
  if (STATIC_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) return "static";
  if (FONT_EXTENSION.test(url.pathname)) return "static";
  return "bypass";
}

/** May this response be stored? `res` is {ok, status, type, headers: {get(name)}}. */
function isCacheableResponse(res) {
  if (!res || !res.ok || res.status !== 200) return false;
  if (res.type && res.type !== "basic" && res.type !== "default") return false;
  const cacheControl = (res.headers.get("cache-control") || "").toLowerCase();
  if (/no-store|private/.test(cacheControl)) return false;
  if (res.headers.get("set-cookie")) return false;
  const vary = (res.headers.get("vary") || "").toLowerCase();
  if (vary.includes("cookie") || vary.includes("authorization") || vary === "*") return false;
  const type = (res.headers.get("content-type") || "").toLowerCase();
  if (type.startsWith("audio/") || type.startsWith("video/") || type.startsWith("text/html")) return false;
  return true;
}

// Exposed for unit tests (tests/pwa-sw.test.ts loads this file in a sandbox).
self.__AHC_SW__ = { strategyFor, isCacheableResponse, VERSION, PRECACHE, RUNTIME, PRECACHE_URLS };

async function precache() {
  const cache = await caches.open(PRECACHE);
  await Promise.all(
    PRECACHE_URLS.map(async (path) => {
      try {
        const response = await fetch(new Request(path, { cache: "reload", credentials: "same-origin" }));
        // The offline page is static HTML; it is the one HTML document we keep.
        if (response.ok) await cache.put(path, response.clone());
        if (path === OFFLINE_URL && response.ok) await precacheOfflineAssets(await response.text());
      } catch {
        // Missing assets must not block installation.
      }
    }),
  );
}

/** Also keep the CSS/JS the offline page needs, so it renders with styles while offline. */
async function precacheOfflineAssets(html) {
  const assets = new Set(html.match(/\/_next\/static\/[^"'\s)\\]+/g) || []);
  const cache = await caches.open(RUNTIME);
  await Promise.all(
    [...assets].slice(0, 40).map(async (path) => {
      try {
        const response = await fetch(path, { credentials: "same-origin" });
        if (isCacheableResponse(response)) await cache.put(path, response);
      } catch {
        // Best effort.
      }
    }),
  );
}

async function deleteOldCaches() {
  const keep = new Set([PRECACHE, RUNTIME]);
  const names = await caches.keys();
  await Promise.all(names.filter((name) => name.startsWith(CACHE_PREFIX) && !keep.has(name)).map((name) => caches.delete(name)));
}

async function clearAllCaches() {
  const names = await caches.keys();
  await Promise.all(names.filter((name) => name.startsWith(CACHE_PREFIX)).map((name) => caches.delete(name)));
}

async function trimRuntimeCache() {
  const cache = await caches.open(RUNTIME);
  const keys = await cache.keys();
  const excess = keys.length - RUNTIME_MAX_ENTRIES;
  for (let i = 0; i < excess; i += 1) await cache.delete(keys[i]);
}

async function cacheFirst(request) {
  const cache = await caches.open(RUNTIME);
  const cached = (await cache.match(request)) || (await caches.match(request, { cacheName: PRECACHE }));
  if (cached) return cached;
  const response = await fetch(request);
  if (isCacheableResponse(response)) {
    await cache.put(request, response.clone());
    trimRuntimeCache().catch(() => undefined);
  }
  return response;
}

/**
 * The offline page is served in place of the page that failed. Tell it which page that
 * was (a same-origin path in a <meta> tag) so "Retry" goes back there.
 */
async function withRetryTarget(offline, requestedUrl) {
  try {
    const url = new URL(requestedUrl);
    // Allowlisted URL characters only, then "&" escaped: nothing can break out of the attribute.
    const path = (url.pathname + url.search).replace(/[^A-Za-z0-9\-._~/?=&%+,:;@!*()]/g, "").replace(/&/g, "&amp;");
    const html = await offline.text();
    const meta = '<meta name="ahc-offline-from" content="' + path + '">';
    return new Response(html.replace("<head>", "<head>" + meta), {
      status: 503,
      headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
    });
  } catch {
    return offline;
  }
}

async function networkWithOfflineFallback(event) {
  try {
    const preloaded = await event.preloadResponse;
    if (preloaded) return preloaded;
    return await fetch(event.request);
  } catch {
    const offline = await caches.match(OFFLINE_URL, { cacheName: PRECACHE });
    if (offline) return withRetryTarget(offline, event.request.url);
    return new Response(
      '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<title>Offline</title><body style="background:#0b0d14;color:#e6e8ef;font-family:system-ui,sans-serif;text-align:center;padding:4rem 1rem">' +
        "<h1>You are offline.</h1><p>Some features may be unavailable.</p>" +
        '<p><a href="" style="color:#a594ff">Retry</a></p></body>',
      { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } },
    );
  }
}

self.addEventListener("install", (event) => {
  // No skipWaiting() here: the page decides when to switch (see SKIP_WAITING).
  event.waitUntil(precache());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await deleteOldCaches();
      if (self.registration.navigationPreload) {
        try {
          await self.registration.navigationPreload.enable();
        } catch {
          // Not supported everywhere.
        }
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const strategy = strategyFor(event.request, self.location.origin);
  if (strategy === "static") event.respondWith(cacheFirst(event.request));
  else if (strategy === "navigate") event.respondWith(networkWithOfflineFallback(event));
  // "bypass": no respondWith, the browser fetches normally and nothing is stored.
});

self.addEventListener("message", (event) => {
  const type = event.data && event.data.type;
  if (type === "SKIP_WAITING") {
    self.skipWaiting();
  } else if (type === "CLEAR_CACHES") {
    event.waitUntil(
      clearAllCaches()
        .then(() => precache())
        .then(() => event.ports && event.ports[0] && event.ports[0].postMessage({ ok: true }))
        .catch(() => event.ports && event.ports[0] && event.ports[0].postMessage({ ok: false })),
    );
  }
});
