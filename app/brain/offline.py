"""Offline brain: rule-based, needs no key and no network.

Uses each chapter's concepts (keywords in English, romanised Hindi and
Devanagari), misconception triggers and pre-written questions and hints.

Question priority (CLAUDE.md §4): the biggest misconception first, then
missing concepts, then "why" probes on concepts the student did mention.
The plan is recomputed after every answer, so a misconception that shows up
in an answer gets targeted next, and a concept the student covers in an
answer is no longer asked about.
"""

from __future__ import annotations

import re

from app.brain.base import (MISCONCEPTION_PENALTY, QUESTIONS_PER_SESSION, Brain, combine_score,
                             reasoning_quality)
from app.brain.text import contains_any, find_phrase, find_unnegated, snippet
from app.content import chapter_text, common, join_lines, line, pick

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _spoken_word(concept: dict, word: str) -> str:
    """The student's word, as the Hindi voice should say it.

    Devanagari is spoken as-is; a Roman word ("dhoop", "green") is swapped for
    the concept's first Devanagari keyword, since Roman Hindi sounds garbled.
    """
    if _DEVANAGARI.search(word):
        return word
    return next((k for k in concept["keywords"] if _DEVANAGARI.search(k)), word)


class OfflineBrain(Brain):
    name = "offline"

    # ---------- analysis ----------

    def analyse(self, chapter: dict, raw: str) -> dict:
        """Find misconceptions and covered concepts in a transcript."""
        text = chapter_text(chapter, raw)
        negations = common()["negations"]

        misconceptions = []
        for m in chapter["misconceptions"]:
            # Some misconceptions are themselves negative ("space mein gravity nahi hai"),
            # so a chapter can switch the negation filter off for them.
            hit = (find_phrase(text, m["triggers"]) if m.get("negation_is_part_of_it")
                   else find_unnegated(text, m["triggers"], negations))
            # "exceptions": words near the match that flip its meaning, e.g.
            # "bhari cheez bhi ek saath girti hai" is the correct idea, not the misconception.
            if hit and contains_any(snippet(text, hit[1], 4), m.get("exceptions", [])):
                hit = None
            if hit:
                misconceptions.append({"item": m, "said": snippet(text, hit[1])})

        covered = {}
        for c in chapter["concepts"]:
            hit = find_phrase(text, c["keywords"])
            if hit:
                covered[c["id"]] = hit[1].group(0)

        return {"text": text, "misconceptions": misconceptions, "covered": covered}

    def _all_text(self, session: dict) -> str:
        parts = [session.get("explanation", "")]
        parts += [a["transcript"] for a in session.get("answers", []) if a["status"] == "answered"]
        return " ".join(parts)

    # ---------- questions ----------

    def _targets(self, chapter: dict, session: dict) -> list[tuple[str, dict, str | None]]:
        a = self.analyse(chapter, self._all_text(session))
        targets = [("misconception", m["item"], None) for m in a["misconceptions"]]
        targets += [("concept", c, None) for c in chapter["concepts"] if c["id"] not in a["covered"]]
        targets += [("probe", c, a["covered"][c["id"]]) for c in chapter["concepts"] if c["id"] in a["covered"]]
        return targets

    def next_question(self, chapter: dict, session: dict) -> dict:
        lang = session["language"]
        asked = {ans["target"]["id"] for ans in session.get("answers", [])}
        targets = self._targets(chapter, session)
        kind, item, word = next((t for t in targets if t[1]["id"] not in asked), targets[0])

        if kind == "probe":
            q = line(item["probe"], lang, word={"text": word, "speak": _spoken_word(item, word)})
        else:
            q = line(item["question"], lang)
        return {
            **q,
            "target": {"kind": kind, "id": item["id"]},
            "mood": "confused" if kind == "misconception" else "curious",
        }

    def first_question(self, chapter: dict, session: dict) -> dict:
        return self.next_question(chapter, session)

    def hint(self, chapter: dict, session: dict) -> dict:
        target = session["current"]["target"]
        pool = chapter["misconceptions"] if target["kind"] == "misconception" else chapter["concepts"]
        item = next(i for i in pool if i["id"] == target["id"])
        return line(item["hint"], session["language"])

    # ---------- scoring ----------

    def score(self, chapter: dict, session: dict) -> dict:
        lang = session["language"]
        c = common()
        lines = c["lines"]
        a = self.analyse(chapter, self._all_text(session))

        concepts = chapter["concepts"]
        covered = [x for x in concepts if x["id"] in a["covered"]]
        missing = [x for x in concepts if x["id"] not in a["covered"]]

        correctness = max(0, 100 - MISCONCEPTION_PENALTY * len(a["misconceptions"]))
        reasoning = self._reasoning(chapter, session)
        coverage = round(100 * len(covered) / len(concepts)) if concepts else 0
        score = combine_score(correctness, reasoning, coverage)
        quality = reasoning_quality(reasoning)

        names = lambda items: [pick(i["name"], lang) for i in items]  # noqa: E731
        joiner = line(lines["joiner"], lang)

        def name_list(items: list[dict]) -> dict:
            parts = [line(i["name"], lang) for i in items]
            return {"text": joiner["text"].join(p["text"] for p in parts),
                    "speak": joiner["speak"].join(p["speak"] for p in parts)}

        strengths = names(covered[:2])
        if quality == "high":
            strengths.append(pick(lines["strength_reasoning"], lang))

        # Three sentences: one strength, the main misconception (or a gap), encouragement.
        if covered:
            s1 = line(lines["strength"], lang, x=name_list(covered[:2]))
        elif quality == "high":
            s1 = line(lines["strength_reasoning"], lang)
        else:
            s1 = line(lines["strength_none"], lang)
        if a["misconceptions"]:
            idea = line(a["misconceptions"][0]["item"]["correct_idea"], lang)
            s2 = line(lines["misconception"], lang, x=idea)
        elif missing:
            s2 = line(lines["missing"], lang, x=name_list(missing[:2]))
        else:
            s2 = line(lines["all_good"], lang)
        band = "high" if score >= 75 else "mid" if score >= 45 else "low"
        feedback = join_lines(s1, s2, line(lines["encourage"][band], lang))

        return {
            "score": score,
            "concepts_covered": names(covered),
            "concepts_missing": names(missing),
            "misconceptions": [
                {
                    "id": m["item"]["id"],
                    "student_said": m["said"],
                    "correct_idea": pick(m["item"]["correct_idea"], lang),
                }
                for m in a["misconceptions"]
            ],
            "reasoning_quality": quality,
            "strengths": strengths,
            "feedback_in_student_language": feedback["text"],
            "feedback_speech": feedback["speak"],  # Devanagari for Hinglish, for the TTS voice
            "breakdown": {"correctness": correctness, "reasoning": reasoning, "coverage": coverage},
        }

    def _reasoning(self, chapter: dict, session: dict) -> int:
        """Score follow-up answers: half for a causal word, half for a concept keyword.

        Skipped ("pata nahi") answers score 0. Every question slot counts, so
        finishing early does not inflate the score.
        """
        causal = common()["causal_words"]
        keywords = [k for c in chapter["concepts"] for k in c["keywords"]]
        points = 0.0
        for ans in session.get("answers", []):
            if ans["status"] != "answered":
                continue
            t = chapter_text(chapter, ans["transcript"])
            points += 0.5 * contains_any(t, causal) + 0.5 * contains_any(t, keywords)
        # Textbook-like explanation + weak follow-up answers: likely read out (CLAUDE.md §4).
        if session.get("own_words_asked"):
            points *= 0.5
        return round(100 * points / QUESTIONS_PER_SESSION)
