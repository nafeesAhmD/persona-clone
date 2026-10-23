"""Roman Urdu (Urdu in Latin letters) -> Devanagari, so a Hindi speech model says it in Urdu.

People often write Urdu in Latin letters ("aap kaise hain?"). Read as English it sounds
wrong, so text that looks like Roman Urdu is rewritten in Devanagari and spoken with
language "hi" (spoken Urdu and Hindi are very close), like Urdu script in transliterate.py.

Detection counts common Roman Urdu words that are not also everyday English words
("hai", "nahi", "aap", "mujhe" ...). Conversion is APPROXIMATE on purpose: a list of very
common words is spelled exactly, other words go letter by letter (sh -> श, kh -> ख, aa -> ा,
final "a" -> ा ...). Roman Urdu has no fixed spelling, so rare words may sound a bit off.
Acronyms ("AI"), numbers, emoji and punctuation are kept as they are.
"""

import re

# Exact spellings for frequent words (several Roman spellings each) the letter rules get wrong.
_WORDS: dict[str, str] = {}
for _devanagari, _spellings in {
    "है": "hai he hy", "हैं": "hain hen hn", "हूँ": "hoon hun hu hon", "में": "mein mai men me mn",
    "मैं": "main mai mein", "नहीं": "nahi nahin nhi nai nahe", "न": "na", "क्या": "kya kia kiya",
    "आप": "aap ap", "तुम": "tum", "हम": "hum ham", "यह": "yeh yah", "ये": "ye", "वह": "woh wuh",
    "वो": "wo vo", "और": "aur or", "भी": "bhi", "ठीक": "theek thik theak thek", "अच्छा": "acha achha accha acha",
    "अच्छी": "achi achhi acchi", "अच्छे": "ache achhe acche", "बहुत": "bohat bohot bahut boht bht",
    "कुछ": "kuch kuchh kch", "क्यों": "kyun kyon kyu kiun", "कहाँ": "kahan kahaan", "यहाँ": "yahan yahaan",
    "वहाँ": "wahan wahaan", "हाँ": "haan han ha", "जी": "ji jee g", "करो": "karo kro", "कर": "kar kr",
    "करना": "karna krna", "करें": "karein karen krein kren", "रहा": "raha rha", "रही": "rahi rhi",
    "रहे": "rahe rhe", "सकता": "sakta skta", "सकती": "sakti skti", "सकते": "sakte skte",
    "चाहिए": "chahiye chahye chahiay chahie", "सलाम": "salam salaam", "अस्सलाम": "assalam asalam assalaam",
    "अलैकुम": "alaikum alaykum alykum", "वअलैकुम": "walaikum wa-alaikum", "ख़ुदा": "khuda", "हाफ़िज़": "hafiz",
    "शुक्रिया": "shukriya shukria", "मेहरबानी": "meharbani mehrbani", "पाकिस्तान": "pakistan",
    "प्यार": "pyar pyaar", "हमारा": "hamara", "हमारी": "hamari", "हमारे": "hamare", "तुम्हारा": "tumhara",
    "तुम्हारी": "tumhari", "तुम्हारे": "tumhare", "सवाल": "sawal sawaal", "जवाब": "jawab jawaab",
    "बात": "baat bat", "बातें": "baatein baaten", "वक़्त": "waqt", "दोस्त": "dost", "भाई": "bhai",
    "मदद": "madad", "ज़रूर": "zaroor zarur", "लेकिन": "lekin", "क्योंकि": "kyunke kyunki kyonki",
    "अब": "ab", "सब": "sab", "जब": "jab", "तब": "tab", "कब": "kab", "कौन": "kaun kon",
    "कैसे": "kaise kese", "कैसा": "kaisa kesa", "कैसी": "kaisi kesi", "मुझे": "mujhe mjhe", "तुझे": "tujhe",
    "उसे": "usay usse use", "इसे": "isay isse", "अपना": "apna", "अपनी": "apni", "अपने": "apne",
    "मेरा": "mera", "मेरी": "meri", "मेरे": "mere", "का": "ka", "की": "ki", "के": "ke", "को": "ko",
    "से": "se say", "पर": "par pe", "तो": "to", "था": "tha", "थी": "thi", "थे": "thay", "हो": "ho",
    "होगा": "hoga", "होगी": "hogi", "गया": "gaya gya", "गई": "gayi gai", "आज": "aaj", "कल": "kal",
    "अभी": "abhi", "फिर": "phir fir", "ख़ुश": "khush", "इंशाअल्लाह": "inshallah insha'allah",
    "माशाअल्लाह": "mashallah masha'allah", "अल्लाह": "allah", "दुआ": "dua", "शुरू": "shuru",
    "ज़िन्दगी": "zindagi", "दिल": "dil", "दिन": "din", "रात": "raat", "नाम": "naam", "काम": "kaam",
    "इंसान": "insan insaan", "आवाज़": "awaz awaaz aawaz", "साथ": "sath saath", "बाद": "baad",
    "पहले": "pehle pahle", "सिर्फ़": "sirf", "बिल्कुल": "bilkul", "समझ": "samajh samaj", "पता": "pata",
    # English words and places common in Roman Urdu chats (letter rules would say the final e).
    "क्लोन": "clone", "फ़ोन": "phone fone", "मोबाइल": "mobile", "वीडियो": "video", "वॉइस": "voice",
    "ऑनलाइन": "online", "लाहौर": "lahore", "कराची": "karachi", "इस्लामाबाद": "islamabad",
}.items():
    for _spelling in _spellings.split():
        _WORDS.setdefault(_spelling, _devanagari)

