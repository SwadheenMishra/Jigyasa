"""SQLite storage. Only transcripts and scores are saved, never audio.

The file lives at data/jigyasa.db (/srv/data in the container, a named
Docker volume) and is created on first start.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("JIGYASA_DB", Path(__file__).resolve().parent.parent / "data" / "jigyasa.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    chapter_id   TEXT NOT NULL,
    language     TEXT NOT NULL,
    student_name TEXT,
    class_code   TEXT,
    stage        TEXT NOT NULL,
    score        INTEGER,
    state        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sessions_class ON sessions(class_code, chapter_id);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


def save_session(state: dict) -> None:
    score = state["result"]["score"] if state.get("result") else None
    with connect() as con:
        con.execute(
            """INSERT INTO sessions (id, chapter_id, language, student_name, class_code, stage, score, state, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET stage=excluded.stage, score=excluded.score,
                   state=excluded.state, updated_at=CURRENT_TIMESTAMP""",
            (state["id"], state["chapter_id"], state["language"], state.get("student_name"),
             state.get("class_code"), state["stage"], score,
             json.dumps(state, ensure_ascii=False), state["created_at"]),
        )


def load_session(session_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return json.loads(row["state"]) if row else None
