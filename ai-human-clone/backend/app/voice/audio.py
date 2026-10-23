"""Audio validation, normalisation and encoding (PyAV, which bundles FFmpeg).

An upload is accepted only if its extension, its declared MIME type and its
actual bytes (magic numbers) all agree on the same format, it is within
MAX_AUDIO_SIZE_MB and MAX_AUDIO_DURATION_SECONDS, and it really decodes as
audio. It is then re-encoded to 16 kHz mono WAV, so providers only ever
receive clean audio produced by us, never the raw upload.
"""

import io
import logging
import wave
from pathlib import PurePath

import av

from app.core.config import get_settings
from app.voice.base import AudioClip, InvalidAudioError

logger = logging.getLogger(__name__)

TARGET_RATE = 16_000
MIN_DURATION_SECONDS = 0.3

# format -> (file extensions, MIME types, PyAV container names)
_FORMATS: dict[str, tuple[set[str], set[str], set[str]]] = {
    "webm": ({"webm"}, {"audio/webm", "video/webm"}, {"matroska", "webm"}),
    "wav": ({"wav"}, {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}, {"wav"}),
    "mp3": ({"mp3"}, {"audio/mpeg", "audio/mp3"}, {"mp3"}),
    "mp4": ({"m4a", "mp4"}, {"audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac", "video/mp4"}, {"mov", "mp4", "m4a"}),
    "ogg": ({"ogg", "oga", "opus"}, {"audio/ogg", "audio/opus"}, {"ogg"}),
}
ALLOWED_EXTENSIONS = sorted(ext for exts, _, _ in _FORMATS.values() for ext in exts)
UNSUPPORTED = "Unsupported audio format. Use WebM, WAV, MP3, M4A or OGG."


def sniff_format(data: bytes) -> str | None:
    """The format the bytes actually are, from their magic numbers."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[4:8] == b"ftyp":
        return "mp4"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def _format_of_name(filename: str | None) -> str | None:
    extension = PurePath(filename or "").suffix.lower().lstrip(".")
    return next((fmt for fmt, (exts, _, _) in _FORMATS.items() if extension in exts), None)


def _format_of_mime(content_type: str | None) -> str | None:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    return next((fmt for fmt, (_, mimes, _) in _FORMATS.items() if mime in mimes), None)


def max_audio_bytes() -> int:
    return get_settings().max_audio_size_mb * 1024 * 1024


def too_large_message() -> str:
    return f"The recording is too large. Maximum size is {get_settings().max_audio_size_mb} MB."


def _measure_duration(container: "av.container.InputContainer", stream: "av.audio.stream.AudioStream") -> float:
    # MediaRecorder's WebM has no duration header, so read packet timestamps
    # (demuxing only, no decoding).
    end = 0.0
    for packet in container.demux(stream):
        if packet.pts is not None and packet.time_base is not None:
            end = max(end, float((packet.pts + (packet.duration or 0)) * packet.time_base))
    return end


def validate_and_normalise(
    data: bytes, filename: str | None, content_type: str | None, *, max_seconds: float | None = None
) -> AudioClip:
    """Check an upload and return it as 16 kHz mono WAV. Raises InvalidAudioError.

    `max_seconds` overrides MAX_AUDIO_DURATION_SECONDS (voice-clone samples may be longer).
    """
    settings = get_settings()
    if not data:
        raise InvalidAudioError("The recording is empty.")
    if len(data) > max_audio_bytes():
        raise InvalidAudioError(too_large_message(), status_code=413)

    by_name, by_mime, by_bytes = _format_of_name(filename), _format_of_mime(content_type), sniff_format(data)
    if by_name is None or by_mime is None:
        raise InvalidAudioError(UNSUPPORTED, status_code=415)
    if not (by_name == by_mime == by_bytes):
        raise InvalidAudioError("The file's content doesn't match its audio type.", status_code=415)

    max_seconds = max_seconds or settings.max_audio_duration_seconds
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            names = set(container.format.name.split(","))
            if not names & _FORMATS[by_bytes][2] or not container.streams.audio:
                raise InvalidAudioError("The file doesn't contain audio.", status_code=415)
            duration = _measure_duration(container, container.streams.audio[0])
        if duration > max_seconds:
            raise InvalidAudioError(f"The recording is too long. Maximum length is {max_seconds:g} seconds.", 413)

        pcm = bytearray()
        max_samples = int((max_seconds + 1) * TARGET_RATE)
        with av.open(io.BytesIO(data), mode="r") as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_RATE)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    pcm += bytes(converted.planes[0])[: converted.samples * 2]
                if len(pcm) > max_samples * 2:  # the header lied about the length
                    raise InvalidAudioError(f"The recording is too long. Maximum length is {max_seconds:g} seconds.", 413)
            for converted in resampler.resample(None):
                pcm += bytes(converted.planes[0])[: converted.samples * 2]
    except InvalidAudioError:
        raise
    except Exception as exc:  # noqa: BLE001 - FFmpeg errors vary; never echo them
        logger.info("Rejected unreadable audio upload (%s)", type(exc).__name__)
        raise InvalidAudioError("The recording couldn't be read. Please record again.") from exc

    seconds = len(pcm) / 2 / TARGET_RATE
    if seconds < MIN_DURATION_SECONDS:
        raise InvalidAudioError("The recording is too short. Hold the button a little longer.")
    return AudioClip(wav=pcm_to_wav(bytes(pcm), TARGET_RATE), duration_seconds=round(seconds, 2))


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def encode_mp3(data: bytes) -> bytes:
    """Re-encode any readable audio (e.g. a provider's WAV) as mono MP3 for browsers."""
    output = io.BytesIO()
    with av.open(io.BytesIO(data), mode="r") as source, av.open(output, mode="w", format="mp3") as target:
        rate = source.streams.audio[0].rate or 24_000
        stream = target.add_stream("libmp3lame", rate=rate)
        stream.layout = "mono"
        stream.bit_rate = 64_000
        resampler = av.AudioResampler(format=stream.format.name, layout="mono", rate=rate)
        for frame in source.decode(audio=0):
            for converted in resampler.resample(frame):
                for packet in stream.encode(converted):
                    target.mux(packet)
        for converted in resampler.resample(None):
            for packet in stream.encode(converted):
                target.mux(packet)
        for packet in stream.encode(None):
            target.mux(packet)
    return output.getvalue()
