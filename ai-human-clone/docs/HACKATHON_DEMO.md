# Hackathon demo

A repeatable 8–10 minute demo using only features that exist in this repository. Nothing here
is pre-recorded or faked: if a provider is down, use the fallback listed for that step and say so.

## Pitch (30 seconds)

**AI Human Clone** lets a person build a consent-based AI version of themselves. The clone learns
only from documents the owner uploads and memories the owner approves. It answers in their
personality, in English, Urdu or Roman Urdu, and it can speak with their own cloned voice and
appear as a talking avatar. Sharing is always the owner's choice: a public page, a marketplace
listing, or a developer API. Every answer says it comes from an AI, shows its sources, and can
never reach private knowledge from a public chat.

## Prerequisites

* Docker Desktop (8 GB RAM for Docker recommended), the repository, and a `.env` made from
  `.env.example` with at least `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY`) and a strong
  `JWT_SECRET_KEY`. Never show `.env` on screen.
* Optional: `REALTIME_VOICE_ENABLED=true` (live voice), the `voice-clone` service
  (`docker compose --profile voice-clone up -d`) for a self-hosted cloned voice, `SIMLI_API_KEY`
  (live avatar call), `FAL_API_KEY` + `LIPSYNC_PROVIDER=fal` (realistic avatar videos).
* A short demo document you own, e.g. a one-page PDF or `.txt` "About me" with 4–5 specific facts
  (supported: PDF, DOCX, TXT; up to `MAX_UPLOAD_SIZE_MB`, default 10 MB).
* For voice/avatar: a 30-second recording of **your own** normal speech (no music or singing) and
  a clear front-facing photo of yourself. Clone only yourself, or someone who gave consent.

## Setup (once, ~10 minutes; the first start downloads the embedding model)

```bash
cd ai-human-clone
docker compose up -d --build
curl http://localhost:8000/api/health/ready     # {"status":"ready",...}
```

Open http://localhost:3007. Create two accounts through **Create Account**: a demo **owner** and
a second **visitor** account (or use a private browser window as a logged-out visitor). Pick your
own passwords; do not put them in slides or files. To show admin pages, set
`INITIAL_ADMIN_EMAIL=<owner email>` in `.env` before starting (that account becomes admin).

Rehearse once: chat answers depend on the live LLM provider.

## Demo steps and expected results

| # | Do | Expect |
|---|---|---|
| 1 | Open http://localhost:3007 | Landing page; header shows Explore / Login / Create Account |
| 2 | Log in as the owner | Dashboard "Welcome, …" |
| 3 | **Create clone** (`/create-clone`): name, profession, personality, skills, language; tick consent | Clone page opens with the chat |
| 4 | **Knowledge** tab → upload the demo document | Status goes to indexed with a chunk count |
| 5 | In chat ask about one fact from the document | Streamed answer using that fact; a sources list names the document |
| 6 | Ask something the document doesn't cover ("What is my blood type?") | The clone says it doesn't know rather than inventing it |
| 7 | **Memory** tab: approve a suggested memory (or add one), then ask about it in a new chat | The answer uses the approved memory |
| 8 | **Voice** tab: turn voice on (consent), test voice; optionally record your own voice → "Create my voice" | Speech plays; with a cloned voice it sounds like you |
| 8b | Optional **Live voice** (`/clone/<id>/voice/live`) → Start, talk, interrupt by talking | Answers spoken sentence by sentence; talking over it stops it |
| 9 | Optional **Avatar** tab: upload your photo (consent) → generate a short video, or start a live call | Talking-head video / live face |
| 10 | **Sharing** tab: make the clone public with public chat; optionally publish to the marketplace (confirmation) | Public link `/c/<slug>`; clone appears on `/explore` when published |
| 11 | Open `/c/<slug>` logged out and ask the step-5 question, then a private-only fact | Public answers use only public documents; private facts are not revealed |
| 12 | **Analytics** tab | Conversations, messages and usage counts from the demo |
| 13 | Optional **Agent** tab: run "What is 18% of 2,450 and what's today's date?" | Planned tool calls (calculator, date) shown step by step; a risky step would ask for confirmation |

## Fallbacks (say what you are doing; never fake output)

| Problem | Fallback |
|---|---|
| Gemini/Claude overloaded or slow (503/timeouts) | Retry once; switch `GEMINI_MODEL` to a lighter model (e.g. a flash-lite model) and restart the backend; otherwise show steps 3–4 and 10–12, which don't need the LLM |
| Cloned voice too slow (self-hosted on a laptop CPU: ~1 min per sentence) | Use the AI voice or the live page's **Browser voice** mode (instant, not your voice), or run the voice service on a free Colab GPU beforehand (`scripts/voice-gpu.ps1`, a few seconds per sentence) |
| No Simli / fal key | Skip step 9 or show the local avatar mode, and say realistic avatars need a provider key |
| Microphone blocked | Use `http://localhost` (a secure context); the LAN IP over plain http blocks the mic |
| Docker Desktop hangs | Restart Docker Desktop; data lives in volumes and survives |

## Known limitations (be upfront)

* Runs as one backend process; no public deployment is included.
* Urdu speech through Chatterbox goes via a Hindi model (spelling done by Gemini); OmniVoice speaks
  Urdu natively but needs a GPU and is licensed for non-commercial use only.
* Self-hosted voice cloning on a CPU is slow; real-time voice is turn-based, not full-duplex.
* LLM answers can still be wrong; sources are shown so the audience can check them.
* No ratings/reviews in the marketplace (by design).
