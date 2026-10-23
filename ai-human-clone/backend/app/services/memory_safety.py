"""Keeps secrets and credentials out of long-term memory.

A memory is refused when it mentions a kind of credential (password, API key,
card number, security answer, ...) or contains something shaped like one
(provider key prefixes, private-key blocks, JWTs, card numbers that pass the
Luhn check, long random tokens). This is deliberately strict: a harmless
memory that merely mentions "my password" is refused too, because a stored
secret is far worse than a missing memory.
"""

import re

_CREDENTIAL_WORDS = re.compile(
    r"\b("
    r"pass(word|wd|code|phrase)s?|otp|one[\s-]time\s+(password|code)|cvv|cvc|"
    r"pin\s*(code|number|is)|(bank|card|atm|debit|credit|phone|sim)\s+pins?|pins?\s+(reminder|for\s+my)|"
    r"api[\s_-]?keys?|secret[\s_-]?keys?|client[\s_-]?secrets?|access[\s_-]?tokens?|auth(entication)?[\s_-]?tokens?|"
    r"bearer\s+tokens?|refresh[\s_-]?tokens?|session[\s_-]?(tokens?|cookies?)|private[\s_-]?keys?|ssh[\s_-]?keys?|"
    r"seed\s+phrase|recovery\s+(phrase|codes?)|security\s+(questions?|answers?)|mother'?s\s+maiden\s+name|"
    r"(credit|debit|bank)\s+card\s*(numbers?)?|card\s+numbers?|bank\s+account\s+numbers?|account\s+numbers?|"
    r"routing\s+numbers?|iban|swift\s+code|login\s+credentials?|credentials?"
    r")\b",
    re.IGNORECASE,
)

_SECRET_SHAPES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{16,}"),  # Anthropic / OpenAI style
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),  # Google API keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key ids
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWTs
]
# 32+ characters of letters AND digits with no spaces: a key or token, not a word.
_RANDOM_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_\-]*[0-9])(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b")
_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _passes_luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def looks_sensitive(text: str) -> bool:
    """True if the text looks like (or talks about) a secret that must not be remembered."""
    if _CREDENTIAL_WORDS.search(text):
        return True
    if any(pattern.search(text) for pattern in _SECRET_SHAPES) or _RANDOM_TOKEN.search(text):
        return True
    for match in _CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _passes_luhn(digits):
            return True
    return False
