"""Jigyasa — FastAPI entry point.

Serves the JSON API under /api and the plain-HTML frontend from /static.
The app must start with no .env and no keys; without a key it uses the
offline (rule-based) brain.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db, session as engine
from app.brain import get_brain, llm_configured
from app.content import (DEFAULT_LANGUAGE, LANGUAGES, get_chapter, load_chapters,
                         match_topic, public_chapter)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    load_chapters()  # fail fast on a broken chapter file
    yield


app = FastAPI(title="Jigyasa", version="0.4.0", lifespan=lifespan)


# ---------- request bodies ----------

class StartBody(BaseModel):
    chapter_id: str = Field(max_length=40)
    language: str = Field(default=DEFAULT_LANGUAGE, max_length=20)
    class_code: str | None = Field(default=None, max_length=6)
    student_name: str | None = Field(default=None, max_length=40)


class TurnBody(BaseModel):
    transcript: str = Field(default="", max_length=6000)
    # Why the turn ended: pause | done | timeout | typed | silence | noise
    reason: str = Field(default="pause", max_length=20)


class MatchBody(BaseModel):
    transcript: str = Field(default="", max_length=500)


# ---------- routes ----------

@app.get("/api/health")
def health() -> dict:
    # brain: what answers right now ("offline" also during the cooldown after an LLM failure).
    # llm_configured: whether a key is set at all. The key itself is never exposed.
    brain = get_brain()
    return {"status": "ok", "brain": brain.name, "llm_configured": llm_configured(),
            "llm_error": getattr(brain, "llm_error", None)}


@app.get("/api/chapters")
def chapters() -> dict:
    return {
        "chapters": [public_chapter(c) for c in load_chapters().values()],
        "languages": [{"id": k, **v} for k, v in LANGUAGES.items()],
        "default_language": DEFAULT_LANGUAGE,
    }


@app.post("/api/match")
def match(body: MatchBody) -> dict:
    return {"chapter_id": match_topic(body.transcript)}


@app.post("/api/session/start")
def start(body: StartBody) -> dict:
    chapter = _chapter(body.chapter_id)
    language = body.language if body.language in LANGUAGES else DEFAULT_LANGUAGE
    brain = get_brain()
    state = engine.new_session(chapter, language, brain, body.student_name, body.class_code)
    db.save_session(state)
    return {"session_id": state["id"], "chapter": public_chapter(chapter), "brain": brain.name,
            **engine.opening(chapter, state)}


@app.post("/api/session/{session_id}/explain")
def explain(session_id: str, body: TurnBody) -> dict:
    return _turn(session_id, body, engine.handle_explain)


@app.post("/api/session/{session_id}/answer")
def answer(session_id: str, body: TurnBody) -> dict:
    return _turn(session_id, body, engine.handle_answer)


@app.post("/api/session/{session_id}/finish")
def finish(session_id: str) -> dict:
    state = _session(session_id)
    try:
        result = engine.finish(state, _chapter(state["chapter_id"]), get_brain())
    except engine.SessionError as e:
        raise HTTPException(409, str(e)) from e
    db.save_session(state)
    return {**result, "brain": state.get("last_brain") or get_brain().name}


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict:
    return _session(session_id)


# ---------- helpers ----------

def _turn(session_id: str, body: TurnBody, handler) -> dict:
    state = _session(session_id)
    try:
        brain = get_brain()
        reply = handler(state, _chapter(state["chapter_id"]), body.transcript, body.reason, brain)
    except engine.SessionError as e:
        raise HTTPException(409, str(e)) from e
    db.save_session(state)
    # Which brain produced this turn (for the badge); turns that needed no brain keep the last one.
    return {**reply, "brain": state.get("last_brain") or brain.name}


def _chapter(chapter_id: str) -> dict:
    chapter = get_chapter(chapter_id)
    if not chapter:
        raise HTTPException(404, "Unknown chapter")
    return chapter


def _session(session_id: str) -> dict:
    state = db.load_session(session_id)
    if not state:
        raise HTTPException(404, "Unknown session")
    return state


# Mounted last so /api routes take priority. html=True serves index.html at "/".
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
