"""Common interface for Kyun-Kyun's brains.

Both brains receive the chapter dict and the session state dict and return
plain dicts, so they are interchangeable mid-session. The session engine
(app/session.py) decides *when* to ask, hint or move on; a brain only decides
*what* to say and how to score.

Question dict: {"text": str, "speak": str,
                "target": {"kind": "misconception"|"concept"|"probe", "id": str},
                "mood": "curious"|"confused"}
Hint: a line dict {"text": str, "speak": str}.
"text" is shown on screen; "speak" is fed to text-to-speech (Devanagari for
Hinglish, because Hindi voices read Roman Hindi badly). A brain without a
separate spoken form may set speak = text.
Score dict: the scoring JSON in the README, plus "feedback_speech".
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# Scoring weights (CLAUDE.md §4), shared so both brains turn their findings
# into a number the same way.
MISCONCEPTION_PENALTY = 30
WEIGHTS = {"correctness": 0.4, "reasoning": 0.3, "coverage": 0.3}
QUESTIONS_PER_SESSION = 3


def combine_score(correctness: int, reasoning: int, coverage: int) -> int:
    return round(WEIGHTS["correctness"] * correctness
                 + WEIGHTS["reasoning"] * reasoning
                 + WEIGHTS["coverage"] * coverage)


def reasoning_quality(reasoning: int) -> str:
    return "high" if reasoning >= 67 else "medium" if reasoning >= 34 else "low"


class Brain(ABC):
    name: str = "base"

    @abstractmethod
    def first_question(self, chapter: dict, session: dict) -> dict:
        """First follow-up question after the student's explanation."""

    @abstractmethod
    def next_question(self, chapter: dict, session: dict) -> dict:
        """Next follow-up question, given the answers so far."""

    @abstractmethod
    def hint(self, chapter: dict, session: dict) -> dict:
        """One small hint for the current question. Must never give the answer."""

    @abstractmethod
    def score(self, chapter: dict, session: dict) -> dict:
        """Final scoring JSON for the whole session."""
