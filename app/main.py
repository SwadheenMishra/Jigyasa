"""Jigyasa — FastAPI entry point.

Serves the JSON API under /api and the plain-HTML frontend from /static.
The app must start with no .env and no keys; without a key it uses the
offline (rule-based) brain.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Path as PathParam
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import classes, db, session as engine
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


app = FastAPI(title="Jigyasa", version="0.6.0", lifespan=lifespan)
CODE = r"^\d{6}$"  # 6-digit class join code


# ---------- request bodies ----------

class StartBody(BaseModel):
    chapter_id: str = Field(max_length=40)
    language: str = Field(default=DEFAULT_LANGUAGE, max_length=20)
    class_code: str | None = Field(default=None, max_length=6)
    student_name: str | None = Field(default=None, max_length=40)
    demo: bool = False  # scripted Demo mode


class TurnBody(BaseModel):
    transcript: str = Field(default="", max_length=6000)
    # Why the turn ended: pause | done | timeout | typed | silence | noise
    reason: str = Field(default="pause", max_length=20)


class MatchBody(BaseModel):
    transcript: str = Field(default="", max_length=500)


class ClassBody(BaseModel):
    name: str = Field(default="", max_length=60)


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
    class_code, student_name = body.class_code or None, classes.clean_name(body.student_name) or None
    if body.demo:  # demo sessions never count towards a class
        class_code = student_name = None
    if class_code:
        if not db.get_class(class_code):
            raise HTTPException(404, "Unknown class code")
        if not student_name:
            raise HTTPException(422, "A name is needed to join a class")
    brain = get_brain()
    state = engine.new_session(chapter, language, brain, student_name, class_code, demo=body.demo)
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


# ---------- classes & teacher dashboard ----------

@app.post("/api/class")
def create_class(body: ClassBody) -> dict:
    """Returns the join code (for students) and the teacher key (for the dashboard; shown once)."""
    code, key = classes.create_class(body.name)
    return {"code": code, "teacher_key": key, "name": db.get_class(code)["name"]}


@app.post("/api/class/demo")
def create_demo_class() -> dict:
    """A sample class with fictional students, scored by the real offline brain."""
    code, key = classes.seed_demo()
    return {"code": code, "teacher_key": key, "name": db.get_class(code)["name"], "demo": True}


@app.get("/api/class/{code}")
def class_info(code: str = PathParam(pattern=CODE)) -> dict:
    """Public: lets a student check a join code. Reveals only the class name."""
    return {"code": code, "name": _class(code)["name"]}


@app.get("/api/class/{code}/dashboard")
def class_dashboard(code: str = PathParam(pattern=CODE), x_teacher_key: str | None = Header(default=None)) -> dict:
    _teacher(code, x_teacher_key)
    return classes.dashboard(code)


@app.get("/api/class/{code}/session/{session_id}")
def class_session(session_id: str, code: str = PathParam(pattern=CODE),
                  x_teacher_key: str | None = Header(default=None)) -> dict:
    _teacher(code, x_teacher_key)
    detail = classes.session_detail(code, session_id)
    if not detail:
        raise HTTPException(404, "Unknown session")
    return detail


# ---------- helpers ----------

def _class(code: str) -> dict:
    cls = db.get_class(code)
    if not cls:
        raise HTTPException(404, "Unknown class code")
    return cls


def _teacher(code: str, key: str | None) -> dict:
    cls = _class(code)
    if not classes.check_key(cls, key):
        raise HTTPException(403, "Teacher key needed")
    return cls


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
class RevalidatedStatic(StaticFiles):
    """Static files that browsers must re-check (cheap 304 via ETag), so an
    updated app is never shown with stale CSS/JS."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", RevalidatedStatic(directory=STATIC_DIR, html=True), name="static")
