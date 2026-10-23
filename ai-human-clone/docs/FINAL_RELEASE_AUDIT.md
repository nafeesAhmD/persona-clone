# Final release audit — Phase 20

Date: 2026-10-15 · Auditor: Phase 20 QA/security pass · Environment: Windows,
Python 3.12.10 (backend venv), Node 24.20.0 / npm 11.19.0, tests on SQLite with fake AI
providers (no API keys, no paid calls).

This is the honest record of what was checked, what was fixed, what is knowingly left, and
whether the project is ready to release. Paired documents: [SECURITY.md](SECURITY.md),
[PRIVACY.md](PRIVACY.md), [eval/RESULTS.md](eval/RESULTS.md).

## Verdict

**Ready as a local / self-hosted demo. Not yet ready for an unattended public production
launch.** The application code, tests and deployment tooling are in good shape and every
automated check passes, but it has never been deployed publicly, has had no
penetration test, relies on third-party AI providers that were not exercised here, and keeps
some per-process state that assumes a single backend process. The items below are the
condition for a "production" stamp.

## What was verified

### Backend test suite

Command (from `backend/`):

```
.\.venv\Scripts\python.exe -m pytest -q --junitxml=final.xml
```

Two consecutive full runs after the fixes in this audit:

| Run | Result | Time |
|---|---|---|
| 1 | **1022 passed, 0 failed, 0 errors, 0 skipped** | 313.99 s |
| 2 | **1022 passed, 0 failed, 0 errors, 0 skipped** | 382.84 s |

The suite uses SQLite and fake LLM/TTS/STT/avatar providers, so it is deterministic, offline
and free. It covers auth/permissions/IDOR, RAG grounding and injection, memory safety, voice
and audio validation, avatars and jobs, live calls, public/private boundaries, organizations,
billing, developer keys and webhooks, the AI agent, marketplace, admin and production
settings.

