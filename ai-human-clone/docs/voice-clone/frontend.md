# Your own voice (voice clone): frontend notes

The clone can speak with the owner's own voice (ElevenLabs Instant Voice Cloning). Because chat
answers, avatar videos and live video calls all take their audio from the clone's text-to-speech,
turning the cloned voice on is all the realistic face needs to speak with your voice too.

Where: **Clone → Voice Settings → "My own voice"** (`/clone/{id}/voice#my-voice`).

## Before you start

- The server needs `ELEVENLABS_API_KEY`. Without it the section shows
  "Voice cloning isn't set up on this server (ELEVENLABS_API_KEY)."
- Voice consent on the clone must be on (the "Voice Consent" card on the same page).
- Your plan must include voice cloning (if billing is on).

## How to record a good sample

- Record **1–2 minutes** of natural speech in total (the server accepts 30 s to 5 min by default,
  `VOICE_CLONE_MIN_SECONDS` / `VOICE_CLONE_MAX_SECONDS`).
- Use a **quiet room**. Only you should be speaking: no music, TV, echo or other voices.
- Speak the language(s) your clone will speak (Urdu and/or English), at your normal pace and tone.
- You can record several short clips with the mic (up to 60 s each) and/or upload audio files
  (WebM, WAV, MP3, M4A, OGG), up to `VOICE_CLONE_MAX_FILES` (5) samples. Each clip can be played
  back or removed before you send anything.
- Not sure what to say? Open "Suggested text to read aloud" for a short English and Roman Urdu paragraph.
- Only tick "Remove background noise" if the recording is noisy; on clean audio it can lower quality.

The bar under the samples shows the total length against the minimum and maximum, with text
(e.g. "0:45 recorded: 0:15 more needed"), so it never relies on colour alone. If the browser can't
read a file's length, the server checks it.

## Creating the voice

1. Tick "This is my own voice, or I have the speaker's explicit permission to clone it." (required).
2. Press **Create my voice**. You see upload progress, then "Creating your voice…" while ElevenLabs
   processes it (you can cancel during the upload). App updates wait until this finishes.
3. The status becomes **Ready**, or **Failed** with the reason. On failure your samples stay so you
   can fix them and try again.

## Privacy

- Recordings are sent to ElevenLabs to create the voice. **This app does not store them.**
- **Delete my cloned voice** deletes it from this app and from ElevenLabs. Withdrawing voice consent
  or deleting the clone also deletes it.
- **Replace (record again)** creates a new voice; the old one is deleted at ElevenLabs.

## Turning the cloned voice on and off

When the voice is ready, use the switch **Speak with my cloned voice**:

- On: chat answers, avatar videos and live calls speak with your voice.
- Off: the clone uses the selected AI voice again (your cloned voice is kept).

**Test my voice** plays a short English/Roman Urdu sentence in your cloned voice (Voice must be
enabled in Voice Settings). Spoken answers are always labelled "AI-generated voice", even when the
voice is cloned from you.

## Make it look and sound real (checklist)

The clone details page has a **Make it look and sound real** card with three checks. Each one links
to its setup page and names the server setting it needs:

| Check | Done when | Set up at | Server needs |
| --- | --- | --- | --- |
| Your own voice | Cloned voice is ready **and** switched on | Voice → My own voice | `ELEVENLABS_API_KEY` |
| Realistic avatar videos | Avatar settings report lipsync provider `fal` | Avatar | `FAL_API_KEY` + `LIPSYNC_PROVIDER=fal` |
| Live video call face | Simli live face is ready | Avatar → Live video call | `SIMLI_API_KEY` |

If one of the checks can't be loaded it shows "Unknown"; the page itself still works.

## Code map

- `frontend/lib/voiceCloneApi.ts`: `getVoiceClone`, `createVoiceClone` (multipart with upload progress), `setUseClonedVoice`, `deleteVoiceClone`.
- `frontend/types/voiceClone.ts`: `VoiceCloneStatus`.
- `frontend/lib/voiceClone.ts`: pure rules (durations, can-submit, file types, status labels, checklist), tested in `frontend/tests/voiceClone.test.ts`.
- `frontend/components/voice/VoiceCloneSection.tsx`: the "My own voice" card (mounted in `VoiceSettingsPanel.tsx`).
- `frontend/components/voice/RealismChecklist.tsx`: the checklist card (mounted in `components/clone/CloneDetails.tsx`).
- Availability: `voice.voice_cloning` from `/api/mobile/config` when present, else `available` from the clone status.
