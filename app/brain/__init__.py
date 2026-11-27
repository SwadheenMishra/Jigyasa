"""Kyun-Kyun's brains. Use get_brain() to get the one that is active right now."""


def get_brain():
    # Imported lazily to avoid a cycle (content -> brain.text -> brain/__init__).
    from app.brain.offline import OfflineBrain

    # Milestone 4 adds the LLM brain here, wrapped so that any error or
    # timeout falls back to the offline brain mid-session.
    return OfflineBrain()
