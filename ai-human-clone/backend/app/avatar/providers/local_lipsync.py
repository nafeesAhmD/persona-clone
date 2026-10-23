"""Local, CPU-only lip-sync: avatar image + speech -> MP4 (H.264 + AAC).

How it works (no model download, no GPU, a few seconds per answer):
1. The speech is decoded and its loudness is measured per video frame; a
   smoothed, gated envelope becomes the mouth opening (0 = closed, 1 = wide).
2. For each frame the lower lip and jaw are moved down by that opening with an
   image warp (OpenCV remap): the chin stays put, the face below the mouth is
   compressed slightly, and the opening is filled with a dark mouth interior
   and a hint of teeth. A slow, subtle head motion keeps it from looking frozen.
3. Frames and audio are encoded with PyAV (bundled FFmpeg) as a web-friendly MP4.

It animates the mouth in sync with the speech, but it is not a learned
talking-head model: for photo-realistic results, use LIPSYNC_PROVIDER=http
with a GPU server running e.g. Wav2Lip, SadTalker or MuseTalk.
"""

import logging
import math

import av
import numpy as np

from app.avatar.base import AvatarError, LipSyncProvider, LipSyncRequest, ProgressCallback

logger = logging.getLogger(__name__)

AUDIO_RATE = 24_000
_GATE = 0.08  # openings below this (fractions of the loud level) are silence
_ATTACK, _RELEASE = 0.65, 0.35  # how fast the mouth opens / closes
_SILENCE_RMS = 0.0025  # about -52 dBFS: below this the mouth stays shut


def load_audio(path, max_seconds: float) -> np.ndarray:
    """Mono int16 samples at AUDIO_RATE, at most max_seconds long."""
    samples: list[np.ndarray] = []
    limit = int(max_seconds * AUDIO_RATE)
    total = 0
    with av.open(str(path)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=AUDIO_RATE)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                chunk = converted.to_ndarray().reshape(-1)
                samples.append(chunk)
                total += chunk.size
            if total >= limit:
                break
        for converted in resampler.resample(None):
            samples.append(converted.to_ndarray().reshape(-1))
    audio = np.concatenate(samples) if samples else np.zeros(0, dtype=np.int16)
    return audio[:limit].astype(np.int16)


def mouth_envelope(audio: np.ndarray, fps: int) -> np.ndarray:
    """Mouth opening per frame (0..1) from the speech loudness."""
    hop = AUDIO_RATE // fps
    frames = max(1, math.ceil(audio.size / hop))
    padded = np.pad(audio.astype(np.float32) / 32768.0, (hop, hop * 2))
    rms = np.array([math.sqrt(float(np.mean(padded[i * hop : i * hop + 2 * hop] ** 2)) + 1e-12) for i in range(frames)])
    # Relative to the loud parts (at least -40 dBFS, so quiet recordings aren't boosted),
    # and anything below _SILENCE_RMS keeps the mouth shut.
    loud = max(float(np.percentile(rms, 95)), _SILENCE_RMS * 4)
    level = np.where(rms < _SILENCE_RMS, 0.0, np.clip(rms / loud, 0.0, 1.0))
    level = np.where(level < _GATE, 0.0, (level - _GATE) / (1 - _GATE))
    opening = np.zeros(frames, dtype=np.float32)
    current = 0.0
    for i, target in enumerate(level):
        rate = _ATTACK if target > current else _RELEASE
        current += (target - current) * rate
        opening[i] = current
    return np.clip(opening, 0.0, 1.0) ** 0.8


