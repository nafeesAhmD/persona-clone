"""Shared fixtures: a fake engine so tests need neither torch nor model weights."""

from __future__ import annotations

import io
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOKEN = "test-token"


class FakeEngine:
    device = "cpu"
    sample_rate = 24_000

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.delay = 0.0
        self.forgotten: list[str] = []

    def load(self) -> None:
        pass

    def generate(self, text, language_id, voice_id, voice_path):
        assert Path(voice_path).is_file()
        self.calls.append((text, language_id, voice_id))
        if self.delay:
            threading.Event().wait(self.delay)
        t = np.arange(int(0.5 * self.sample_rate)) / self.sample_rate
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    def forget_voice(self, voice_id):
        self.forgotten.append(voice_id)


def make_wav(seconds: float, sr: int = 16_000, kind: str = "tone", subtype: str = "PCM_16") -> bytes:
    rng = np.random.default_rng(0)
    n = int(seconds * sr)
    if kind == "tone":
        t = np.arange(n) / sr
        # Amplitude-modulated tone: roughly syllable-like on/off energy.
        samples = 0.5 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
    elif kind == "noise":
        samples = 0.2 * rng.standard_normal(n)
    else:  # silence
        samples = np.zeros(n)
    buf = io.BytesIO()
    sf.write(buf, samples.astype(np.float32), sr, format="WAV", subtype=subtype)
    return buf.getvalue()


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def make_client(tmp_path, monkeypatch, engine):
    from fastapi.testclient import TestClient

    clients = []

    def _make(token: str = TOKEN, wait_loaded: bool = True, **env):
        monkeypatch.setenv("VOICE_CLONE_SERVICE_TOKEN", token)
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
        import app as app_module

        application = app_module.create_app(engine_factory=lambda: engine, data_dir=tmp_path / "voices")
        client = TestClient(application)
        client.__enter__()
        clients.append(client)
        if wait_loaded:
            application.state.manager.wait_ready(5)
        if token:
            client.headers["X-Service-Token"] = token
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def voice_id(client):
    resp = client.post("/voices", files=[("files", ("a.wav", make_wav(12), "audio/wav"))])
    assert resp.status_code == 201, resp.text
    return resp.json()["voice_id"]
