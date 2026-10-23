"""Audio helpers: decoding uploads, building the reference clip, WAV encoding.

Only numpy + soundfile are required. ``soxr`` (installed in the Docker image
as a librosa dependency) is used for high-quality resampling when available;
otherwise a linear-interpolation fallback keeps the tests dependency-free.
"""

from __future__ import annotations

import io
import re

import numpy as np
import soundfile as sf

# Chatterbox's S3Gen decoder works at 24 kHz and resamples the reference to it.
REFERENCE_SAMPLE_RATE = 24_000
MIN_REFERENCE_SECONDS = 5.0
MAX_REFERENCE_SECONDS = 20.0
# When there is more voiced audio than MAX_REFERENCE_SECONDS, keep the most
# voiced window of this length.
TARGET_REFERENCE_SECONDS = 15.0

_FRAME_SECONDS = 0.02
_SILENCE_DB_BELOW_PEAK = 40.0
_ABS_SILENCE_RMS = 1e-4
_MAX_INNER_GAP_SECONDS = 0.3
_FILE_JOIN_GAP_SECONDS = 0.15


class AudioError(ValueError):
    """Raised for audio the service cannot use (maps to HTTP 400)."""


def decode_audio(data: bytes) -> tuple[np.ndarray, int]:
    """Decode WAV (or FLAC/OGG/MP3 when libsndfile supports it) to mono float32."""
    if not data:
        raise AudioError("empty audio file")
    try:
        samples, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception as exc:  # soundfile raises several error types
        raise AudioError("could not decode audio (send WAV)") from exc
    if samples.size == 0 or sr <= 0:
        raise AudioError("empty audio file")
    mono = samples.mean(axis=1).astype(np.float32)
    if not np.all(np.isfinite(mono)):
        mono = np.nan_to_num(mono, nan=0.0, posinf=0.0, neginf=0.0)
    return mono, int(sr)


def resample(samples: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    try:
        import soxr  # type: ignore

        return soxr.resample(samples, orig_sr, target_sr, quality="HQ").astype(np.float32)
    except ImportError:
        n_out = int(round(samples.size * target_sr / orig_sr))
        x_old = np.arange(samples.size, dtype=np.float64) / orig_sr
        x_new = np.arange(n_out, dtype=np.float64) / target_sr
        return np.interp(x_new, x_old, samples).astype(np.float32)


def _frame_rms(samples: np.ndarray, frame: int) -> np.ndarray:
    n_frames = samples.size // frame
    if n_frames == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: n_frames * frame].reshape(n_frames, frame)
    return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)).astype(np.float32)


def _voiced_mask(rms: np.ndarray) -> np.ndarray:
    if rms.size == 0:
        return np.zeros(0, dtype=bool)
    peak = float(rms.max())
    threshold = max(peak * 10 ** (-_SILENCE_DB_BELOW_PEAK / 20), _ABS_SILENCE_RMS)
    return rms > threshold


def _compact_silence(samples: np.ndarray, sr: int) -> np.ndarray:
    """Trim leading/trailing silence and shorten long internal pauses."""
    frame = max(1, int(sr * _FRAME_SECONDS))
    rms = _frame_rms(samples, frame)
    voiced = _voiced_mask(rms)
    if not voiced.any():
        return np.zeros(0, dtype=np.float32)
    max_gap = max(1, int(_MAX_INNER_GAP_SECONDS / _FRAME_SECONDS))
    first, last = int(np.argmax(voiced)), int(len(voiced) - np.argmax(voiced[::-1]) - 1)
    keep: list[np.ndarray] = []
    gap = 0
    for i in range(first, last + 1):
        if voiced[i]:
            gap = 0
        else:
            gap += 1
            if gap > max_gap:
                continue
        keep.append(samples[i * frame : (i + 1) * frame])
    return np.concatenate(keep).astype(np.float32)


def _best_window(samples: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    """Return the window of `seconds` with the most voiced energy."""
    win = int(seconds * sr)
    if samples.size <= win:
        return samples
    frame = max(1, int(sr * _FRAME_SECONDS))
    rms = _frame_rms(samples, frame)
    energy = np.where(_voiced_mask(rms), rms, 0.0).astype(np.float64)
    win_frames = max(1, win // frame)
    if energy.size <= win_frames:
        return samples[:win]
    csum = np.concatenate([[0.0], np.cumsum(energy)])
    scores = csum[win_frames:] - csum[:-win_frames]
    start = int(np.argmax(scores)) * frame
    return samples[start : start + win]


def build_reference(clips: list[tuple[np.ndarray, int]]) -> np.ndarray:
    """Combine uploaded clips into one clean reference at REFERENCE_SAMPLE_RATE."""
    sr = REFERENCE_SAMPLE_RATE
    gap = np.zeros(int(_FILE_JOIN_GAP_SECONDS * sr), dtype=np.float32)
    parts: list[np.ndarray] = []
    for samples, clip_sr in clips:
        compact = _compact_silence(resample(samples, clip_sr, sr), sr)
        if compact.size:
            if parts:
                parts.append(gap)
            parts.append(compact)
    combined = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    if combined.size < MIN_REFERENCE_SECONDS * sr:
        raise AudioError(
            f"not enough speech: need at least {MIN_REFERENCE_SECONDS:.0f} seconds of non-silent audio"
        )
    if combined.size > MAX_REFERENCE_SECONDS * sr:
        combined = _best_window(combined, sr, TARGET_REFERENCE_SECONDS)
    peak = float(np.max(np.abs(combined)))
    if peak > 0:
        combined = combined * (0.89 / peak)  # about -1 dBFS
    return combined.astype(np.float32)


def encode_wav(samples: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.clip(samples, -1.0, 1.0), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# --- text --------------------------------------------------------------------

_SENTENCE_END = re.compile(r"(?<=[.!?।॥。！？؟])\s+|(?<=[。！？])|\n+")
_MAX_CHUNK_CHARS = 250


def split_sentences(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Split text into sentence-sized chunks of at most ``max_chars`` characters.

    Short sentences are merged so that the model is not called for every
    fragment; overly long sentences are split at commas, then at spaces.
    """
    pieces = [p.strip() for p in _SENTENCE_END.split(text) if p and p.strip()]
    sentences: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            sentences.append(piece)
            continue
        current = ""
        for part in re.split(r"(?<=[,，、;:])\s*|\s+", piece):
            if not part:
                continue
            while len(part) > max_chars:  # no break point at all
                if current:
                    sentences.append(current)
                    current = ""
                sentences.append(part[:max_chars])
                part = part[max_chars:]
            candidate = f"{current} {part}".strip() if current else part
            if len(candidate) > max_chars:
                sentences.append(current)
                current = part
            else:
                current = candidate
        if current:
            sentences.append(current)

    chunks: list[str] = []
    for sentence in sentences:
        if chunks and len(chunks[-1]) + 1 + len(sentence) <= max_chars // 2:
            chunks[-1] = f"{chunks[-1]} {sentence}"
        else:
            chunks.append(sentence)
    return chunks
