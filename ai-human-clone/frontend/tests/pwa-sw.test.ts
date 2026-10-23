// Loads public/sw.js in a sandbox and checks its caching rules directly
// (the worker exposes its pure decision functions on self.__AHC_SW__).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
const ORIGIN = "https://app.example.com";
const API = "https://api.example.com";

interface SwApi {
  strategyFor: (req: unknown, origin: string) => "static" | "navigate" | "bypass";
  isCacheableResponse: (res: unknown) => boolean;
  VERSION: string;
  PRECACHE: string;
  RUNTIME: string;
  PRECACHE_URLS: string[];
}

function loadWorker(scriptUrl = `${ORIGIN}/sw.js?v=20261005&api=${encodeURIComponent(API)}`) {
  const listeners: Record<string, unknown> = {};
  const self: Record<string, unknown> = {
    location: new URL(scriptUrl),
    addEventListener: (type: string, fn: unknown) => {
      listeners[type] = fn;
    },
  };
  vm.runInNewContext(SOURCE, { self, URL, Response: class {}, Request: class {}, caches: {}, fetch: () => undefined });
  return { sw: self.__AHC_SW__ as SwApi, listeners };
}

const headers = (values: Record<string, string> = {}) => ({
  get: (name: string) => values[name.toLowerCase()] ?? null,
});
const req = (url: string, extra: Record<string, unknown> = {}) => ({
  url,
  method: "GET",
  mode: "cors",
  destination: "",
  headers: headers(),
  ...extra,
});
const res = (extra: Record<string, unknown> = {}, h: Record<string, string> = {}) => ({
  ok: true,
  status: 200,
  type: "basic",
  headers: headers({ "content-type": "application/javascript", ...h }),
  ...extra,
});

const { sw, listeners } = loadWorker();
const decide = (url: string, extra: Record<string, unknown> = {}) => sw.strategyFor(req(url, extra), ORIGIN);

test("registers install, activate, fetch and message handlers", () => {
  for (const type of ["install", "activate", "fetch", "message"]) assert.equal(typeof listeners[type], "function", type);
  assert.doesNotMatch(SOURCE, /skipWaiting\(\)\s*;?\s*\}\);\s*$/m);
  // skipWaiting only appears inside the SKIP_WAITING message branch.
  assert.equal(SOURCE.match(/self\.skipWaiting\(\)/g)?.length, 1);
});

test("versioned cache names", () => {
  assert.equal(sw.VERSION, "20261005");
  assert.equal(sw.PRECACHE, "ahc-precache-20261005");
  assert.equal(sw.RUNTIME, "ahc-runtime-20261005");
  const other = loadWorker(`${ORIGIN}/sw.js?v=<script>bad`).sw;
  assert.match(other.VERSION, /^[A-Za-z0-9._-]+$/, "version is sanitised");
});

test("precache holds only the offline page, manifest and icons", () => {
  for (const url of sw.PRECACHE_URLS) {
    assert.ok(url === "/offline" || url === "/manifest.webmanifest" || url.startsWith("/icons/"), url);
  }
});

test("immutable static assets are cache-first", () => {
  assert.equal(decide(`${ORIGIN}/_next/static/chunks/app-123.js`), "static");
  assert.equal(decide(`${ORIGIN}/_next/static/css/abc.css`), "static");
  assert.equal(decide(`${ORIGIN}/_next/static/media/inter.woff2`), "static");
  assert.equal(decide(`${ORIGIN}/icons/icon-192.png`), "static");
  assert.equal(decide(`${ORIGIN}/fonts/brand.woff2`), "static");
});

test("navigations are network-first with offline fallback (never cached)", () => {
  assert.equal(decide(`${ORIGIN}/dashboard`, { mode: "navigate", destination: "document" }), "navigate");
  assert.equal(decide(`${ORIGIN}/clone/123/chat`, { mode: "navigate", destination: "document" }), "navigate");
});

test("never cached: API, other origins, writes, auth, media, data", () => {
  assert.equal(decide(`${ORIGIN}/api/clones`), "bypass", "same-origin /api");
  assert.equal(decide(`${ORIGIN}/api/auth/me`, { mode: "navigate" }), "bypass", "even as a navigation");
  assert.equal(decide(`${API}/api/clones`), "bypass", "API origin");
  assert.equal(decide(`${API}/static/x.js`), "bypass", "anything on the API origin");
  assert.equal(decide("https://api.simli.ai/session"), "bypass", "third party");
  assert.equal(decide(`${ORIGIN}/_next/static/chunks/a.js`, { method: "POST" }), "bypass", "non-GET");
  assert.equal(decide(`${ORIGIN}/_next/static/chunks/a.js`, { headers: headers({ authorization: "Bearer x" }) }), "bypass");
  assert.equal(decide(`${ORIGIN}/_next/static/media/a.mp4`, { headers: headers({ range: "bytes=0-" }) }), "bypass");
  assert.equal(decide(`${ORIGIN}/_next/static/media/clip.mp4`), "bypass", "video");
  assert.equal(decide(`${ORIGIN}/_next/static/media/voice.mp3`), "bypass", "audio");
  assert.equal(decide(`${ORIGIN}/icons/x.png`, { destination: "video" }), "bypass");
  assert.equal(decide(`${ORIGIN}/_next/image?url=%2Favatar.png&w=64`), "bypass", "optimized images");
  assert.equal(decide(`${ORIGIN}/_next/data/build/dashboard.json`), "bypass");
  assert.equal(decide(`${ORIGIN}/dashboard?_rsc=abc`, { headers: headers({ rsc: "1" }) }), "bypass", "RSC payload");
  assert.equal(decide(`${ORIGIN}/dashboard`), "bypass", "non-navigation HTML fetch");
  assert.equal(decide(`${ORIGIN}/avatars/a.png`), "bypass");
  assert.equal(decide(`${ORIGIN}/documents/report.pdf`), "bypass");
  assert.equal(decide(`${ORIGIN}/sw.js`), "bypass");
  assert.equal(decide("not a url"), "bypass");
});

test("responses: only plain, public, non-media 200s are stored", () => {
  assert.equal(sw.isCacheableResponse(res()), true);
  assert.equal(sw.isCacheableResponse(res({}, { "cache-control": "public, max-age=31536000, immutable" })), true);
  assert.equal(sw.isCacheableResponse(res({}, { "cache-control": "no-store" })), false);
  assert.equal(sw.isCacheableResponse(res({}, { "cache-control": "private, max-age=60" })), false);
  assert.equal(sw.isCacheableResponse(res({}, { "set-cookie": "a=b" })), false);
  assert.equal(sw.isCacheableResponse(res({}, { vary: "Cookie" })), false);
  assert.equal(sw.isCacheableResponse(res({}, { "content-type": "audio/mpeg" })), false);
  assert.equal(sw.isCacheableResponse(res({}, { "content-type": "video/mp4" })), false);
  assert.equal(sw.isCacheableResponse(res({}, { "content-type": "text/html; charset=utf-8" })), false);
  assert.equal(sw.isCacheableResponse(res({ ok: false, status: 404 })), false);
  assert.equal(sw.isCacheableResponse(res({ status: 206 })), false, "partial content");
  assert.equal(sw.isCacheableResponse(res({ type: "opaque" })), false);
  assert.equal(sw.isCacheableResponse(null), false);
});
