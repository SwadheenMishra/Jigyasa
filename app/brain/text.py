"""Text helpers shared by both brains: normalisation and phrase matching.

Transcripts arrive from the browser's speech recogniser in mixed scripts:
`hi-IN` returns Devanagari (often even for English words), `en-IN` returns
Latin. Every keyword list therefore holds both scripts, and matching works on
a normalised form of the text so that pronunciation slips ("clorofil") never
cost the student marks.

Phrase syntax used in the chapter JSON files:
  * plain words must appear in order, e.g. "food from soil"
  * a "*" token allows a gap of up to 3 words, e.g. "mitti * khana" matches
    "mitti se apna khana".
Latin-script edges get word boundaries ("sun" does not match "sunday").
Indic-script edges match as substrings so inflected forms still hit
("पत्ती" matches "पत्तियाँ" after normalisation).
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Keep Latin letters/digits and all Indic blocks (Devanagari..Malayalam, U+0900–U+0DFF).
_STRIP = re.compile(r"[^a-z0-9\sऀ-෿]")
_SPACES = re.compile(r"\s+")
_LATIN = re.compile(r"[a-z0-9]")
_GAP = r"(?:\s+\S+){0,3}\s+"
# Fractions: "1/8" (or "1 / 8") becomes "1 by 8" so it survives punctuation stripping;
# spoken forms ("ek bata aath", "one by eight") are mapped to the same shape by vocab_fixes.
_FRACTION = re.compile(r"(\d)\s*/\s*(\d)")
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize(text: str | None, fixes: dict[str, str] | None = None) -> str:
    """Lower-case, unify Unicode, drop punctuation, then apply vocabulary fixes."""
    t = unicodedata.normalize("NFC", text or "").lower().translate(_DEV_DIGITS)
    t = _FRACTION.sub(r"\1 by \2", t)
    t = t.replace("'", "").replace("’", "")  # "don't" -> "dont"
    t = t.replace("।", " ").replace("॥", " ")  # Devanagari full stops
    t = _SPACES.sub(" ", _STRIP.sub(" ", t)).strip()
    if fixes:
        for wrong, right in _sorted_fixes(tuple(fixes.items())):
            t = _phrase_regex(wrong).sub(right, t)
    return t


@lru_cache(maxsize=64)
def _sorted_fixes(items: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    # Longest first, so "photo sin thesis" is fixed before any shorter overlap.
    pairs = [(normalize(w), normalize(r)) for w, r in items]
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


@lru_cache(maxsize=4096)
def _phrase_regex(phrase: str) -> re.Pattern:
    # Normalise each word but keep the "*" gap marker (normalize() would strip it).
    tokens = " ".join(t if t == "*" else normalize(t) for t in phrase.split()).split()
    body = ""
    for i, tok in enumerate(tokens):
        if tok == "*":
            continue
        if body:
            body += _GAP if tokens[i - 1] == "*" else r"\s+"
        body += re.escape(tok)
    first, last = body[:1], tokens[-1][-1:] if tokens else ""
    prefix = r"(?<![a-z0-9])" if _LATIN.match(first or "") else ""
    suffix = r"(?![a-z0-9])" if _LATIN.match(last or "") else ""
    return re.compile(prefix + body + suffix)


def find_phrase(text: str, phrases: list[str]) -> tuple[str, re.Match] | None:
    """Return the first phrase (in list order) found in already-normalised text."""
    for phrase in phrases:
        m = _phrase_regex(phrase).search(text)
        if m:
            return phrase, m
    return None


def find_unnegated(text: str, phrases: list[str], negations: list[str]) -> tuple[str, re.Match] | None:
    """Like find_phrase, but skips matches that are negated ("... nahi leta")."""
    for phrase in phrases:
        for m in _phrase_regex(phrase).finditer(text):
            if not is_negated(text, m, negations):
                return phrase, m
    return None


def contains_any(text: str, phrases: list[str]) -> bool:
    return find_phrase(text, phrases) is not None


def is_negated(text: str, m: re.Match, negations: list[str], window: int = 3) -> bool:
    """True if a negation word sits inside the match or within `window` words of it.

    "plant mitti se khana nahi leta" should not count as the soil misconception.
    """
    before = text[: m.start()].split()[-window:]
    inside = m.group(0).split()
    after = text[m.end():].split()[:window]
    neg = set(negations)
    return any(w in neg for w in before + inside + after)


def snippet(text: str, m: re.Match, words: int = 4) -> str:
    """A few words around a match, to quote the student back to themselves."""
    before = text[: m.start()].split()[-words:]
    after = text[m.end():].split()[:words]
    return " ".join(before + [m.group(0)] + after)


_BY = re.compile(r"(\d) by (\d)")


def readable(text: str) -> str:
    """Undo the matching-only "1 by 8" form for display: "1/8"."""
    return _BY.sub(r"\1/\2", text)


def word_count(text: str) -> int:
    return len(text.split())
