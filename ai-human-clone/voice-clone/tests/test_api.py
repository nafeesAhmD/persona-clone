from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf

from conftest import make_wav

# --- auth & health -----------------------------------------------------------


def test_health_needs_no_token(make_client):
    client = make_client()
    del client.headers["X-Service-Token"]
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "model_loaded": True, "device": "cpu", "engine": "chatterbox"}


def test_missing_or_wrong_token_is_401(client):
    files = [("files", ("a.wav", make_wav(8), "audio/wav"))]
    assert client.post("/voices", files=files, headers={"X-Service-Token": "nope"}).status_code == 401
    del client.headers["X-Service-Token"]
    resp = client.post("/voices", files=files)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid service token"}
    assert client.delete("/voices/" + "a" * 32).status_code == 401
    assert client.post("/synthesize", json={}).status_code == 401


def test_no_token_configured_allows_requests(make_client):
    client = make_client(token="")
    resp = client.post("/voices", files=[("files", ("a.wav", make_wav(8), "audio/wav"))])
    assert resp.status_code == 201


def test_health_reports_loading(make_client, engine):
    import threading

    gate = threading.Event()
    engine.load = lambda: gate.wait(5)  # type: ignore[method-assign]
    client = make_client(wait_loaded=False)
    assert client.get("/health").json()["model_loaded"] is False
    gate.set()
    client.app.state.manager.wait_ready(5)
    assert client.get("/health").json()["model_loaded"] is True


def test_synthesize_returns_503_while_model_loading(make_client, engine, tmp_path):
    import threading

    gate = threading.Event()
    engine.load = lambda: gate.wait(5)  # type: ignore[method-assign]
    client = make_client(wait_loaded=False, MODEL_WAIT_SECONDS=0.1)
    vid = client.post("/voices", files=[("files", ("a.wav", make_wav(8), "audio/wav"))]).json()["voice_id"]
    resp = client.post("/synthesize", json={"voice_id": vid, "text": "Hello.", "language_id": "en"})
    gate.set()
    assert resp.status_code == 503
    assert resp.json() == {"detail": "model loading"}


# --- voices ------------------------------------------------------------------


def test_create_voice_from_tone(client, tmp_path):
    resp = client.post("/voices", files=[("files", ("a.wav", make_wav(12), "audio/wav"))])
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["voice_id"]) == 32
    assert 11.0 <= body["reference_seconds"] <= 12.5
    saved = tmp_path / "voices" / f"{body['voice_id']}.wav"
    data, sr = sf.read(saved)
    assert sr == 24_000 and data.ndim == 1


def test_create_voice_combines_files_and_caps_length(client):
    files = [
        ("files", ("a.wav", make_wav(14, kind="noise", sr=44_100), "audio/wav")),
        ("files", ("b.wav", make_wav(14, sr=22_050, subtype="FLOAT"), "audio/wav")),
    ]
    resp = client.post("/voices", files=files)
    assert resp.status_code == 201, resp.text
    assert 14.5 <= resp.json()["reference_seconds"] <= 15.5


def test_silence_is_trimmed(client):
    # 3 s tone + 10 s silence: only ~3 s of usable audio -> rejected.
    tone, _ = sf.read(io.BytesIO(make_wav(3)))
    padded = np.concatenate([np.zeros(16_000 * 5), tone, np.zeros(16_000 * 5)])
    buf = io.BytesIO()
    sf.write(buf, padded, 16_000, format="WAV")
    resp = client.post("/voices", files=[("files", ("a.wav", buf.getvalue(), "audio/wav"))])
    assert resp.status_code == 400


def test_too_short_audio_is_400(client):
    resp = client.post("/voices", files=[("files", ("a.wav", make_wav(3), "audio/wav"))])
    assert resp.status_code == 400
    assert "at least 5 seconds" in resp.json()["detail"]


def test_silent_and_empty_and_garbage_are_400(client):
    for blob in (make_wav(10, kind="silence"), b"", b"not audio at all"):
        resp = client.post("/voices", files=[("files", ("a.wav", blob, "audio/wav"))])
        assert resp.status_code == 400, blob[:10]


