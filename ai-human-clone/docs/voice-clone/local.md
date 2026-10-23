# Free voice cloning on your own server (Chatterbox)

AI Human Clone can clone the owner's voice without a paid ElevenLabs plan. It uses
**Chatterbox Multilingual** (Resemble AI, open source, MIT licence), which runs in its
own Docker service next to the backend. Recordings and answer text never leave your
server.

Everything else works as with ElevenLabs (see [backend.md](backend.md)): the same
"My own voice" page, the same two consents, the same API, and the cloned voice is used
for voice chat, "Play", the voice test, public voice, talking-avatar videos and live
calls. Spoken answers are still labelled "AI-generated voice".

## Start it

1. Start the voice-clone service (it is behind a Compose profile, so it only runs when
   you ask for it):

   ```bash
   docker compose --profile voice-clone up -d voice-clone
   ```

   The first start downloads the model (a few GB) into a Docker volume; later starts
   reuse it. `GET http://voice-clone:8100/health` reports `"model_loaded": true` when it
   is ready.

2. Point the backend at it in `.env` and restart the backend:

   ```
   VOICE_CLONE_PROVIDER=local          # or auto
   LOCAL_VOICE_CLONE_URL=http://voice-clone:8100
   VOICE_CLONE_SERVICE_TOKEN=          # optional shared secret, same value in the service
   LOCAL_VOICE_CLONE_TIMEOUT_SECONDS=300
   ```

   `VOICE_CLONE_PROVIDER` chooses where **new** voices are cloned:

   | Value | Meaning |
   |---|---|
   | `auto` (default) | ElevenLabs if `ELEVENLABS_API_KEY` is set, else the local service if `LOCAL_VOICE_CLONE_URL` is set, else off |
   | `local` | Always the local service |
   | `elevenlabs` | Always ElevenLabs |
   | `none` | Cloning off; clones use their prebuilt voices |

3. `GET /api/mobile/config` now reports `voice.voice_cloning: true`, and the
   "My own voice" page explains that recordings are processed on this server.

## How the backend uses it

- Each recording is checked as usual (type, size, length; 30–300 s in total), converted
  to mono WAV and sent to `POST /voices`. Only the returned voice id is stored, as
  `local:<id>` (ElevenLabs voices are stored as `elevenlabs:<id>`; older ids without a
  prefix are ElevenLabs). **The recordings are not stored by the backend.** The service
  keeps a short reference clip for the voice until the voice is deleted.
- Speech goes to `POST /synthesize` in pieces of up to 400 characters (split at sentence
  ends); the WAV pieces are joined and stored as MP3 like other speech.
- Deleting the cloned voice, withdrawing voice consent or deleting the clone calls
  `DELETE /voices/{id}` at the provider that made the voice, even if
  `VOICE_CLONE_PROVIDER` has changed since. If a service is down, the voice is cleared
  in the app, kept in `pending_voice_deletions` and retried every hour until every
  service has deleted it (a warning with the id is logged too).
- If the service is removed from `.env`, clones fall back to their prebuilt voice.
- `X-Service-Token` is sent on every call when `VOICE_CLONE_SERVICE_TOKEN` is set. The
  token, audio and text are never logged.

## Resources and speed

- **CPU only** works, but is slow: expect **5–30+ seconds per sentence** (more on small
  machines). A long answer can take a few minutes, so the backend waits up to
  `LOCAL_VOICE_CLONE_TIMEOUT_SECONDS` (300 s) instead of `VOICE_TIMEOUT_SECONDS`.
  Voice chat still returns the text answer at once if speech fails or times out.
- Plan for about **4–6 GB of RAM** for the model and a few GB of disk for the model files.
- A GPU makes it many times faster. Live video calls need fast speech, so on a CPU-only
  server they will feel slow with the cloned voice; turn the cloned voice off for live
  calls if needed, or use ElevenLabs.
- While the model is loading, cloning and speech return a friendly "still starting" error
  (503); try again a minute later.

## Languages and Urdu

Chatterbox speaks: ar, da, de, el, en, es, fi, fr, he, hi, it, ja, ko, ms, nl, no, pl,
pt, ru, sv, sw, tr, zh. **It has no Urdu.** Because spoken Urdu and Hindi are very close:

