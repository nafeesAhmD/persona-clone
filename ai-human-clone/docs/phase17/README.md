# Phase 17 — Real-time voice conversation

Talk to a clone hands-free: you speak, it answers out loud, you can cut in while it
speaks, and the conversation carries on. The wire format is in [contract.md](contract.md).

## Architecture

```
Browser (mic, voice-activity detection, playback)
  │  1. POST /api/clones/{id}/realtime/session      (cookie auth, all checks)  → one-time ticket
  │  2. WebSocket /api/realtime/sessions/{sid}/ws?ticket=…   (Origin checked, ticket used once)
  ▼
Backend  app/realtime_voice/
  connection.py   one socket = one session; each turn is a cancellable asyncio task
  providers/pipeline.py   the implemented provider:
      utterance ─► speech-to-text (existing STT provider, Gemini)
                 ─► the clone's normal chat turn (chat_service.prepare_stream + rag_pipeline:
                    same prompt/personality, RAG, approved memories, history, plan limits)
                    – public visitors: public_service pipeline (public documents only, no memories)
                 ─► answer text streamed (answer_delta) and, sentence by sentence,
                    spoken with the clone's voice (routing.effective_voice: cloned or AI voice)
  session_manager.py   live sessions + hashed one-time tickets (in-process)
  service.py      create/get/end, settings, rate/concurrency/quota checks, usage + analytics
  provider_base.py  RealtimeProvider interface (room for other providers)
```

**Transport: WebSocket, not WebRTC.** WebRTC needs either a media server (SFU/TURN) or a
provider that terminates it (e.g. OpenAI Realtime, Gemini Live). Those run their own model,
which would replace the clone's own pipeline (its personality, Claude/Gemini choice, RAG and
memories). No such adapter is implemented; `RealtimeProvider` is the place to add one.

**Interruption** is real: the browser stops playback at once and sends `interrupt` (or just
starts a new utterance — barge-in); the server cancels the turn's LLM stream and speech
synthesis and tells the browser to drop that turn's audio. A partial answer is kept in the
conversation only if some text was produced.

## Speech modes and honest latency

| | voice (default) | browser |
|---|---|---|
| Voice | the clone's cloned voice, or its AI voice | the browser's built-in voice (not the clone's) |
| First sound | after the first sentence is synthesised | as soon as the first sentence is written |
| Typical | Gemini TTS: seconds · cloned voice on a laptop CPU: ~1 min per sentence · on a Colab GPU: seconds | ~1–5 s |

Measured locally (Gemini, laptop CPU): typed question → full first answer **4.3 s** in
browser mode. STT adds 1–5 s for spoken questions.

## Languages

What the configured providers can do, not a promise for every provider:
* **English** — STT, LLM and every TTS.
* **Urdu (Urdu script)** — Gemini STT and LLM. The self-hosted Chatterbox voice reads Urdu
  through Hindi (Devanagari, spelled by Gemini); OmniVoice on a GPU speaks Urdu natively.
* **Roman Urdu** — the LLM answers in Roman Urdu when asked; it is rewritten for speech as above.
* Browser mode depends on the voices installed in the browser/OS (Urdu voices are often missing).

## Setup

```bash
# .env (never commit it)
REALTIME_VOICE_ENABLED=true          # off by default
REALTIME_VOICE_PROVIDER=pipeline
# optional, see .env.example for all: TTL, max duration, concurrency, rate limit, origins
docker compose up -d --build         # runs migration 0021_realtime_voice
```

Requirements: speech-to-text configured (Gemini key), the clone's voice on with consent.
No new paid service. Usage counts against the existing Gemini/TTS quotas; Gemini's free
tier limits requests per minute/day.

Per clone (owner, on the Voice page → "Live voice" card): enabled (default on),
public visitors (default **off**), default speech mode.

## Using it

Voice page → **Live voice** (or 🎙️ Live voice in the chat header) → **Start**. The browser
asks for the microphone only now. Speak; pause ~1 s to send. Talk over the clone to
interrupt it, or press **Stop speaking**. **End** closes everything.

## Local testing

```bash
cd backend && docker run --rm -v "$(pwd):/app" -w /app ahc-dev python -m pytest tests/test_realtime_voice.py -q
cd frontend && npm test && npx tsc --noEmit && npm run lint
```
Microphones need a secure context: `http://localhost` works; a LAN IP over plain http does not.

## Production (HTTPS)

* Serve the frontend and API over **HTTPS**; the socket is then `wss://` automatically
  (the URL is built from `NEXT_PUBLIC_API_URL`). Browsers block the mic on insecure origins.
* Set `REALTIME_VOICE_ALLOWED_ORIGINS` (or `CORS_ORIGINS`) to the exact site origin(s).
* The reverse proxy must pass WebSocket upgrades (`Upgrade`/`Connection` headers) on
  `/api/realtime/` and allow long-lived connections (≥ `REALTIME_VOICE_MAX_DURATION_SECONDS`).
* Live sessions are kept in the backend process: run **one** backend worker, or add a shared
  store (e.g. Redis) and sticky WebSocket routing before scaling out.

## Security and privacy

* Provider keys never reach the browser; the browser only gets a one-time ticket (≤ 60 s,
  stored as a SHA-256 hash, redacted from server logs) for one session.
* Every request is authorised server-side (clone access, voice consent, owner switch, public
  switches); access and consent are re-checked on every turn.
* Limits: sessions per minute, concurrent sessions per user, monthly plan limit
  `realtime_voice_sessions`, max session duration, max utterance size, public message limits.
* No raw audio or transcripts are stored by this feature; conversations are saved exactly as
  in normal chat. `REALTIME_VOICE_AUDIO_RETENTION_ENABLED` must stay false (not implemented).
* Analytics: `realtime_voice_session_started/ended`, `realtime_voice_connection_failed`,
  `realtime_voice_provider_error` (categories only); usage event `REALTIME_VOICE_SESSION`.

## Limitations

* Turn-based under the hood (utterance → answer), not full-duplex streaming STT.
* Voice-activity detection is energy-based in the browser; very noisy rooms may cut early/late.
* Echo: relies on the browser's echo cancellation; headphones work best for barge-in.
* Cloned voice on a CPU is slow (see above); use browser mode or the Colab GPU for speed.
