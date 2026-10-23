"""Urdu spelled for the local voice by Gemini: in Devanagari, or in Urdu script.

Chatterbox has no Urdu, so Urdu is read by its Hindi model from Devanagari. OmniVoice
speaks Urdu itself, from Urdu script, so Roman Urdu (Urdu in Latin letters) is rewritten
in Urdu script for it. The rule-based converters (roman_urdu.py, transliterate.py) can
only guess spellings ("sakta" -> सक्ता, "jawab" -> जवब): Roman Urdu has no fixed spelling and
Urdu script leaves out short vowels. Gemini knows the words, so it is asked first; on any
failure (no key, timeout, quota, an odd answer) these return None and the caller keeps
the rules.
"""

import asyncio
import logging
import re
from collections import OrderedDict

from google.genai import types

from app.core.config import get_settings
from app.voice.base import VoiceError
from app.voice.providers.gemini import _call, _client, model_list

logger = logging.getLogger(__name__)

_RULES = """- Keep English words and English sentences exactly as they are, in Latin letters.
- Keep numbers, punctuation and the order of sentences. Do not translate, add, remove or explain anything.
Return only the rewritten text."""

PROMPT = f"""You prepare text for a Hindi text-to-speech engine that reads it aloud in an Urdu (Hindustani) voice.
Rewrite the text you are given:
- Write every Urdu or Hindi word in Devanagari, whether it is written in Roman letters (Roman Urdu) or in Urdu script, spelled the way it is pronounced in Urdu. Use nukta letters for Urdu sounds (क़ ख़ ग़ ज़ फ़).
{_RULES}"""

URDU_PROMPT = """You prepare text for an Urdu text-to-speech engine, which stumbles when Latin letters appear inside Urdu.
Rewrite the text you are given:
- Write every Urdu or Hindi word in Urdu script (Nastaliq letters), whether it is written in Roman letters (Roman Urdu) or in Devanagari, with its usual Urdu spelling.
- In sentences that are mainly Urdu, also write the English words in Urdu script, the way Pakistanis say them (e.g. "AI clone" -> "اے آئی کلون", "phone" -> "فون").
- Keep sentences that are entirely English exactly as they are, in Latin letters.
- Keep numbers, punctuation and the order of sentences. Do not translate, add, remove or explain anything.
Return only the rewritten text."""

_DEVANAGARI = re.compile("[ऀ-ॿ]")
_ARABIC_SCRIPT = re.compile("[؀-ۿ]")
_CACHE_SIZE = 256
_cache: OrderedDict[tuple[str, str], str] = OrderedDict()


def clear_cache() -> None:
    _cache.clear()


async def _rewrite(text: str, prompt: str, script: re.Pattern[str], what: str) -> str | None:
    settings = get_settings()
    if not settings.voice_llm_transliteration:
        return None
    key = (what, text)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    timeout = settings.voice_transliteration_timeout_seconds
    client = _client(settings.stt_api_key or settings.gemini_api_key, timeout)
    if client is None:
        return None
    config = types.GenerateContentConfig(
        system_instruction=prompt,
        temperature=0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    async def request(model: str) -> str:
        response = await client.aio.models.generate_content(model=model, contents=text, config=config)
        return response.text or ""

    models = model_list(settings.voice_transliteration_model, settings.gemini_fallback_model)
    try:
        written = (await asyncio.wait_for(_call(models, request, "transliteration"), timeout=timeout)).strip()
    except (VoiceError, TimeoutError) as exc:
        logger.warning("Urdu spelling (%s) by Gemini failed (%s); using the rules", what, type(exc).__name__)
        return None
    # A sensible answer is in the asked script and about as long (never an essay or a refusal).
    if not script.search(written) or len(written) > 2 * len(text) + 40:
        logger.warning("Urdu spelling (%s) by Gemini looked wrong; using the rules", what)
        return None
    _cache[key] = written
    while len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return written


async def to_devanagari(text: str) -> str | None:
    """`text` with its Urdu words in Devanagari (for Chatterbox), or None to use the rules."""
    return await _rewrite(text, PROMPT, _DEVANAGARI, "devanagari")


async def to_urdu_script(text: str) -> str | None:
    """`text` with its Urdu words in Urdu script (for OmniVoice), or None to use the rules."""
    return await _rewrite(text, URDU_PROMPT, _ARABIC_SCRIPT, "urdu")