- Answers in **Urdu script** are rewritten in Devanagari (`app/voice/transliterate.py`)
  and spoken with the **Hindi** model. The rewrite is approximate (Urdu script usually
  leaves out short vowels), so some words sound slightly off and the accent is Hindi.
- **Roman Urdu** ("aap kaise hain") is detected by common Urdu words (`app/voice/roman_urdu.py`),
  rewritten in Devanagari (a word list plus letter rules, approximate) and spoken with the
  **Hindi** model too. One such word is enough when the clone's voice language is `ur` or `hi`;
  otherwise at least two and 20% of the words. Other Latin text is spoken as English.
- Other supported languages (by the clone's voice language) are passed through.

For natural Urdu, ElevenLabs (`eleven_v3`) is still the better choice.

## Watermark

Chatterbox adds Resemble AI's inaudible **Perth watermark** to everything it generates,
so the audio can later be identified as AI-made. It cannot be heard and survives MP3
encoding. This fits the app's rule that spoken answers are always disclosed as AI.

## Privacy

- Recordings and answer text are processed only on your server; nothing goes to an
  outside company.
- Two consents are needed, exactly as with ElevenLabs: voice consent on the clone, plus
  "This is my own voice, or I have the speaker's permission to clone it".
- Deleting the voice (or the clone, or withdrawing voice consent) deletes it from the
  voice-clone service too. If the Colab GPU is off at that moment, the delete is retried
  hourly; keep its URL in `.env` (as `LOCAL_VOICE_CLONE_URL` or the fallback) until the
  GPU has been started once more, or its copy on Google Drive is never removed.
- Only clone voices you have the right to use.

## Faster speech on a free Colab GPU

On a laptop CPU a few seconds of speech take 1-2 minutes. The same service runs on a free
Google Colab T4 GPU, where it is many times faster:

- `voice-clone/colab/voice_clone_gpu.ipynb` starts the service on the GPU and opens a public
  `https://*.trycloudflare.com` link (Cloudflare quick tunnel). The service token is required
  there: without it anyone with the link could use the voice. Voices are kept in Google Drive
  (`MyDrive/ai-clone-voices/<voice_id>.wav`), so they survive a new Colab session.
- `scripts/voice-gpu.ps1` (option 1) copies the notebook and the recorded voices to
  `Desktop\AI-Clone-GPU`, puts the token on the clipboard, checks the pasted link, sets
  `LOCAL_VOICE_CLONE_URL` to it and stops the laptop voice service (frees ~5 GB RAM).
  Option 2 switches back to `http://voice-clone:8100`.
- The model picks its device with `VOICE_CLONE_DEVICE` (`auto` by default: CUDA when there is
  a GPU, otherwise the CPU).
- The notebook embeds `app.py`, `model.py` and `audio.py`: after changing them run
  `python voice-clone/colab/build_notebook.py`.

Limits: free Colab sessions stop after some idle time or a few hours; then run the notebook
again and paste the new link (the script asks for it). A voice recorded while on Colab is
stored in Drive, not in the laptop service.

## Two engines, GPU first with laptop fallback

- `VOICE_CLONE_ENGINE` picks the model inside the service: `chatterbox` (default, MIT) or
  `omnivoice` (k2-fsa/OmniVoice: 600+ languages including Urdu, **CC-BY-NC weights:
  personal / non-commercial use only**, needs a GPU; on a laptop CPU it was 2-3x slower
  than Chatterbox). `GET /health` reports `engine`.
- OmniVoice needs the reference transcript: `<voice_id>.txt` if present, otherwise Whisper
  writes it on first use; the clone prompt is saved as `<voice_id>.omnivoice.pt` (both next to
  the WAV, deleted with the voice).
- `POST /voices` accepts an optional `voice_id` form field, so one voice lives on two services.
- Backend: with `LOCAL_VOICE_CLONE_FALLBACK_URL` set, speech goes to `LOCAL_VOICE_CLONE_URL`
  (the Colab GPU) first and falls back to the laptop when that is off or lacks the voice
  (or never connects), but not when it times out while speaking. A new voice is stored on
  both under one id; delete removes it from both, and stays pending until both have.
- With OmniVoice, Urdu script is sent as `ur`, and Roman Urdu is rewritten in Urdu script by
  Gemini (`pronounce.to_urdu_script`); Chatterbox keeps getting Devanagari as `hi`.
- The Colab notebook defaults to `ENGINE = "omnivoice"`; set `"chatterbox"` for the MIT model.