def test_upload_too_large_is_413(make_client):
    client = make_client(MAX_UPLOAD_MB=0.1)
    resp = client.post("/voices", files=[("files", ("a.wav", make_wav(10), "audio/wav"))])
    assert resp.status_code == 413


def test_delete_voice(client, voice_id, tmp_path, engine):
    assert client.delete(f"/voices/{voice_id}").status_code == 204
    assert not (tmp_path / "voices" / f"{voice_id}.wav").exists()
    assert engine.forgotten == [voice_id]
    assert client.delete(f"/voices/{voice_id}").status_code == 404


def test_bad_voice_ids_are_rejected(client, tmp_path):
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"x")
    for bad in ("ABC", "a" * 31, "g" * 32, "..%2Fsecret", "..%2F..%2Fetc%2Fpasswd", "A" * 32):
        resp = client.delete(f"/voices/{bad}")
        assert resp.status_code in (400, 404), bad
    assert secret.exists()
    resp = client.post("/synthesize", json={"voice_id": "../secret", "text": "Hi.", "language_id": "en"})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "invalid voice_id"}


# --- synthesize ----------------------------------------------------------------


def test_synthesize_returns_wav(client, voice_id, engine):
    resp = client.post("/synthesize", json={"voice_id": voice_id, "text": "नमस्ते, आप कैसे हैं?", "language_id": "hi"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(resp.content))
    assert sr == 24_000 and data.ndim == 1 and data.size > 0
    assert engine.calls == [("नमस्ते, आप कैसे हैं?", "hi", voice_id)]


def test_long_text_is_split_into_sentences(client, voice_id, engine):
    text = " ".join(f"This is sentence number {i} and it has a few words in it." for i in range(15))
    resp = client.post("/synthesize", json={"voice_id": voice_id, "text": text, "language_id": "EN"})
    assert resp.status_code == 200
    assert len(engine.calls) > 1
    assert all(len(call[0]) <= 250 for call in engine.calls)
    assert " ".join(call[0] for call in engine.calls) == text
    data, _ = sf.read(io.BytesIO(resp.content))
    assert data.size > 0.5 * 24_000 * len(engine.calls)


def test_unsupported_language_is_400(client, voice_id):
    resp = client.post("/synthesize", json={"voice_id": voice_id, "text": "Hallo.", "language_id": "ur"})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "unsupported language_id"}


def test_unknown_voice_is_404(client):
    resp = client.post("/synthesize", json={"voice_id": "0" * 32, "text": "Hi.", "language_id": "en"})
    assert resp.status_code == 404


def test_text_length_limits(client, voice_id):
    for text in ("", "   ", "a" * 1001):
        resp = client.post("/synthesize", json={"voice_id": voice_id, "text": text, "language_id": "en"})
        assert resp.status_code == 422, text[:5]
    resp = client.post("/synthesize", json={"voice_id": voice_id, "text": "a" * 1000, "language_id": "en"})
    assert resp.status_code == 200


def test_synthesis_timeout_is_504(make_client, engine):
    client = make_client(SYNTH_TIMEOUT_SECONDS=0.2)
    vid = client.post("/voices", files=[("files", ("a.wav", make_wav(8), "audio/wav"))]).json()["voice_id"]
    engine.delay = 0.5
    resp = client.post(
        "/synthesize", json={"voice_id": vid, "text": "One. Two. " * 40, "language_id": "en"}
    )
    assert resp.status_code == 504
    assert resp.json() == {"detail": "synthesis timed out"}



def test_model_load_is_retried_after_failure(engine, monkeypatch):
    from model import ModelManager

    attempts = []

    def flaky_load():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("network down")

    engine.load = flaky_load  # type: ignore[method-assign]
    monkeypatch.setattr(ModelManager, "retry_initial_seconds", 0.01)
    manager = ModelManager(lambda: engine)
    manager.start_loading()
    assert manager.wait_ready(5)
    assert len(attempts) == 2


