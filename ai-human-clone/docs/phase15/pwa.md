# Progressive Web App (Phase 15)

AI Human Clone can be installed on phones, tablets and desktops as a Progressive Web
App (PWA). It uses the same frontend and the same FastAPI backend as the website; there
is no separate mobile backend.

## What's included

| Piece | Where |
| --- | --- |
| Web app manifest (`/manifest.webmanifest`) | `frontend/app/manifest.ts` |
| Icons (192, 512, maskable 512, Apple touch 180, favicon) | `frontend/public/icons/`, `frontend/app/icon.png`, `frontend/app/apple-icon.png` |
| Service worker (hand-written, no dependencies) | `frontend/public/sw.js` |
| Offline page | `frontend/app/offline/page.tsx` |
| Registration, install card, update notice, network banner | `frontend/components/pwa/` |
| Pure logic (unit-tested) | `frontend/lib/pwa/` |
| API error kinds, timeouts, auth-expired event | `frontend/lib/api.ts` |
| Client config hook (`GET /api/mobile/config`) | `frontend/lib/mobileConfig.ts` |

The manifest opens the installed app at `/dashboard` (logged-out users are sent to the
login page and come back to the dashboard), in `standalone` mode, with the app's dark
theme color `#0b0d14`. It has two shortcuts: Dashboard and Explore.

## Setup

Nothing extra to install. The service worker is registered automatically:

- only in **production builds** (`next build` + `next start`, or the Docker image).
  In `next dev` it is never registered, and a worker left over from an earlier
  production run on the same origin is unregistered;
- only in **secure contexts**: `https://…` or `http://localhost`. On plain `http://`
  hosts (for example a LAN IP like `http://192.168.1.20:3000`) registration is silently
  skipped and the site works as a normal website.

Each build gets a build id (`NEXT_PUBLIC_BUILD_ID`, a timestamp by default; set it to
your git SHA in CI if you prefer). The worker is registered as
`/sw.js?v=<build id>&api=<API origin>`, so every deploy is detected as an update.

`/sw.js` is served with `Cache-Control: no-cache, no-store, must-revalidate` and
`Service-Worker-Allowed: /` (see `frontend/next.config.ts`).

## HTTPS requirements

