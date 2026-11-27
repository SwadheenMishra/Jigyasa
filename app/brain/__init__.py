"""Kyun-Kyun's brains. Use get_brain() to get the one that is active right now.

No key            -> OfflineBrain (rule-based, always works).
GEMINI_API_KEY set -> FallbackBrain(GeminiBrain, OfflineBrain): the AI brain,
                      falling back to offline on any error or after 8 s.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

log = logging.getLogger("jigyasa.brain")


def llm_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def get_brain():
    return _build(
        os.getenv("GEMINI_API_KEY", "").strip(),
        os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini",
        os.getenv("GEMINI_MODEL", "").strip(),
    )


@lru_cache(maxsize=4)  # one instance per config, so the fallback cooldown is shared
def _build(api_key: str, provider: str, model: str):
    # Imported lazily to avoid a cycle (content -> brain.text -> brain/__init__).
    from app.brain.offline import OfflineBrain

    offline = OfflineBrain()
    if not api_key:
        return offline
    if provider != "gemini":
        log.warning("LLM_PROVIDER=%r is not supported yet; using the offline brain", provider)
        return offline

    from app.brain.fallback import FallbackBrain
    from app.brain.llm import GeminiBrain

    return FallbackBrain(GeminiBrain(api_key, model or None), offline)