class MouthAnimator:
    """Precomputes the warp region once, then renders one frame per opening value."""

    def __init__(self, image: np.ndarray, mouth_x: float, mouth_y: float, mouth_width: float, animate_mouth: bool):
        import cv2

        self.cv2 = cv2
        self.image = image
        self.height, self.width = image.shape[:2]
        self.animate_mouth = animate_mouth
        cx, cy = mouth_x * self.width, mouth_y * self.height
        mw = max(8.0, mouth_width * self.width)
        self.cx, self.cy, self.mw = cx, cy, mw
        self.max_open = 0.42 * mw
        self.jaw = 1.25 * mw  # from the lip line down to where the chin stays fixed
        x0, x1 = int(max(0, cx - 1.1 * mw)), int(min(self.width, cx + 1.1 * mw))
        y0, y1 = int(max(0, cy - 0.2 * mw)), int(min(self.height, cy + self.jaw + 2))
        self.roi = (x0, y0, x1, y1)
        xs, ys = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
        self.xs, self.ys = xs, ys
        # Horizontal bell: full movement in the middle of the mouth, none at its corners.
        self.bell = np.clip(1 - ((xs - cx) / (0.62 * mw)) ** 2, 0, 1) ** 1.2
        self.inside = np.clip(1 - ((xs - cx) / (0.5 * mw)) ** 2, 0, 1)
        # Mouth-interior colour from this face's own lips (a deep, dark version), so it
        # looks natural on any skin tone and on drawings alike.
        lx0, lx1 = int(max(0, cx - 0.3 * mw)), int(min(self.width, cx + 0.3 * mw))
        ly0, ly1 = int(max(0, cy - 0.12 * mw)), int(min(self.height, cy + 0.12 * mw)) + 1
        lips = np.median(image[ly0:ly1, lx0:lx1].reshape(-1, 3), axis=0) if lx1 > lx0 and ly1 > ly0 else np.array([60, 50, 120])
        self.cavity = np.clip(lips * 0.22 + np.array([8, 6, 14]), 0, 255)
        self.teeth = np.array([214, 216, 222], dtype=np.float32)
        self.t = 0

    def frame(self, opening: float) -> np.ndarray:
        cv2 = self.cv2
        out = self.image.copy()
        if self.animate_mouth and opening > 0.02:
            x0, y0, x1, y1 = self.roi
            gap = opening * self.max_open * self.bell  # per column: how far the lower lip drops
            below = self.ys - self.cy
            # Destination rows below the lip line: [0, gap) is the open mouth, the rest
            # maps back onto the original lower face, squeezed so the chin stays still.
            squeezed = self.cy + (below - gap) * self.jaw / np.maximum(self.jaw - gap, 1.0)
            map_y = np.where(below < 0, self.ys, np.where(below < gap, self.cy, squeezed)).astype(np.float32)
            region = cv2.remap(self.image, self.xs, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

            # Mouth interior: dark, with a light band of upper teeth when open wide enough.
            depth = np.clip((below >= 0) & (below < gap), 0, 1).astype(np.float32) * self.inside
            depth = cv2.GaussianBlur(depth, (0, 0), 1.2)
            # Darkest in the middle of the opening, a little lighter near the lips.
            middle = 1 - np.abs((below - gap / 2) / np.maximum(gap / 2, 1.0))
            interior = self.cavity * (1.15 - 0.35 * np.clip(middle, 0, 1))[..., None]
            teeth = (below >= 0) & (below < gap * 0.26) & (self.inside > 0.35) & (gap > 5)
            interior[teeth] = interior[teeth] * 0.2 + self.teeth * 0.8
            alpha = depth[..., None]
            out[y0:y1, x0:x1] = np.clip(region * (1 - alpha) + interior * alpha, 0, 255).astype(np.uint8)

        # Subtle, slow head motion (plus a little with speech) so the image isn't frozen.
        self.t += 1
        angle = 0.6 * math.sin(self.t / 37.0)
        scale = 1.0 + 0.006 * math.sin(self.t / 53.0) + 0.004 * opening
        matrix = cv2.getRotationMatrix2D((self.width / 2, self.height * 0.62), angle, scale)
        matrix[1, 2] += 1.2 * math.sin(self.t / 29.0)
        return cv2.warpAffine(out, matrix, (self.width, self.height), borderMode=cv2.BORDER_REPLICATE)


class LocalLipSync(LipSyncProvider):
    name = "local"

    def render(self, request: LipSyncRequest, progress: ProgressCallback) -> float:
        import cv2

        image = cv2.imread(str(request.image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise AvatarError("The avatar image couldn't be read")
        audio = load_audio(request.audio_path, request.max_seconds)
        if audio.size < AUDIO_RATE // 10:
            raise AvatarError("The speech audio is empty")
        openings = mouth_envelope(audio, request.fps)
        animator = MouthAnimator(
            image, request.mouth.x, request.mouth.y, request.mouth.width, animate_mouth=True
        )
        progress(15)

        height, width = image.shape[:2]
        try:
            with av.open(str(request.output_path), mode="w", format="mp4", options={"movflags": "+faststart"}) as out:
                video = out.add_stream("libx264", rate=request.fps)
                video.width, video.height, video.pix_fmt = width, height, "yuv420p"
                video.options = {"crf": "23", "preset": "veryfast"}
                sound = out.add_stream("aac", rate=AUDIO_RATE)
                sound.layout = "mono"

                total = len(openings)
                for index, opening in enumerate(openings):
                    frame = av.VideoFrame.from_ndarray(animator.frame(float(opening)), format="bgr24")
                    for packet in video.encode(frame):
                        out.mux(packet)
                    if index % max(1, total // 20) == 0:
                        progress(15 + int(75 * index / total))
                for packet in video.encode(None):
                    out.mux(packet)

                pcm = av.AudioFrame.from_ndarray(audio.reshape(1, -1), format="s16", layout="mono")
                pcm.sample_rate = AUDIO_RATE
                resampler = av.AudioResampler(format="fltp", layout="mono", rate=AUDIO_RATE)
                fifo = av.AudioFifo()
                for converted in resampler.resample(pcm):
                    fifo.write(converted)
                size = sound.codec_context.frame_size or 1024
                while chunk := fifo.read(size):
                    for packet in sound.encode(chunk):
                        out.mux(packet)
                if last := fifo.read():
                    for packet in sound.encode(last):
                        out.mux(packet)
                for packet in sound.encode(None):
                    out.mux(packet)
        except AvatarError:
            raise
        except Exception as exc:  # noqa: BLE001 - FFmpeg errors vary
            raise AvatarError(f"Video encoding failed: {type(exc).__name__}") from exc
        progress(95)
        duration = round(audio.size / AUDIO_RATE, 2)
        logger.info("Rendered a %.1fs talking-avatar video (%dx%d, %d frames)", duration, width, height, len(openings))
        return duration
