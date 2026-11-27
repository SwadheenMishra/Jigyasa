"""FallbackBrain: try the LLM brain, fall back to the offline brain on anything.

Every call to the primary brain gets a hard deadline (8 s, CLAUDE.md §3).
On a timeout, network error, HTTP error, safety block or a reply that fails
validation, the same call is answered by the offline brain, mid-session, and
the student never sees an error.

After a failure the LLM is skipped for COOLDOWN_S seconds, so a dropped
network doesn't add an 8 s wait to every turn. A permanent failure (key
rejected, model not found) keeps it off until the server restarts with a new
config. /api/health reports "offline" plus the reason (llm_error) meanwhile.

Each call records which brain answered in session["last_brain"], so the UI
badge can show it per turn.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from app.brain.base import Brain

log = logging.getLogger("jigyasa.brain")

DEADLINE_S = 8.0
COOLDOWN_S = 60.0

# A timed-out call keeps running in its worker thread until its own socket
# timeout ends; the pool is sized so a few of those can't starve new calls.
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="llm")


class FallbackBrain(Brain):
    def __init__(self, primary: Brain, backup: Brain, deadline_s: float = DEADLINE_S, cooldown_s: float = COOLDOWN_S):
        self.primary = primary
        self.backup = backup
        self.deadline_s = deadline_s
        self.cooldown_s = cooldown_s
        self._cool_until = 0.0
        self._last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.backup.name if self.cooling_down else self.primary.name

    @property
    def cooling_down(self) -> bool:
        return time.monotonic() < self._cool_until

    @property
    def llm_error(self) -> str | None:
        """Why the LLM is currently not used (None when it is)."""
        return self._last_error if self.cooling_down else None

    def _fail(self, reason: str, permanent: bool = False) -> None:
        with self._lock:
            self._last_error = reason
            self._cool_until = float("inf") if permanent else time.monotonic() + self.cooldown_s

    def _run(self, method: str, chapter: dict, session: dict):
        if not self.cooling_down:
            # The primary brain must not mutate `session`; a timed-out call may still finish later.
            future = _pool.submit(getattr(self.primary, method), chapter, session)
            try:
                result = future.result(timeout=self.deadline_s)
                session["last_brain"] = self.primary.name
                return result
            except FutureTimeout:
                log.warning("LLM brain timed out after %.0f s on %s; using offline brain", self.deadline_s, method)
                self._fail(f"timed out after {self.deadline_s:.0f} s")
            except Exception as e:  # noqa: BLE001 - any failure means: use the offline brain
                permanent = bool(getattr(e, "permanent", False))
                log.warning("LLM brain failed on %s (%s); using offline brain%s", method, e,
                            " until restart" if permanent else "")
                self._fail(str(e)[:200], permanent)
        session["last_brain"] = self.backup.name
        return getattr(self.backup, method)(chapter, session)

    def first_question(self, chapter: dict, session: dict) -> dict:
        return self._run("first_question", chapter, session)

    def next_question(self, chapter: dict, session: dict) -> dict:
        return self._run("next_question", chapter, session)

    def hint(self, chapter: dict, session: dict) -> dict:
        return self._run("hint", chapter, session)

    def score(self, chapter: dict, session: dict) -> dict:
        return self._run("score", chapter, session)
