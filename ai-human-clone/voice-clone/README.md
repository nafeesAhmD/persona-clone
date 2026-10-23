# Voice clone service

A small internal HTTP service that clones a voice from a short recording and
speaks text in that voice. It wraps the open-source
[Chatterbox Multilingual](https://github.com/resemble-ai/chatterbox) model by
Resemble AI (`chatterbox-tts` 0.1.7) and runs on the CPU.

The backend calls it at `http://voice-clone:8100` inside the Compose network.
It has no published ports.

## License and watermark

- Chatterbox is MIT licensed (code and weights).
- Every generated clip carries an inaudible **Perth watermark** added by the
  model. It marks the audio as AI-generated and cannot be turned off here.
- Only clone voices with the speaker's consent.

## Resources

| | |
|---|---|
| Model | ~500M parameters, CPU (`device=cpu`) |
| RAM | ~3–4 GB while generating; Compose sets `mem_limit: 6g` |
| Image | ~2–3 GB (CPU-only torch 2.6.0, no CUDA, no gradio) |
| First start | downloads ~3 GB of weights from Hugging Face (`ResembleAI/chatterbox`: `t3_mtl23ls_v2.safetensors`, `s3gen.pt`, `ve.pt`, tokenizer, `conds.pt`) into the `voice_clone_models` volume. Later starts reuse it. |
| Speed | slow on a laptop CPU: several seconds of compute per second of speech. Requests run one at a time. |

## Run

```sh
# Optional: shared secret the backend must send as X-Service-Token
# (set the same VOICE_CLONE_SERVICE_TOKEN for backend and voice-clone, e.g. in .env)
docker compose --profile voice-clone build voice-clone
docker compose --profile voice-clone up -d voice-clone
docker compose logs -f voice-clone      # watch the first-run model download
```

A plain `docker compose up` (without the profile) does not build or start this
service.

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `VOICE_CLONE_SERVICE_TOKEN` | empty | If set, every request except `GET /health` needs header `X-Service-Token` |
| `SYNTH_TIMEOUT_SECONDS` | 240 | Max time per `/synthesize` request (queue + generation) → 504 |
| `MODEL_WAIT_SECONDS` | 30 | How long a request waits for the model to finish loading → 503 |
| `MAX_UPLOAD_MB` | 50 | Max upload size for `/voices` → 413 |
| `MAX_QUEUED_SYNTHESES` | 4 | Pending + running syntheses before 503 "busy" |
| `TORCH_NUM_THREADS` | torch default | CPU threads for generation |
| `VOICE_DATA_DIR` | `/data/voices` | Where reference clips are stored |

## API

Errors are JSON: `{"detail": ...}`.

- `GET /health` → `{"status": "ok", "model_loaded": bool, "device": "cpu"}`.
  The model loads in a background thread at startup.
- `POST /voices` (multipart, field `files`, one or more WAV files; FLAC/OGG/MP3
  also work if libsndfile decodes them) → `201 {"voice_id": "<32 hex>", "reference_seconds": float}`.
  Silence is trimmed, the files are joined, and at most 20 s are kept (if there
  is more, the 15 s window with the most speech). Saved as 24 kHz mono WAV at
  `/data/voices/<voice_id>.wav`. Less than 5 s of sound → 400; undecodable → 400;
  over `MAX_UPLOAD_MB` → 413.
- `DELETE /voices/{voice_id}` → 204; unknown → 404; malformed id → 400.
- `POST /synthesize` `{"voice_id", "text" (1–1000 chars), "language_id"}` →
  `200 audio/wav` (mono 16-bit, 24 kHz). Unsupported language → 400, unknown
  voice → 404, bad text length → 422, model still loading → 503, timeout → 504.
  Long text is split into sentences that are generated one by one and joined.

Supported `language_id`: `ar da de el en es fi fr he hi it ja ko ms nl no pl pt ru sv sw tr zh`.
(Urdu is not supported; Hindi `hi` is the closest.)

Logs contain sizes and timings only, never the text.

## Tests

The tests use a fake model, so they need neither torch nor the weights:

```sh
docker run --rm -v "$PWD/voice-clone:/src:ro" python:3.11-slim sh -c \
  "cp -r /src /w && cd /w && pip install -q -r requirements-test.txt && python -m pytest -q -p no:cacheprovider"
```
