"""Word-boundary phrase matching with light negation handling.

Every matcher in the ranker (keyword lists, concept triggers, saturation
triggers, compliance keywords) routes through ``phrase_in`` so the whole
engine shares one defensible definition of "the thesis says X":

* A needle matches only at word boundaries, so "vat" no longer fires on
  "private" and "eta" no longer fires on "details".
* A trailing optional plural (``s``/``es``) keeps "return" matching
  "returns" the way the old substring matcher did.
* A hyphen immediately before the match blocks it ("closed-loop" must not
  fire the "loop" brand trigger), but a hyphen after is allowed so
  "ai-powered" still fires "ai".
* An *absence marker* within the three words before the match suppresses it,
  so "no manual upload needed" stops firing the high-setup trigger.
  Only ``{"no", "not", "without", "zero", "never"}`` are absence markers.
  Mitigation verbs (eliminate, replace, avoid …) are NOT negators here because
  they signal that the pain *exists* — "eliminates involuntary churn" is
  evidence of churn pain and must still fire the churn trigger.

Precondition: all inputs must be ``normalize()``d lowercase text and lowercase
needles. Patterns are case-sensitive by design — callers must lower-case before
passing in.
"""

from __future__ import annotations

import re
from functools import lru_cache

NEGATORS = frozenset({"no", "not", "without", "zero", "never"})

_NEGATION_WINDOW_WORDS = 3
# 40 chars comfortably covers 3 average English words (~6-8 chars each) plus
# punctuation and spaces — sufficient for typical 3-word negation windows.
_WINDOW_CHARS = 40


def phrase_in(text: str, needle: str) -> bool:
    """True when ``needle`` appears as a whole word/phrase and is not negated."""

    if not needle:
        return False
    for match in _compiled(needle).finditer(text):
        if not _negated(text, match.start()):
            return True
    return False


def count_phrases(text: str, needles: tuple[str, ...], *, cap: int) -> int:
    """Count distinct needles present in text (via ``phrase_in``), capped at ``cap``."""
    count = sum(1 for needle in needles if phrase_in(text, needle))
    return min(count, cap)


def any_phrase(text: str, needles: tuple[str, ...]) -> bool:
    return any(phrase_in(text, needle) for needle in needles)


@lru_cache(maxsize=8192)
def _compiled(needle: str) -> re.Pattern[str]:
    escaped = re.escape(needle)
    left = r"(?<![\w$€£-])" if needle[0].isalnum() else ""
    if needle[-1].isalpha():
        right = r"(?:e?s)?(?!\w)"
    elif needle[-1].isdigit():
        right = r"(?!\w)"
    else:
        right = ""
    return re.compile(left + escaped + right)


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - _WINDOW_CHARS):start]
    words = re.findall(r"[a-z][\w'-]*", window)
    return any(word in NEGATORS for word in words[-_NEGATION_WINDOW_WORDS:])
