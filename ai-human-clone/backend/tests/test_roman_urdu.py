"""Roman Urdu (Latin letters) -> Devanagari for the local voice-clone model."""

import pytest

from app.voice.roman_urdu import is_roman_urdu, roman_urdu_to_devanagari


@pytest.mark.parametrize(
    "text",
    [
        "Aap kaise hain?",
        "Mujhe nahi pata, lekin main koshish karunga.",
        "Shukriya bhai, bohat acha laga.",
        "Assalam o alaikum! Kya haal hai?",
    ],
)
def test_detects_roman_urdu(text: str):
    assert is_roman_urdu(text)


@pytest.mark.parametrize(
    "text",
    [
        "Hello, how are you?",
        "I am fine and the main thing is to go home.",
        "My phone video is on the main mobile app, ok?",
        "",
        "123 !!",
    ],
)
def test_english_is_not_roman_urdu(text: str):
    assert not is_roman_urdu(text)


def test_one_clue_is_enough_when_urdu_is_expected():
    assert is_roman_urdu("Salam", expected=True)
    assert not is_roman_urdu("Salam")
    assert not is_roman_urdu("Hello there", expected=True)


@pytest.mark.parametrize(
    ("roman", "devanagari"),
    [
        ("Aap kaise hain?", "आप कैसे हैं?"),
        ("Main theek hoon.", "मैं ठीक हूँ."),
        ("Mujhe nahi pata", "मुझे नहीं पता"),
        ("Shukriya bhai, bohat acha laga!", "शुक्रिया भाई, बहुत अच्छा लगा!"),
        ("Mera naam Ahmad hai", "मेरा नाम अह्मद है"),  # h+m with no vowel between: a cluster
        ("Main aap ka AI clone hoon", "मैं आप का AI क्लोन हूँ"),
        ("kabhi kitab", "कभी कितब"),  # letter rules: final i is long, clusters, no fixed spelling
        ("bachcha", "बच्चा"),
        ("Inshallah 2 baje", "इंशाअल्लाह 2 बजे"),
    ],
)
def test_conversion(roman: str, devanagari: str):
    assert roman_urdu_to_devanagari(roman) == devanagari


def test_conversion_leaves_no_latin_letters_except_acronyms():
    result = roman_urdu_to_devanagari("Kal subah dost ke sath khana khayenge, OK?")
    assert [c for c in result if c.isascii() and c.isalpha()] == list("OK")
