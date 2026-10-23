# Personal voice clone + realistic avatar: contract (backend ↔ frontend)

Goal: the clone speaks with the owner's OWN voice (ElevenLabs Instant Voice Cloning), and
the realistic face (Simli live call / fal Fabric videos, already built) lip-syncs that voice.
Because live calls and avatar videos already take their audio from the clone's TTS, using
the cloned voice for TTS is all the face needs.

## Backend (lead already added)
- clone_profiles: voice_clone_id, voice_clone_status (none|processing|ready|failed),
  voice_clone_error, voice_clone_consent_at, use_cloned_voice (migration 0020_voice_clone).
- Settings: ELEVENLABS_API_KEY (empty = cloning unavailable), ELEVENLABS_MODEL (eleven_v3),
  ELEVENLABS_API_URL, VOICE_CLONE_MIN_SECONDS (30), VOICE_CLONE_MAX_SECONDS (300),
  VOICE_CLONE_MAX_FILES (5).

## API (owner only: clone_service.get_managed_clone), all under /api/clones/{clone_id}/voice/clone
- GET  → VoiceCloneStatus
  {available: bool (key set), status: "none"|"processing"|"ready"|"failed", error: str|null,
   use_cloned_voice: bool, consent_at: datetime|null, provider: "elevenlabs"|null,
   min_seconds, max_seconds, max_files, model: str}
- POST (multipart): files=[audio, 1..max_files] (WebM/WAV/MP3/M4A/OGG, each ≤ MAX_AUDIO_SIZE_MB),
  consent=true (required: "This is my own voice, or I have the speaker's permission to clone it"),
  remove_background_noise=true|false (optional) → 201 VoiceCloneStatus (status ready, or failed with error)
  - checks total duration between min and max seconds (400 otherwise)
  - replaces an existing cloned voice (deletes the old one at ElevenLabs)
  - requires voice consent already given on the clone (403 otherwise)
  - recordings are never stored (only sent to ElevenLabs)
- PATCH {use_cloned_voice: bool} → VoiceCloneStatus (only when status ready)
- DELETE → 204: deletes the voice at ElevenLabs and clears the fields (use_cloned_voice false)
- Withdrawing voice consent (existing PATCH voice settings voice_consent_given=false) or deleting
  the clone also deletes the cloned voice at ElevenLabs.
- POST /api/clones/{clone_id}/voice/test {text} (existing) speaks with the cloned voice when
  use_cloned_voice is on — so the frontend's "Test voice" plays the owner's own voice.
- GET /api/clones/{clone_id}/voice/settings (existing) adds: voice_type "custom" when the cloned
  voice is in use (already a field), and voice_clone: VoiceCloneStatus (embedded).

## Disclosure
Spoken answers stay labelled "AI-generated voice" in the UI even when cloned from the owner.