Before this audit the suite was **flaky**: three different ordering-sensitive tests failed on
different runs (`test_chat.py::test_history_is_limited`,
`test_agent_tools.py::test_conversation_context_reads_only_own_conversation`,
`test_voice.py::test_spoken_messages_are_marked_as_voice`). Root cause and fix are in
[Fixes made](#fixes-made-in-this-audit). After the fix, both runs above were clean.

### Frontend checks

From `frontend/`:

| Check | Command | Result |
|---|---|---|
| Lint | `npm run lint` | exit 0 (no findings) |
| Types | `npm run typecheck` | exit 0 |
| Unit tests | `npm test` | **152 passed, 0 failed**, 152 tests |
| Production build | `npm run build` | exit 0 (all routes built) |
| Internal links | `npm run check:links` | exit 0 — 52 routes, 169 internal link targets |

### Security review

The backend was read against its threat model (see [SECURITY.md](SECURITY.md)). Three review
tracks covered (1) authentication, sessions and API keys, (2) public/private retrieval
isolation, prompt injection, memory safety, uploads and consent, and (3) the AI agent,
webhooks, realtime voice, marketplace and organizations. Track (2) found no issues. The
confirmed findings and their disposition are below.

### Clone-behaviour evaluation

`docs/eval/RESULTS.md` records a real run (2026-10-13, configured Gemini model, fictional QA
clone): literal counts **PASS 10, FAIL 4, BLOCKED 0, ERROR 0, NOT TESTED 1**. The four
failures are analysed there: two are real retrieval weaknesses on the default embedding model
(a short/indirect question missed the right chunk; cross-lingual Urdu→English retrieval), one
is a test-setup artefact (clone language overrides the user's), and one is the documented
`MAX_CONVERSATION_MESSAGES` window. Injection cases (E10, E11) and the public/private
boundary (E13) passed.

## Fixes made in this audit

| # | Issue | Fix | Files |
|---|---|---|---|
| 1 | **Flaky message ordering.** Messages are ordered by `created_at, id`, but `id` is a random UUID4 (`app/db/base.py:13`). When two inserts land on the same clock tick (rapid calls, or a coarse OS clock), the tie is broken randomly and history order can shuffle — which made three tests fail intermittently. | `conversation_service.add_message` now keeps `created_at` strictly increasing within a conversation (`max(created_at) + 1µs` on collision), so ordering is deterministic. Improves production correctness too. | `backend/app/services/conversation_service.py` |
| 2 | **Organization member list exposed PII of removed/suspended members.** Any active member (including a `viewer`) received the e-mail and full name of members who had been removed or suspended. | The list still returns the membership row (so the owner/admin can act on the id) but only includes `email`/`full_name` while `status == "active"`. | `backend/app/org/routes/members.py` |
| 3 | **Windows test collection error.** `test_voice.py::test_invalid_audio_is_rejected` parametrised on raw WAV bytes, making pytest build multi-KB test ids → `ValueError: the environment variable is longer than 32767 characters` on Windows. | Added explicit short `ids=[...]`. | `backend/tests/test_voice.py` |
| 4 | **README pointed at three missing documents** (`docs/SECURITY.md`, `docs/PRIVACY.md`, `docs/FINAL_RELEASE_AUDIT.md`). | Wrote all three. | `docs/` |

## Findings accepted (not fixed) with rationale

Full detail in [SECURITY.md → Accepted risks](SECURITY.md#accepted-risks-and-known-limitations).

| # | Finding | Severity | Disposition |
|---|---|---|---|
| A1 | Logout clears the cookie but does not revoke the stateless JWT. | Low | Accepted. Needs a server-side revocation store this single-process deployment lacks. Password change *does* revoke. |
| A2 | No absolute session lifetime (`/me` slides expiry). | Medium | Accepted as a UX choice; 30-min idle timeout + HttpOnly/SameSite cookie. Absolute cap is a planned addition. |
| A3 | Account lockout returns a distinct `429`, hinting that an account exists. | Medium | Accepted. The lockout is a control and is tested; login is rate limited per address and e-mail. |
| A4 | Password-change cut-off has 1-second granularity. | Low | Accepted. Window ≤ 1 s against a 30-min token; fixing needs per-token ids. |
| C1 | Inbound billing webhook verifies no signature. | Low | Accepted. It is a no-op stub; no payment provider is wired up. Verify the provider's signature when one is added. |
| — | No self-service account deletion / data export. | — | Documented in [PRIVACY.md](PRIVACY.md); whole-account removal is an operator/admin action today. |

No finding was fixed by weakening a control, and none is hidden: every accepted item is listed
publicly in `SECURITY.md`.

## Known limitations (unchanged)

- **Never deployed publicly; no penetration test.** All evidence is from code reading and
  automated tests.
- **Single backend process.** Rate limits, real-time voice sessions, marketplace view
  de-duplication and background job runners are per-process; more than one worker breaks them
  (the app warns). See [SCALING_GUIDE.md](SCALING_GUIDE.md).
- **Third-party AI providers not exercised here.** Claude, Gemini (chat/voice), ElevenLabs,
  fal.ai and Simli were not called in this audit (no keys / cost). Their error paths are
  covered by fakes in the tests; real behaviour depends on the providers.
- **Default embedding model is weak on Roman Urdu** and on short/indirect questions (see the
  eval failures). This is a quality limit, not a security one.
- **Cross-browser / real-device QA not done.** The prior track's browser pass was Chromium at
  1366 px and 390 px only.
- **No OCR** for scanned PDFs, and **no group chat / conversation sharing** (by design).

## What was not re-run in this audit

- `scripts/e2e_journey.py` (full journey + restart persistence) and `scripts/eval_clone.py`
  (behaviour eval + latency) require a **live Docker stack** with provider keys. The eval
  results in `docs/eval/RESULTS.md` are from the earlier Phase 20 track; the journey script is
  provided for an operator to run against a running stack.
- Backup/restore drill: covered by `docs/BACKUP_AND_RESTORE.md` from the Phase 19 track, not
  re-exercised here.

## How to reproduce

```powershell
# Backend (from backend/)
.\.venv\Scripts\python.exe -m pytest -q --junitxml=final.xml

# Frontend (from frontend/)
npm run lint; npm run typecheck; npm test; npm run build; npm run check:links
```

Expected: backend `1022 passed`; frontend all exit 0 and `152 passed`.

## Release checklist

- [x] Backend test suite green (1022/1022, two runs)
- [x] Frontend lint, types, tests, build, links green
- [x] Security review complete; issues fixed or documented
- [x] `SECURITY.md`, `PRIVACY.md`, `FINAL_RELEASE_AUDIT.md` present
- [x] Production startup safety checks in place
- [ ] Public deployment + HTTPS behind Caddy — **not done**
- [ ] Penetration test — **not done**
- [ ] Real provider keys exercised end-to-end — **not done**
- [ ] Absolute session lifetime / server-side token revocation — **planned**

## Sign-off

Automated verification passes and the code is fit for a local demo or a controlled
self-hosted deployment. A public production launch should first address the four unchecked
boxes above. The accepted risks (A1–A4, C1) are low-to-medium and individually documented with
their reasoning, so they can be consciously accepted by whoever operates the release.
