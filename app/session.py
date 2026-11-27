"""Session engine: the turn-taking rules, shared by both brains.

The engine decides *when* Kyun-Kyun asks, hints, redirects or moves on; the
brain decides *what* the question, hint and score are. Every reply to the
browser has the same shape:

    {"action": "listen"|"question"|"hint"|"redirect"|"nudge"|"noise"|"done",
     "say": str,              # Kyun-Kyun's line as shown on screen (Roman Hinglish / English)
     "speak": str,            # the same line for text-to-speech (Devanagari for Hinglish)
     "question": str|None,    # the current question, for the question card
     "q_number": int, "q_total": int, "stage": str,
     "mood": "curious"|"listening"|"confused"|"happy"}
"""

from __future__ import annotations

import random
import secrets
from datetime import datetime, timezone

from app.brain.base import Brain
from app.brain.text import contains_any, word_count
from app.content import chapter_text, common, join_lines, line

QUESTIONS_PER_SESSION = 3
MAX_IDK = 2  # the second "pata nahi" (or silence) on a question moves on
MAX_EXPLAIN_TRIES = 2  # after two empty/off-topic explanations, ask questions anyway
IDK_MAX_WORDS = 6  # "pata nahi, shayad kyunki dhoop..." is an answer, not an IDK


class SessionError(Exception):
    """A request that does not fit the session's current stage."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_session(chapter: dict, language: str, brain: Brain,
                student_name: str | None = None, class_code: str | None = None) -> dict:
    return {
        "id": secrets.token_urlsafe(12),
        "chapter_id": chapter["id"],
        "language": language,
        "student_name": student_name,
        "class_code": class_code,
        "brain": brain.name,
        "stage": "explain",  # explain -> questions -> review -> done
        "explanation": "",
        "explain_tries": 0,
        "answers": [],  # [{question, target, transcript, status: answered|skipped, hints}]
        "current": None,  # current question dict from the brain
        "idk": 0,
        "offtopic": 0,
        "log": [],  # every turn, including ones that were not scored
        "result": None,
        "created_at": _now(),
    }


def opening(chapter: dict, session: dict) -> dict:
    return _reply(session, "listen", line(chapter["opening"], session["language"]), mood="curious")


def classify(chapter: dict, raw: str, reason: str) -> str:
    """Sort a turn into noise / idk / offtopic / ok, using offline rules only.

    `reason` comes from the browser: "silence" (nothing heard for 8 s),
    "noise" (sound detected but nothing recognised), or "pause"/"done"/
    "timeout"/"typed" for a normal end of turn.
    """
    t = chapter_text(chapter, raw)
    c = common()
    if not t:
        return "idk" if reason == "silence" else "noise"

    vocab = [k for x in chapter["concepts"] for k in x["keywords"]]
    has_content = contains_any(t, vocab) or contains_any(t, c["causal_words"])
    if contains_any(t, c["idk_triggers"]) and (word_count(t) <= IDK_MAX_WORDS or not has_content):
        return "idk"

    if not has_content and word_count(t) >= 3:
        related = (
            chapter.get("related_words", [])
            + chapter.get("topic_keywords", [])
            + [tr for m in chapter["misconceptions"] for tr in m["triggers"]]
        )
        if not contains_any(t, related):
            return "offtopic"
    return "ok"


def handle_explain(session: dict, chapter: dict, raw: str, reason: str, brain: Brain) -> dict:
    _require(session, "explain")
    lang, lines = session["language"], common()["lines"]
    text = (raw or "").strip()
    kind = classify(chapter, text, reason)
    session["log"].append({"stage": "explain", "kind": kind, "text": text, "at": _now()})

    if kind == "noise":  # never score a turn we could not hear
        return _reply(session, "noise", line(lines["noise"], lang), mood="confused")

    if kind == "ok":
        session["explanation"] = f"{session['explanation']} {text}".strip()
    else:
        session["explain_tries"] += 1
        if session["explain_tries"] < MAX_EXPLAIN_TRIES:
            if kind == "offtopic":
                return _reply(session, "redirect", line(chapter["redirect"], lang), mood="confused")
            return _reply(session, "nudge", line(lines["explain_nudge"], lang), mood="curious")

    session["stage"] = "questions"
    return _ask(session, brain.first_question(chapter, session), _ack(lang))


def handle_answer(session: dict, chapter: dict, raw: str, reason: str, brain: Brain) -> dict:
    _require(session, "questions")
    lang, lines = session["language"], common()["lines"]
    q = session["current"]
    text = (raw or "").strip()
    kind = classify(chapter, text, reason)
    session["log"].append({"stage": "answer", "q": q["text"], "kind": kind, "text": text, "at": _now()})

    if kind == "noise":
        return _reply(session, "noise", join_lines(line(lines["noise"], lang), _q_line(q)), mood="confused")

    if kind == "offtopic":
        session["offtopic"] += 1
        if session["offtopic"] == 1:
            say = join_lines(line(chapter["redirect"], lang), _q_line(q))
            return _reply(session, "redirect", say, mood="confused")
        kind = "idk"  # a second off-topic answer counts as "pata nahi"

    if kind == "idk":
        session["idk"] += 1
        if session["idk"] < MAX_IDK:
            return _reply(session, "hint", brain.hint(chapter, session), mood="curious")
        return _advance(session, chapter, brain, text, "skipped", line(lines["move_on"], lang))

    return _advance(session, chapter, brain, text, "answered", _ack(lang))


def finish(session: dict, chapter: dict, brain: Brain) -> dict:
    if session["stage"] == "explain":
        raise SessionError("The student has not explained anything yet.")
    if session["result"] is None:
        session["result"] = brain.score(chapter, session)
        session["stage"] = "done"
        session["finished_at"] = _now()
    return session["result"]


# ---------- helpers ----------

def _advance(session: dict, chapter: dict, brain: Brain, text: str, status: str, prefix: dict) -> dict:
    q = session["current"]
    session["answers"].append({
        "question": q["text"],
        "target": q["target"],
        "transcript": text if status == "answered" else "",
        "status": status,
        "hints": session["idk"],
    })
    if len(session["answers"]) >= QUESTIONS_PER_SESSION:
        session["stage"] = "review"
        session["current"] = None
        return _reply(session, "done", line(common()["lines"]["done"], session["language"]), mood="happy")
    return _ask(session, brain.next_question(chapter, session), prefix)


def _ask(session: dict, question: dict, prefix: dict) -> dict:
    session["current"] = question
    session["idk"] = 0
    session["offtopic"] = 0
    return _reply(session, "question", join_lines(prefix, _q_line(question)), mood=question["mood"])


def _q_line(question: dict) -> dict:
    return {"text": question["text"], "speak": question.get("speak") or question["text"]}


def _reply(session: dict, action: str, say: dict, mood: str) -> dict:
    current = session.get("current")
    return {
        "action": action,
        "say": say["text"],
        "speak": say["speak"],
        "question": current["text"] if current else None,
        "q_number": min(len(session["answers"]) + 1, QUESTIONS_PER_SESSION),
        "q_total": QUESTIONS_PER_SESSION,
        "stage": session["stage"],
        "mood": mood,
    }


def _ack(language: str) -> dict:
    return line(random.choice(common()["lines"]["ack"]), language)


def _require(session: dict, stage: str) -> None:
    if session["stage"] != stage:
        raise SessionError(f"Session is in stage '{session['stage']}', expected '{stage}'.")
