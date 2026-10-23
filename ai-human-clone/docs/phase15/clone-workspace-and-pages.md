# Phase 15: clone workspace on mobile, and the analytics, billing and organization pages

## Mobile chat (`/clone/{id}`)

- **Layout:** the chat fills the screen (`100dvh` minus the top bar, `--app-header-h`), and the composer stays at the bottom. The root viewport uses `interactive-widget=resizes-content`, so the message box stays above the on-screen keyboard. Safe-area padding is applied on notched phones.
- **Scrolling and conversations:** new messages scroll into view unless you have scrolled up to read. Conversations open from a drawer.
- **Messages:** sources can be collapsed. A failed message shows **Retry**, and it is only sent again when you tap it.
- **Bottom navigation:** hidden here (and on `/clone/{id}/call`) to give the chat the full height.

## Voice (microphone)

- **States:** voice replies go through Idle → Listening → Uploading → Transcribing → Thinking → Generating voice → Complete / Error. Each state is shown with text and an icon, not colour alone (`lib/voiceStates.ts`).
- **Starting and saving:** recording starts only when you tap the mic. Nothing is recorded or published automatically.
- **Problems the app explains:**
  - microphone permission denied
  - unsupported browser (no MediaRecorder / getUserMedia, or the page isn't served over HTTPS)
  - microphone missing or busy
  - upload failure
  - speech provider unavailable (503) or busy (429)
- **Permissions:**
  - Android Chrome asks the first time you tap the mic.
  - iOS Safari needs iOS 14.3+ and an HTTPS page; if access was denied, allow it again under Settings → Safari → Microphone.
  - Desktop browsers keep the choice in the address-bar site settings.

## Knowledge, memory, avatar

- **Knowledge:**
  - Uses the phone's file picker (PDF, DOCX, TXT) with upload progress, a size check before uploading, and manual knowledge.
  - Documents show as cards with an indexing status, plus Retry, Delete (with confirmation) and Search.
  - File paths are never shown.
- **Memory:** a segmented control switches between Pending, Approved, Rejected and Archived, and works at 320 px. The actions are Approve, Reject, Edit and Delete; destructive ones ask for confirmation.
- **Avatar:**
  - **Photo:** choose from the gallery (`accept="image/*"`) or tap **Take photo** (`capture="user"`). The camera is never forced, and the gallery always stays available.
  - **Video:** the status (queued, processing, completed, failed) is shown. The player is responsive and uses the avatar as its poster image. It plays inline and full screen where supported.
  - **Sound:** videos never autoplay with sound.
- **Sharing:** **Share this AI Clone** uses the phone's share sheet (Web Share API) and falls back to copying the link. It is only offered for public or unlisted clones, never for private ones.

## Analytics (`/analytics`, `/clone/{id}/analytics`)

- **Data:** a hub of your clones, and a per-clone page with a range selector (today, 7 days, 30 days, 90 days).
- **Summary cards:** Messages, Conversations, Visitors, Knowledge usage and Errors.
- **Activity chart:** made with CSS bars, with no chart library. It scrolls horizontally on small screens and has a table alternative for screen readers.
- **API:** `GET /api/clones/{id}/analytics/overview` and `GET /api/clones/{id}/analytics/activity` (new; daily counts, no message content). Both are owner only.

## Billing (`/billing`)

- **Page:** shows the current plan, usage against each limit (with progress bars that also show the numbers), the reset date and the available plans.
- **Upgrade and cancel:** with `BILLING_ENABLED=false` (the default), the page shows the free mode and explains that upgrades aren't enabled. Cancelling asks for confirmation. Payment secrets and provider ids are never shown.
- **API:** `GET /api/billing/usage` now returns real usage for the current month.

## Organizations (`/organizations`, `/organizations/{id}`, `/members`, `/settings`, `/invite/{token}`)

- **Pages:** list and create organizations; an overview of each, with its clones (assign or unassign your own clones).
- **Members:** shown as cards with role badges. The page also covers changing roles and removing members (owner/admin only, as the server enforces), inviting by email, and pending invitations.
- **Invite links:** the invite shows a one-time link `/invite/{token}` that can be copied or shared.
- **Settings:** rename, leave, and transfer ownership, each with confirmation.
- **Accepting an invite:** if you are logged out, `/invite/{token}` asks you to log in and then brings you back. Logged in, you can Accept or Decline. Wrong-account, expired and already-used invites get clear messages.

## Mobile client configuration

`GET /api/mobile/config` is public and contains no secrets. It returns the feature switches the app uses to decide what to show:
- maintenance and registration status, discovery, public chat, billing enabled
- voice: speech-to-text and text-to-speech availability, recording limits
- avatar: videos and live calls
- upload limits

The frontend reads it through `useMobileConfig()` (`lib/mobileConfig.ts`).

## In-progress actions and app updates

`lib/busy.ts` counts actions in progress:
- changes being sent to the API (POST/PATCH/PUT/DELETE)
- document uploads and streamed answers
- voice recordings and live calls

While any of these run, or while a text field holds a draft, a new app version waits before reloading ("Will update when you're done").