- Service workers only run on **HTTPS**, with one exception: `localhost`.
- Installing the app ("Add to Home Screen" / "Install app") also requires HTTPS in
  production. Put the frontend behind TLS (a reverse proxy such as Caddy, nginx or
  your platform's load balancer).
- The API (`NEXT_PUBLIC_API_URL`) must also use HTTPS in production; browsers block
  `http://` API calls from an `https://` page (mixed content), and the session cookie
  should be `Secure` in production.

## Installing the app

**Android (Chrome, Edge, Samsung Internet)**: after a couple of page views an
"Install AI Human Clone" card appears below the top bar. Tap **Install**. You can also use
the browser menu → **Install app** / **Add to Home screen**.

**iPhone / iPad (Safari)**: iOS has no install prompt, so the card shows a hint instead:
tap **Share** (the square with an arrow) → **Add to Home Screen**. Other iOS browsers
may not offer this; open the site in Safari.

**Desktop (Chrome, Edge)**: use the install icon in the address bar, or the card when it
appears. Firefox desktop does not support installing web apps; the site works normally.

The card never blocks the app. It is shown only on browsing pages (dashboard, clones,
explore, analytics, profile), never over a form, an editor or the chat, and not on the
first page of a visit. All PWA notices (install, update, offline) sit just below the
top bar, so they never cover submit buttons or the message composer. The card disappears once the app is installed, and after **Not now** it
stays hidden for 30 days (stored in `localStorage` as `ahc:install-dismissed-at`).

## Offline behaviour and limitations

The app needs the network for nearly everything: chatting, voice, avatars, knowledge,
login. When offline:

- a banner says "You are offline. Some features may be unavailable.";
- opening a page that can't be loaded shows the offline page with a **Retry** button
  (it also retries automatically when the connection comes back);
- already-open screens keep what they show; actions fail with a clear "You are offline"
  message instead of a generic error;
- when the connection returns, the app refreshes its data with GET requests and fires a
  `ahc:back-online` window event. Messages, uploads and other changes are **never**
  re-sent automatically. Send them again yourself.

There is no offline chat, offline history or background sync. This is deliberate:
conversations and documents are private and stay on the server.

## What is cached, and what is never cached

Cached (versioned caches `ahc-precache-<build>` and `ahc-runtime-<build>`; old versions
are deleted when a new worker activates):

- **Precache**: `/offline`, `/manifest.webmanifest`, the app icons, plus the CSS/JS
  files the offline page needs.
- **Runtime, cache-first**: same-origin `GET` requests for `/_next/static/*`
  (content-hashed build files, including self-hosted fonts), `/icons/*` and font files.
  At most 200 entries.

Never cached:

- anything under `/api` and anything on the API origin (`NEXT_PUBLIC_API_URL`);
- any other origin (Simli, LiveKit, etc.);
- any non-GET request;
- requests with an `Authorization` or `Range` header;
- responses with `Cache-Control: no-store` or `private`, with `Set-Cookie`, or varying on
  cookies, and any non-200 / opaque response;
- HTML pages. Navigations are network-only; the only HTML kept is the static offline page;
- Next.js RSC/data requests and `/_next/image`;
- audio, video, avatars, documents and other user media.

On logout the app asks the worker to clear all its caches (`CLEAR_CACHES`), as defence
in depth. The caches never contain private data in the first place.

## Updates

1. A new deploy changes the worker URL; the browser installs the new worker in the
   background (it also re-checks at most once an hour when the tab becomes visible).
2. The new worker **waits**; it does not take over by itself. The app shows
   "New version available" with **Update now** (or **Later**).
3. **Update now** tells the worker to activate (`SKIP_WAITING`). When it takes over,
   the page reloads, but **not** while you are typing, have an unsent draft, or a form is
   busy (`data-busy="true"` / `aria-busy` on a form). Then it shows "Will update when
   you're done" and reloads as soon as it's safe.
4. If you pick **Later**, the new version is used the next time all app tabs are closed.

## API errors and network handling

`apiFetch` (in `lib/api.ts`) adds a 30-second timeout to normal requests (file uploads
and the streaming chat have no client timeout) and classifies failures as
`ApiError.kind`:

| kind | When |
| --- | --- |
| `offline` | the device is offline |
| `timeout` | no answer within the time limit |
| `network` | online, but the server couldn't be reached |
| `maintenance` | 503 with `maintenance: true` |
| `unavailable` | 502/503/504 (server or AI provider temporarily unavailable) |
| `auth` | 401: session missing or expired |
| `forbidden` / `not_found` | 403 / 404, 410 |
| `rate_limit` / `usage_limit` | 429: too many requests / plan limit reached |
| `invalid` | other 4xx (validation etc.) |
| `server` | anything else |

Only `GET`/`HEAD` requests are retried, once, and only for `network`/`unavailable`;
`POST`, `PATCH`, `PUT` and `DELETE` are never retried automatically. A 401 (outside
`/api/auth/*`) fires the `ahc:auth-expired` window event. `components/ApiErrorState.tsx`
shows a matching screen with **Try again**, **Log in again** or **Go back**.

## Security headers

`next.config.ts` sends `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy: camera=(self), geolocation=(), microphone=(self)` and a
conservative CSP: `frame-ancestors 'none'; object-src 'none'; base-uri 'self';
form-action 'self'`. A full `script-src`/`connect-src` policy would need per-request
nonces for Next.js' inline scripts and an allowlist covering the API origin and the
WebRTC providers; it can be added later at the reverse proxy.

## Browser compatibility

| Feature | Chrome / Edge (Android, desktop) | Samsung Internet | Safari iOS/iPadOS 16.4+ | Safari macOS | Firefox |
| --- | --- | --- | --- | --- | --- |
| Service worker + offline page | yes | yes | yes | yes | yes |
| Install prompt card | yes | yes | hint (Share → Add to Home Screen) | via File → Add to Dock (Sonoma+) | Android: menu only; desktop: no |
| Maskable icon | yes | yes | uses apple-touch-icon | n/a | Android: yes |
| Update notice | yes | yes | yes | yes | yes |

## Troubleshooting

- **No install option**: the site must be on HTTPS (or localhost), in a production
  build, and visited at least twice in the session. Already installed? The card hides.
  Dismissed it? Clear `ahc:install-dismissed-at` in site storage.
- **Service worker not registering**: check DevTools → Application → Service Workers.
  It's skipped in `next dev` and on `http://` hosts other than localhost.
- **Stuck on an old version**: click **Update now**, or close every app tab and reopen.
  In DevTools you can tick "Update on reload" or unregister the worker.
- **Offline page shows while online**: the server may be down or unreachable from the
  device; use Retry. The offline page is only shown when the page request itself fails.
- **Testing on a phone over the LAN**: `http://<LAN IP>` is not a secure context, so no
  service worker or install. Use an HTTPS tunnel or a proper certificate.
- **Clearing everything**: DevTools → Application → Storage → Clear site data
  (also unregisters the worker).