def test_pick_device():
    from model import pick_device

    assert pick_device("auto", cuda_available=True) == "cuda"
    assert pick_device("auto", cuda_available=False) == "cpu"
    assert pick_device("", cuda_available=False) == "cpu"
    assert pick_device("cpu", cuda_available=True) == "cpu"
    with pytest.raises(RuntimeError):
        pick_device("cuda", cuda_available=False)


def test_engine_by_name():
    from model import ChatterboxEngine, OmniVoiceEngine, engine_class

    assert engine_class("") is ChatterboxEngine
    assert engine_class("OmniVoice") is OmniVoiceEngine
    with pytest.raises(ValueError):
        engine_class("nope")


def test_caller_can_choose_the_voice_id(client):
    chosen = "ab" * 16
    resp = client.post("/voices", files=[("files", ("a.wav", make_wav(8), "audio/wav"))], data={"voice_id": chosen})
    assert resp.status_code == 201 and resp.json()["voice_id"] == chosen
    bad = client.post("/voices", files=[("files", ("a.wav", make_wav(8), "audio/wav"))], data={"voice_id": "../x"})
    assert bad.status_code == 400


def test_delete_removes_transcript_and_prompt(client, voice_id, tmp_path):
    folder = tmp_path / "voices"
    (folder / f"{voice_id}.txt").write_text("hello", encoding="utf-8")
    (folder / f"{voice_id}.omnivoice.pt").write_bytes(b"x")
    assert client.delete(f"/voices/{voice_id}").status_code == 204
    assert sorted(p.name for p in folder.iterdir()) == []


def test_any_language_engine_accepts_urdu(tmp_path, monkeypatch, engine):
    from fastapi.testclient import TestClient

    import app as app_module

    class AnyLanguage:
        name = "omnivoice"
        languages = None

        def __new__(cls):
            return engine

    monkeypatch.setenv("VOICE_CLONE_SERVICE_TOKEN", "")
    with TestClient(app_module.create_app(engine_factory=AnyLanguage, data_dir=tmp_path / "v")) as client:
        client.app.state.manager.wait_ready(5)
        assert client.get("/health").json()["engine"] == "omnivoice"
        vid = client.post("/voices", files=[("files", ("a.wav", make_wav(8), "audio/wav"))]).json()["voice_id"]
        ok = client.post("/synthesize", json={"voice_id": vid, "text": "آپ کیسے ہیں؟", "language_id": "ur"})
        assert ok.status_code == 200
        assert engine.calls[-1][1] == "ur"
        bad = client.post("/synthesize", json={"voice_id": vid, "text": "Hi.", "language_id": "u r"})
        assert bad.status_code == 400


def test_fixed_language_engine_rejects_urdu(client, voice_id):
    resp = client.post("/synthesize", json={"voice_id": voice_id, "text": "Hi.", "language_id": "ur"})
    assert resp.status_code == 400


def test_reference_can_be_read_back(client, voice_id):
    resp = client.get(f"/voices/{voice_id}/reference")
    assert resp.status_code == 200 and resp.content[:4] == b"RIFF"
    assert client.get("/voices/" + "c" * 32 + "/reference").status_code == 404
    del client.headers["X-Service-Token"]
    assert client.get(f"/voices/{voice_id}/reference").status_code == 401


def test_transcript_replaces_the_saved_prompt(client, voice_id, engine, tmp_path):
    folder = tmp_path / "voices"
    (folder / f"{voice_id}.omnivoice.pt").write_bytes(b"old prompt")
    resp = client.put(f"/voices/{voice_id}/transcript", json={"text": " آپ کیسے ہیں؟ "})
    assert resp.status_code == 204
    assert (folder / f"{voice_id}.txt").read_text(encoding="utf-8") == "آپ کیسے ہیں؟"
    assert not (folder / f"{voice_id}.omnivoice.pt").exists()
    assert voice_id in engine.forgotten
    assert client.put(f"/voices/{voice_id}/transcript", json={"text": ""}).status_code == 422
    assert client.put("/voices/" + "c" * 32 + "/transcript", json={"text": "hi"}).status_code == 404
