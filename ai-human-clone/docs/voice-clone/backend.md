# Personal voice clone (backend)

The owner of an AI Clone can record their own voice. The clone then answers in that
voice: in voice chat, in "Play" on chat replies, in the voice test, for public visitors
(if public voice is on), in talking-avatar videos and in live video calls. Cloning uses
ElevenLabs Instant Voice Cloning. Spoken answers are still labelled "AI-generated voice".

## How it works

1. The owner gives **voice consent** on the clone (Voice settings), as before.
2. The owner records or uploads 1–5 samples (WebM, WAV, MP3, M4A or OGG, each up to
   `MAX_AUDIO_SIZE_MB`) and confirms the **clone consent**: "This is my own voice, or I
   have the speaker's permission to clone it."
3. The backend checks every file (type, size, real audio, length) and the total length
   (`VOICE_CLONE_MIN_SECONDS`–`VOICE_CLONE_MAX_SECONDS`, 30–300 s by default). It then sends
   the original recordings to ElevenLabs (`POST /v1/voices/add`) and keeps only the returned
   voice id. **The recordings are never stored on our server.**
4. On success the cloned voice is switched on (`use_cloned_voice`). A provider failure is
   saved as status `failed` with a safe message; the owner can try again.

### API (owner only), under `/api/clones/{clone_id}/voice/clone`

| Method | Body | Result |
|---|---|---|
| GET | – | `VoiceCloneStatus` |
| POST | multipart: `files` (repeat, 1..`VOICE_CLONE_MAX_FILES`), `consent=true`, `remove_background_noise=true\|false` | 201 `VoiceCloneStatus` (`ready` or `failed` + `error`) |
| PATCH | `{"use_cloned_voice": bool}` | `VoiceCloneStatus` (turning on needs status `ready`) |
| DELETE | – | 204: deleted at ElevenLabs and here |

`VoiceCloneStatus`: `available` (key set), `status` (`none`/`processing`/`ready`/`failed`),
`error`, `use_cloned_voice`, `consent_at`, `provider`, `min_seconds`, `max_seconds`,
`max_files`, `model`. It is also embedded in `GET /voice/settings` as `voice_clone`.

Errors: 503 without `ELEVENLABS_API_KEY`; 403 without voice consent; 400 without clone
consent, with too many files, or when the total length is outside the limits (e.g.
"Record at least 30 seconds in total (you have 18)."); 413/415 for a too-large or
unsupported file; 429 after 3 clone attempts in an hour (per user).

### Which voice is used (TTS routing)

`clone.voice_id` always keeps the clone's prebuilt voice. `app/voice/routing.py`
`effective_voice(clone)` returns `"elevenlabs:<voice_clone_id>"` while the cloned voice is
ready, switched on, consented and the server has a key; otherwise the prebuilt voice.
Every speech caller passes `effective_voice(clone)` to `generate_speech`, which sends
`elevenlabs:` voices to ElevenLabs (`POST /v1/text-to-speech/{id}`, MP3, `ELEVENLABS_MODEL`)
and all others to the normal TTS provider. So:

- voice chat, spoken replies, the voice test and public voice use the cloned voice;
- **talking-avatar videos** lip-sync that same speech;
- **live calls** stream each answer's speech (voice chat) to the live face, so the face
  speaks with the owner's voice automatically.

Turning the cloned voice off (PATCH, or choosing a prebuilt voice in Voice settings) goes
back to the prebuilt voice. In the Voice settings list the cloned voice appears as
"My voice (cloned)" (`is_custom: true`); `voice_type` is `custom` while it is in use.
If the ElevenLabs key is removed, clones fall back to their prebuilt voice.

Usage is recorded as `TTS_REQUEST` with provider `elevenlabs` (character counts only).

## Consent and deletion

- Two consents: voice consent on the clone, plus the clone consent with the recordings.
- **DELETE** removes the voice at ElevenLabs (`DELETE /v1/voices/{id}`; already gone counts
  as deleted) and clears it here.
- **Withdrawing voice consent** or **deleting the clone** also deletes the cloned voice at
  ElevenLabs.
- Deletion never waits on the provider: if ElevenLabs can't be reached, the voice is
  cleared here and a warning with the voice id is logged, so an admin can delete it in the
  ElevenLabs dashboard (there is no automatic retry).
- Creating a new cloned voice replaces the old one (the old one is deleted at ElevenLabs).
- Keys, audio and text are never logged or returned.

## Recording tips (show these to users)

- A quiet room, no music or TV, and no echo (a small furnished room is better than a hall).
- 1–2 minutes in total works best (minimum 30 seconds).
- Speak naturally, the way you want the clone to sound, in the language(s) it will speak.
- Only one speaker. Keep the phone or microphone at the same distance.
- "Remove background noise" helps with a noisy recording, but can reduce quality on a
  clean one.

## Setup and costs

1. Create an ElevenLabs account with a plan that includes Instant Voice Cloning
   (Starter or higher). Free plans can't clone voices.
2. Create an API key (Profile → API keys) and set it in `.env` (never commit it):

   ```
   ELEVENLABS_API_KEY=...
   ELEVENLABS_MODEL=eleven_v3
   ELEVENLABS_API_URL=https://api.elevenlabs.io
   VOICE_CLONE_MIN_SECONDS=30
   VOICE_CLONE_MAX_SECONDS=300
   VOICE_CLONE_MAX_FILES=5
   ```
3. Restart the backend. `GET /api/mobile/config` then reports `voice.voice_cloning: true`.

ElevenLabs bills speech by characters from the plan's monthly credits; every spoken answer
with a cloned voice uses credits (cached replies are reused, not paid twice). Plans also limit
how many cloned voices an account can hold. When the quota runs out, cloning shows a
"usage limit" message and spoken answers fail with a safe error (the text answer still
arrives).

## Languages

`eleven_v3` speaks 70+ languages, including **Urdu** and English, with the cloned voice.
The clone's voice language (`en`/`ur`), or Urdu detected from Arabic script in the answer,
is sent as `language_code`. A voice cloned from English recordings can still speak Urdu,
but recording in the language the clone will mostly speak sounds most natural.
`eleven_flash_v2_5` is faster (lower latency for live calls) but supports fewer languages.
