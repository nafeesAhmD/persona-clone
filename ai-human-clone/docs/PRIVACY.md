# Privacy

What the platform stores about you, where it goes, how long it is kept, and what you can do
about it. This is a consent-based AI clone: it should only know what you deliberately give it.
The technical controls are described in [SECURITY.md](SECURITY.md).

> **Status.** Local/demo deployment. No analytics vendor, no advertising and no data broker are
> involved. Some features send data to third-party AI providers (below) — always because you
> turned that feature on.

## Principles

1. **Consent first.** A clone, its voice and its avatar each require an explicit confirmation
   before they can be used, and withdrawing consent turns the feature off.
2. **Data minimisation.** Public visitors are not identified; raw audio is not kept; server
   paths and internal ids are not exposed.
3. **You control the boundary.** Everything is private by default. You choose what becomes
   public, and changes take effect on the next question.
4. **No silent collection.** Long-term memories are only extracted when you click the button,
   and only ones you approve are ever used.

## What is stored

| Data | Where | Notes |
|---|---|---|
| Account: e-mail, username, full name, password **hash** (Argon2id) | PostgreSQL | Password is never stored in the clear. |
| Login state: failed count, lock-until, sessions-valid-after | PostgreSQL | Security bookkeeping only. |
| Clone profile: name, tagline, bio, profession, skills, language, style, personality, visibility | PostgreSQL | Used to build the clone's prompt. |
| Knowledge: uploaded files and their extracted text, chunks | File storage + PostgreSQL + Qdrant vectors | Owner-only unless a document is marked public. |
| Public knowledge and memories | PostgreSQL + Qdrant | Only what you marked public, for visitors. |
| Conversations and messages | PostgreSQL | Belong to the user who had them, not even the owner sees them. |
| Long-term memories | PostgreSQL + a separate Qdrant collection | Only **approved** ones get a vector. |
| Voice: transcripts and answer text; generated speech MP3s | PostgreSQL (text) + file storage (audio) | **Raw recordings are never stored.** Audio expires (default 24 h). |
| Avatar photo (re-encoded, metadata stripped), avatar videos | File storage | Videos expire (default 24 h); the photo stays until changed/removed. |
| Public visitor sessions | PostgreSQL | Only a SHA-256 hash of a random token, tied to one clone with a TTL. **No e-mail, account or IP.** |
| Usage events, analytics, security/error logs | PostgreSQL | Retention: security 30 d, errors 30 d, usage 90 d, analytics 90 d by default. |

**Not collected:** visitor IP addresses or e-mail, raw voice recordings, browser fingerprints,
advertising identifiers, or any data from your camera/microphone unless you press the button
that uses it. A self-view of your camera in a live call stays in your browser and is never sent.

## Where data goes (third parties)

Data leaves the server only for a feature you enabled:

| Feature | What is sent | To |
|---|---|---|
| Chat answers (text, voice, avatar, live call) | the prompt: clone settings + retrieved **public/your** knowledge and approved memories + recent messages | Anthropic (Claude) or Google (Gemini) |
| Speech-to-text / text-to-speech | the cleaned audio / the answer text | Google (Gemini) voice API |
| Cloned voice (when you configure it) | reference audio + text | ElevenLabs or your self-hosted voice-clone service |
| Avatar video (photo-realistic option) | the avatar photo and the spoken answer | fal.ai |
| Live video call | the avatar photo once (to build the face), then the spoken answers | Simli |
| Webhooks (developer platform) | the event payload you subscribed to | **your** endpoint |
| Embeddings | text, only if you choose a hosted embedding provider | that provider — the **default is local** (on the server, no third party) |

The default embedding model runs on the server, so knowledge does not leave for retrieval. The
same clone settings also reach the provider for every answer; provider data-handling terms
apply to what is sent. No provider key is ever sent to the browser. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the list of dependencies and models.

## Retention and deletion

| Data | Default retention |
|---|---|
| Generated voice audio | `VOICE_AUDIO_RETENTION_HOURS` = 24 h (hourly cleanup job) |
| Avatar videos | `VIDEO_RETENTION_HOURS` = 24 h (hourly cleanup job) |
| Public visitor sessions | `PUBLIC_SESSION_TTL_HOURS` = 24 h; also ends on "New conversation" |
| Security logs | `SECURITY_LOG_RETENTION_DAYS` = 30 |
| Error logs | `ERROR_LOG_RETENTION_DAYS` = 30 |
| Usage / analytics | `USAGE_LOG_RETENTION_DAYS` / `ANALYTICS_RETENTION_DAYS` = 90 |
| Conversations, knowledge, memories, clones | until you delete them |

Deleting a clone removes its documents, vectors, memories, conversations, avatars, videos and
its storage folder. **Delete all memories** removes that clone's memory rows and vectors only.
Deleting a document removes its file and vectors. Qdrant vectors are removed *before* the row
is committed, so a failure leaves neither orphaned.

## Your controls

- **See and edit** your profile, clones, knowledge and memories in the UI.
- **Delete** individual memories, documents, conversations, clones; or clear all of a clone's
  memories with a confirmation dialog.
- **Choose visibility** per document and memory (private/public) and per clone
  (private/unlisted/public), and turn public chat, public voice and public avatar on or off.
- **Withdraw consent** for voice or avatar, which turns the feature off and (for avatars) removes
  the live face.

**Gaps (honest):** there is no single "download everything" export and no self-service "delete
my account" button yet. To remove a whole account, delete its clones and memories in the UI, or
ask the operator/admin (who can disable the account). These are tracked as improvements in
[FINAL_RELEASE_AUDIT.md](FINAL_RELEASE_AUDIT.md).

## Content generated by or about other people

The platform is meant for **your own** profile, knowledge, voice and image. Uploading someone
else's documents, voice or photograph requires that you have their permission — the UI asks you
to confirm this for voice and avatars. Every clone, voice answer and avatar video is labelled as
AI-generated, and the clone is instructed to present itself as an AI representation, not the
real person. Do not use it to impersonate or deceive.

## Children

The platform is not directed at children and collects no age information.

## Contact

This is a local/demo project without a data-protection officer. For privacy questions, use the
project's issue tracker. Do not put real personal data in a public issue.
