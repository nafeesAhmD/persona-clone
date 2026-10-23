"""Urdu (Arabic script) -> Devanagari, so a Hindi speech model can read Urdu answers.

The local voice-clone model (Chatterbox Multilingual) has no Urdu, but spoken Urdu and
Hindi are very close. Urdu text is therefore rewritten in Devanagari and spoken with
language "hi".

This is APPROXIMATE on purpose: Urdu script usually leaves out short vowels, so a
letter-by-letter map can't always know them (e.g. پاکستان -> पाकसतान, not पाकिस्तान).
It handles the common letters, aspirated pairs with ھ (بھ -> भ, کھ -> ख ...), nasal ں,
long vowels written with ا و ی ے, short-vowel marks when the text has them (zer, zabar,
pesh, jazm, shadda), Urdu/Arabic punctuation and digits, plus a small list of very common
words whose usual spelling the rules would get wrong (ہے -> है, میں -> में, نہیں -> नहीं).
Non-Urdu text (Latin words, numbers, emoji) is kept as it is.
"""

import re
import unicodedata

_ASPIRATED = {
    "ب": "भ", "پ": "फ", "ت": "थ", "ٹ": "ठ", "ج": "झ", "چ": "छ", "د": "ध", "ڈ": "ढ",
    "ڑ": "ढ़", "ک": "ख", "گ": "घ", "ل": "ल्ह", "م": "म्ह", "ن": "न्ह", "ر": "र्ह",
}
_CONSONANTS = {
    "ب": "ब", "پ": "प", "ت": "त", "ٹ": "ट", "ث": "स", "ج": "ज", "چ": "च", "ح": "ह",
    "خ": "ख़", "د": "द", "ڈ": "ड", "ذ": "ज़", "ر": "र", "ڑ": "ड़", "ز": "ज़", "ژ": "झ़",
    "س": "स", "ش": "श", "ص": "स", "ض": "ज़", "ط": "त", "ظ": "ज़", "غ": "ग़", "ف": "फ़",
    "ق": "क़", "ک": "क", "گ": "ग", "ل": "ल", "م": "म", "ن": "न",
}
# Vowel sign after a consonant -> the same vowel standing alone.
_INDEPENDENT = {"ा": "आ", "ि": "इ", "ी": "ई", "ु": "उ", "ू": "ऊ", "े": "ए", "ै": "ऐ", "ो": "ओ", "ौ": "औ"}
# Spelling variants (Arabic keyboard letters, presentation forms) -> Urdu letters.
_VARIANTS = str.maketrans({"ك": "ک", "ي": "ی", "ى": "ی", "ه": "ہ", "ة": "ہ", "ۃ": "ہ", "أ": "ا", "إ": "ا", "ٱ": "ا"})
_PUNCTUATION = str.maketrans({
    "۔": "।", "،": ",", "؛": ";", "؟": "?", "٪": "%", "٫": ".", "٬": ",", "«": '"', "»": '"',
    **{chr(0x0660 + d): str(d) for d in range(10)},  # Arabic-Indic digits
    **{chr(0x06F0 + d): str(d) for d in range(10)},  # Urdu (Extended Arabic-Indic) digits
})
# zabar, zer, pesh, tanween (fathatan), shadda, jazm (sukun), khari zabar (superscript alif)
_ZABAR, _ZER, _PESH, _TANWEEN, _SHADDA, _JAZM, _KHARI_ZABAR = (
    chr(c) for c in (0x064E, 0x0650, 0x064F, 0x064B, 0x0651, 0x0652, 0x0670)
)


def _char_class(*ranges: tuple[int, int]) -> re.Pattern[str]:
    return re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in ranges) + "]")


_DIACRITICS = _char_class((0x064B, 0x065F), (0x0670, 0x0670))
_SHORT_VOWELS = _char_class((0x064E, 0x0650))  # zabar, zer, pesh
_ARABIC_SCRIPT = _char_class((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))

# Very common words whose usual (vowel-less) spelling the letter rules get wrong.
_WORDS = {
    "ہے": "है", "ہیں": "हैं", "میں": "में", "نہیں": "नहीं", "نہ": "न", "اور": "और", "کیا": "क्या",
    "یہ": "यह", "وہ": "वह", "کہ": "कि", "آپ": "आप", "تم": "तुम", "ہم": "हम", "مجھے": "मुझे",
    "مجھ": "मुझ", "تجھے": "तुझे", "ہمیں": "हमें", "انہیں": "उन्हें", "انہوں": "उन्हों", "اس": "इस",
    "ان": "इन", "اُن": "उन", "کیسے": "कैसे", "کیسا": "कैसा", "کیسی": "कैसी", "ایسا": "ऐसा",
    "ایسے": "ऐसे", "ایسی": "ऐसी", "ایک": "एक", "لیے": "लिए", "لئے": "लिए", "کچھ": "कुछ",
    "بہت": "बहुत", "اچھا": "अच्छा", "اچھی": "अच्छी", "اچھے": "अच्छे", "ٹھیک": "ठीक", "جی": "जी",
    "ہاں": "हाँ", "شکریہ": "शुक्रिया", "السلام": "अस्सलाम", "علیکم": "अलैकुम", "خدا": "ख़ुदा",
    "حافظ": "हाफ़िज़", "لیکن": "लेकिन", "کیونکہ": "क्योंकि", "پھر": "फिर", "ہو": "हो", "ہوں": "हूँ",
    "کر": "कर", "پر": "पर", "سے": "से", "کو": "को", "کا": "का", "کی": "की", "کے": "के",
    "اپنا": "अपना", "اپنی": "अपनी", "اپنے": "अपने", "دن": "दिन", "کب": "कब", "اب": "अब",
    "سب": "सब", "جب": "जब", "تب": "तब", "کون": "कौन", "کہاں": "कहाँ", "یہاں": "यहाँ", "وہاں": "वहाँ",
}


