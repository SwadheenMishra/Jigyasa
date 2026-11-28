"""Loads chapter content (app/chapters/*.json) and shared lines (app/brain/common.json)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.brain.text import contains_any, find_phrase, normalize

APP_DIR = Path(__file__).resolve().parent
CHAPTER_DIR = APP_DIR / "chapters"
COMMON_FILE = APP_DIR / "brain" / "common.json"

# Language chips offered in the UI. "rec" is the SpeechRecognition locale.
LANGUAGES = {
    "hinglish": {"label": "Hinglish", "rec": "hi-IN"},
    "en": {"label": "English", "rec": "en-IN"},
    "hi": {"label": "हिंदी", "rec": "hi-IN"},
    "pa": {"label": "ਪੰਜਾਬੀ", "rec": "pa-IN"},
    "ta": {"label": "தமிழ்", "rec": "ta-IN"},
    "bn": {"label": "বাংলা", "rec": "bn-IN"},
    "mr": {"label": "मराठी", "rec": "mr-IN"},
}
DEFAULT_LANGUAGE = "hinglish"


@lru_cache(maxsize=1)
def load_chapters() -> dict[str, dict]:
    chapters = [json.loads(p.read_text(encoding="utf-8")) for p in CHAPTER_DIR.glob("*.json")]
    chapters.sort(key=lambda c: c.get("order", 99))
    return {c["id"]: c for c in chapters}


@lru_cache(maxsize=1)
def common() -> dict:
    return json.loads(COMMON_FILE.read_text(encoding="utf-8"))


def get_chapter(chapter_id: str) -> dict | None:
    return load_chapters().get(chapter_id)


def public_chapter(ch: dict) -> dict:
    """The small, safe subset of a chapter that the browser needs."""
    return {k: ch.get(k) for k in ("id", "title", "title_hi", "class", "subject", "emoji")}


def line_key(language: str) -> str:
    """Which form of a line to show: "hi" = Roman Hinglish, "en" = English, "dev" = Devanagari Hindi.

    The हिंदी chip shows the Devanagari form. Other languages fall back to
    Hinglish for now; the LLM brain can reply in the student's own language.
    Listed as a roadmap item.
    """
    return {"en": "en", "hi": "dev"}.get(language, "hi")


def pick(text_obj, language: str) -> str:
    if isinstance(text_obj, str):
        return text_obj
    return text_obj.get(line_key(language)) or text_obj.get("hi") or ""


def line(text_obj, language: str, **subs) -> dict:
    """A Kyun-Kyun line: {"text": shown on screen, "speak": fed to text-to-speech}.

    Hinglish is shown in Roman script, but Hindi TTS voices read Roman Hindi
    badly, so the spoken version uses the line's Devanagari form ("dev") when
    there is one. The browser falls back to speaking "text" with an English
    (India) voice if the device has no Hindi voice.
    Each value in `subs` is a str or another line dict, filled into {name}.
    """
    text = pick(text_obj, language)
    speak = text
    if language != "en" and isinstance(text_obj, dict) and text_obj.get("dev"):
        speak = text_obj["dev"]
    for name, value in subs.items():
        v_text, v_speak = (value["text"], value["speak"]) if isinstance(value, dict) else (value, value)
        text = text.replace("{" + name + "}", v_text)
        speak = speak.replace("{" + name + "}", v_speak)
    return {"text": text, "speak": speak}


def join_lines(*lines: dict, sep: str = " ") -> dict:
    parts = [ln for ln in lines if ln and ln["text"]]
    return {"text": sep.join(p["text"] for p in parts), "speak": sep.join(p["speak"] for p in parts)}


def chapter_text(ch: dict, raw: str) -> str:
    """Normalise a transcript with the chapter's vocabulary fixes and drop topic names
    that would falsely look like concept keywords (e.g. प्रकाश in प्रकाश संश्लेषण)."""
    t = normalize(raw, ch.get("vocab_fixes"))
    for phrase in ch.get("ignore_phrases", []):
        t = t.replace(normalize(phrase), " ")
    return " ".join(t.split())


def match_topic(raw: str) -> str | None:
    """Map a spoken topic ("Photosynthesis samjhana hai") to a chapter id."""
    best_id, best_hits = None, 0
    for ch in load_chapters().values():
        t = normalize(raw, ch.get("vocab_fixes"))
        if find_phrase(t, ch.get("topic_keywords", [])):
            return ch["id"]
        hits = sum(contains_any(t, c["keywords"]) for c in ch["concepts"])
        if hits > best_hits:
            best_id, best_hits = ch["id"], hits
    return best_id if best_hits >= 2 else None
