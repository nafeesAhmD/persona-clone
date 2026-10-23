# Third-party notices

Key components this project uses and their licenses. Python and npm license fields were read from
the installed package metadata (`importlib.metadata`, `node_modules/*/package.json`) on
2026-10-13; model and container licenses come from their published model cards/images. This is a
summary, not legal advice: the full license texts ship with each package.

## Backend (Python, `backend/requirements.txt`)

| Package | Version | License |
|---|---|---|
| fastapi | 0.141.1 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| pydantic / pydantic-settings | 2.14.0 / 2.15.0 | MIT |
| SQLAlchemy | 2.1.1 | MIT |
| alembic | 1.20.0 | MIT |
| psycopg (binary) | 3.3.6 | **LGPL-3.0-only** (used unmodified as a library) |
| qdrant-client | 1.19.1 | Apache-2.0 |
| fastembed (+ onnxruntime 1.31.0) | 0.8.1 | Apache-2.0 (onnxruntime: MIT) |
| anthropic | 1.9.0 | MIT |
| google-genai | 2.25.0 | Apache-2.0 |
| PyJWT | 2.15.1 | MIT |
| argon2-cffi | 25.1.0 | MIT |
| email-validator | 2.3.0 | Unlicense |
| pypdf | 6.19.0 | BSD-3-Clause |
| python-docx | 1.2.0 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| av (PyAV, bundles FFmpeg libraries) | 19.0.0 | BSD-3-Clause (bundled FFmpeg: LGPL) |
| opencv-python-headless | 4.14.0.94 | Apache-2.0 |
| httpx | 0.28.1 | BSD-3-Clause |
| numpy | 2.5.4 | BSD-3-Clause (and bundled permissive licenses) |

## Frontend (npm, `frontend/package.json`)

| Package | Version | License |
|---|---|---|
| next | 16.3.7 | MIT |
| react / react-dom | 19.3.0 | MIT |
| simli-client | 3.0.2 | MIT |
| qrcode | 1.5.4 | MIT |
| tailwindcss | 4.3.3 | MIT |
| typescript (dev) | 5.9.3 | Apache-2.0 |
| eslint (dev) | 9.39.5 | MIT |

## Models

| Model | Used by | License / terms |
|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | embeddings (fastembed) | Apache-2.0 |
| ResembleAI Chatterbox Multilingual (`chatterbox-tts` 0.1.7) | self-hosted voice clone (default) | MIT; every output carries an inaudible Perth watermark |
| k2-fsa OmniVoice | optional GPU engine in `voice-clone/` | code Apache-2.0, **weights CC-BY-NC — personal / non-commercial use only**; do not use it for a commercial deployment |
| Higgs Audio v2 tokenizer (pulled by OmniVoice) | OmniVoice | see its model card before redistribution (not verified here) |
| openai/whisper-large-v3-turbo (pulled by OmniVoice only when no transcript exists) | OmniVoice | MIT |

## Containers and infrastructure

| Image | License |
|---|---|
| postgres:16-alpine | PostgreSQL License |
| qdrant/qdrant | Apache-2.0 |
| caddy:2-alpine (production proxy) | Apache-2.0 |
| python:3.12-slim, node:22-alpine | Python Software Foundation License / MIT (plus OS packages) |

## External services (not open source; used only when keys are configured)

Anthropic Claude, Google Gemini, ElevenLabs, Simli and fal.ai are used under their own terms of
service and usage policies. Voice and face cloning additionally require the consent of the person
being cloned (enforced in the app as owner consent flags).