def has_arabic_script(text: str) -> bool:
    return bool(_ARABIC_SCRIPT.search(text))


def _is_letter(char: str) -> bool:
    return "ء" <= char <= "ٟ" or char == "ٰ" or "ٱ" <= char <= "ۓ"


def _vowel(sign: str, after_consonant: bool) -> str:
    return sign if after_consonant else _INDEPENDENT[sign]


def _word(word: str) -> str:
    plain = _DIACRITICS.sub("", word)
    if plain in _WORDS and not _SHORT_VOWELS.search(word):  # written vowel marks win
        return _WORDS[plain]
    word = word.replace("ـ", "")  # tatweel (kashida) is only decoration
    out: list[str] = []
    prev = "start"  # "start" | "consonant" | "vowel"
    last = ""  # the last consonant written (for shadda)
    i, n = 0, len(word)
    while i < n:
        char, nxt = word[i], word[i + 1] if i + 1 < n else ""
        after = prev == "consonant"
        if char in (_ZABAR, _ZER, _PESH, _KHARI_ZABAR):
            sign = {_ZABAR: "", _ZER: "ि", _PESH: "ु", _KHARI_ZABAR: "ा"}[char]
            if sign:
                out.append(_vowel(sign, after))
            elif not after:
                out.append("अ")
            prev = "vowel"
        elif char == _SHADDA:
            if last and after:
                out.append("्" + last)
        elif char == _JAZM:
            if after:
                out.append("्")
        elif char == _TANWEEN:
            out.append("न")
            prev = "consonant"
        elif char in _ASPIRATED and nxt == "ھ":
            last = _ASPIRATED[char]
            out.append(last)
            prev, i = "consonant", i + 1
        elif char == "ھ":
            last = "ह"
            out.append(last)
            prev = "consonant"
        elif char == "آ":
            out.append(_vowel("ा", after))
            prev = "vowel"
        elif char == "ا":
            if after:
                out.append("ा")
            elif prev == "vowel":
                out.append("आ")
            elif nxt in ("ی", "ے"):
                out.append("ए")
                i += 1
            elif nxt == "و":
                out.append("ओ")
                i += 1
            elif nxt in (_ZER, _PESH, _ZABAR):
                out.append({_ZER: "इ", _PESH: "उ", _ZABAR: "अ"}[nxt])
                i += 1
            else:
                out.append("अ")
            prev = "vowel"
        elif char == "ع":
            if prev == "start":
                out.append("अ")
            elif after:
                out.append("ा")
            prev = "vowel"
        elif char == "و":
            if prev == "start" or nxt == "ا" or prev == "vowel":
                last = "व"
                out.append(last)
                prev = "consonant"
            else:
                out.append("ो")
                prev = "vowel"
        elif char == "ی":
            if prev == "start" or nxt in ("ا", "و", "ے", "ہ"):
                last = "य"
                out.append(last)
                prev = "consonant"
            elif after:
                out.append("ी" if not nxt else "े")
                prev = "vowel"
            else:
                out.append("ई" if not nxt else "य")
                prev = "vowel" if not nxt else "consonant"
        elif char == "ئ":
            if nxt == "ی":
                out.append("ई")
                i += 1
            elif nxt == "ے":
                out.append("ए")
                i += 1
            else:
                out.append("इ")
            prev = "vowel"
        elif char == "ؤ":
            out.append("ओ")
            prev = "vowel"
        elif char in ("ے", "ۓ"):
            out.append(_vowel("े", after))
            prev = "vowel"
        elif char == "ہ":
            if not nxt and after and i > 0:  # final "gol he" after a consonant: a long "a"
                out.append("ा")
                prev = "vowel"
            else:
                last = "ह"
                out.append(last)
                prev = "consonant"
        elif char == "ں":
            out.append("ं")
        elif char == "ء":
            pass  # hamza alone: a short pause, nothing to write
        elif char in _CONSONANTS:
            last = _CONSONANTS[char]
            out.append(last)
            prev = "consonant"
        else:
            out.append(char)
        i += 1
    return "".join(out)


def urdu_to_devanagari(text: str) -> str:
    """Rewrite the Urdu-script words of `text` in Devanagari (approximate, see module doc)."""
    text = "".join(unicodedata.normalize("NFKC", c) if "ﭐ" <= c <= "﻿" else c for c in text)
    text = text.translate(_VARIANTS).translate(_PUNCTUATION)
    out: list[str] = []
    word: list[str] = []
    for char in text:
        if _is_letter(char):
            word.append(char)
            continue
        if word:
            out.append(_word("".join(word)))
            word = []
        out.append(char)
    if word:
        out.append(_word("".join(word)))
    return "".join(out)