# Roman Urdu words that are not also everyday English words: what detection counts.
_MARKERS = frozenset(_WORDS) - frozenset(
    "he me or to use pe ha g on hu hon men mn a bat dil din kal kon sab tab ab say mai ho na ji "
    "main mere ache hen ham ap par clone phone fone mobile video voice online".split()
)

_CONSONANTS = [  # longest first
    ("chh", "छ"), ("kh", "ख"), ("gh", "घ"), ("ch", "च"), ("jh", "झ"), ("th", "थ"), ("dh", "ध"),
    ("ph", "फ"), ("bh", "भ"), ("sh", "श"), ("zh", "झ़"), ("q", "क़"), ("k", "क"), ("g", "ग"),
    ("c", "क"), ("j", "ज"), ("t", "त"), ("d", "द"), ("n", "न"), ("p", "प"), ("f", "फ़"), ("b", "ब"),
    ("m", "म"), ("y", "य"), ("r", "र"), ("l", "ल"), ("v", "व"), ("w", "व"), ("s", "स"), ("h", "ह"),
    ("z", "ज़"), ("x", "क्स"),
]
# (roman, sign after a consonant, letter standing alone); "" = the inherent "a".
_VOWELS = [
    ("aa", "ा", "आ"), ("ai", "ै", "ऐ"), ("au", "ौ", "औ"), ("ee", "ी", "ई"), ("ii", "ी", "ई"),
    ("oo", "ू", "ऊ"), ("ou", "ौ", "औ"), ("ei", "े", "ए"), ("ae", "ै", "ऐ"), ("a", "", "अ"),
    ("e", "े", "ए"), ("i", "ि", "इ"), ("o", "ो", "ओ"), ("u", "ु", "उ"),
]
_FINAL_LONG = {"": "ा", "ि": "ी", "ु": "ू"}  # word-final short vowels are long in Roman Urdu
_VIRAMA, _NASAL = "्", "ं"
_TOKEN = re.compile(r"[A-Za-z']+")


def _words(text: str) -> list[str]:
    return [w.lower().replace("'", "") for w in _TOKEN.findall(text)]


def is_roman_urdu(text: str, *, expected: bool = False) -> bool:
    """True when Latin `text` reads as Urdu (fewer clues needed when Urdu is `expected`)."""
    words = _words(text)
    if not words:
        return False
    hits = sum(1 for word in words if word in _MARKERS)
    if expected:
        return hits >= 1
    return hits >= 2 and hits * 5 >= len(words)  # at least 2 clues and 20% of the words


def _match(word: str, i: int, table: list) -> tuple | None:
    for entry in table:
        if word.startswith(entry[0], i):
            return entry
    return None


def _word(word: str) -> str:
    out: list[str] = []
    i, after_consonant = 0, False
    while i < len(word):
        vowel = _match(word, i, _VOWELS)
        if vowel:
            roman, sign, alone = vowel
            i += len(roman)
            at_end = i == len(word)
            if after_consonant:
                out.append(_FINAL_LONG.get(sign, sign) if at_end else sign)
            else:
                out.append(alone)
            if word[i:] == "n" and roman not in ("a", "u"):  # hain, main, hoon -> nasal
                out.append(_NASAL)
                break
            after_consonant = False
            continue
        consonant = _match(word, i, _CONSONANTS)
        if consonant is None:  # not a letter we know: keep it
            out.append(word[i])
            i, after_consonant = i + 1, False
            continue
        if after_consonant:
            out.append(_VIRAMA)  # two consonants with no vowel between: a cluster
        out.append(consonant[1])
        i += len(consonant[0])
        after_consonant = True
    return "".join(out)


def _convert(match: re.Match[str]) -> str:
    original = match.group(0)
    if original.isupper() and len(original) <= 5:  # acronyms such as AI, OK, USA
        return original
    word = original.lower().replace("'", "")
    return _WORDS.get(word) or _word(word)


def roman_urdu_to_devanagari(text: str) -> str:
    """Rewrite the Latin words of `text` in Devanagari (approximate, see module doc)."""
    return _TOKEN.sub(_convert, text)
