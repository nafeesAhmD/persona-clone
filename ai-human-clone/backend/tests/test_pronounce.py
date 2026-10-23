"""Urdu spelled in Devanagari by Gemini for the local voice, with the rules as fallback."""

import asyncio

import pytest

from app.core.config import get_settings
from app.voice import pronounce
from app.voice.base import VoiceTimeoutError
from app.voice.providers import local_clone


@pytest.fixture(autouse=True)
def gemini(monkeypatch):
    """A fake Gemini: `answers` maps input text to the reply (or an exception)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_llm_transliteration", True)
    monkeypatch.setattr(pronounce, "_client", lambda key, timeout: object())
    answers: dict[str, object] = {}
    calls: list[str] = []

    async def fake_call(models, request, what):
        calls.append(what)
        text = list(answers)[-1] if answers else ""
        reply = answers.get(text, "")
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(pronounce, "_call", fake_call)
    pronounce.clear_cache()
    yield answers, calls
    pronounce.clear_cache()


def run(coro):
    return asyncio.run(coro)


def test_gemini_spelling_is_used(gemini):
    answers, _ = gemini
    answers["Main aap ki madad kar sakta hoon."] = "मैं आप की मदद कर सकता हूँ."
    assert run(local_clone.spoken_segments("Main aap ki madad kar sakta hoon.", None)) == [
        ("मैं आप की मदद कर सकता हूँ.", "hi")
    ]


def test_english_sentences_stay_english(gemini):
    answers, _ = gemini
    text = "Hello! Aap kaise hain? Thank you."
    answers[text] = "Hello! आप कैसे हैं? Thank you."
    assert run(local_clone.spoken_segments(text, None)) == [
        ("Hello!", "en"),
        ("आप कैसे हैं?", "hi"),
        ("Thank you.", "en"),
    ]


def test_urdu_script_goes_through_gemini_too(gemini):
    answers, _ = gemini
    answers["آپ کیسے ہیں؟"] = "आप कैसे हैं?"
    assert run(local_clone.spoken_segments("آپ کیسے ہیں؟", None)) == [("आप कैसे हैं?", "hi")]


@pytest.mark.parametrize("reply", [VoiceTimeoutError("slow"), "Sorry, I can't help with that.", ""])
def test_rules_are_the_fallback(gemini, reply):
    answers, _ = gemini
    answers["Aap kaise hain?"] = reply
    assert run(local_clone.spoken_segments("Aap kaise hain?", None)) == [("आप कैसे हैं?", "hi")]


def test_no_gemini_call_without_urdu(gemini):
    _, calls = gemini
    assert run(local_clone.spoken_segments("Hello there, how are you?", None)) == [
        ("Hello there, how are you?", "en")
    ]
    assert run(local_clone.spoken_segments("आप कैसे हैं?", "hi")) == [("आप कैसे हैं?", "hi")]
    assert calls == []


def test_switched_off(gemini, monkeypatch):
    answers, calls = gemini
    monkeypatch.setattr(get_settings(), "voice_llm_transliteration", False)
    answers["Aap kaise hain?"] = "आप कैसे हैं?"
    assert run(pronounce.to_devanagari("Aap kaise hain?")) is None
    assert calls == []


def test_answers_are_cached(gemini):
    answers, calls = gemini
    answers["Shukriya bhai"] = "शुक्रिया भाई"
    assert run(pronounce.to_devanagari("Shukriya bhai")) == "शुक्रिया भाई"
    assert run(pronounce.to_devanagari("Shukriya bhai")) == "शुक्रिया भाई"
    assert calls == ["transliteration"]


def test_too_long_answer_is_rejected(gemini):
    answers, _ = gemini
    answers["Haan"] = "हाँ " * 50
    assert run(pronounce.to_devanagari("Haan")) is None
