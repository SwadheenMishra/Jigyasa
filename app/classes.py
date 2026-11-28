"""Teacher classes and the class dashboard.

Privacy model (users are minors):
  * Students join with a 6-digit join code and a first name. The code alone
    gives NO access to anyone's data.
  * Creating a class also returns a random teacher key. The dashboard and the
    transcripts need that key (sent as the X-Teacher-Key header). Only its
    SHA-256 hash is stored.
  * The dashboard shows transcripts and scores only; audio is never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from app import db
from app.content import get_chapter, load_chapters, pick

CODE_ATTEMPTS = 25
OTHER = {"en": "Other wrong ideas", "hi": "Doosri galat baatein"}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def clean_name(name: str | None, limit: int = 40) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:limit]


def create_class(name: str, demo: bool = False) -> tuple[str, str]:
    """Returns (join code, teacher key)."""
    key = secrets.token_urlsafe(18)
    for _ in range(CODE_ATTEMPTS):
        code = f"{secrets.randbelow(900000) + 100000}"
        if db.insert_class(code, clean_name(name, 60) or "My class", _hash(key), demo):
            return code, key
    raise RuntimeError("could not allocate a class code")


def check_key(cls: dict, key: str | None) -> bool:
    return bool(key) and hmac.compare_digest(cls["key_hash"], _hash(key))


# ---------- dashboard ----------

def _ids(chapter: dict, result: dict, field: str) -> list[str]:
    """Concept ids from a result; older results only have display names."""
    if f"{field}_ids" in result:
        return list(result[f"{field}_ids"])
    names = set(result.get(f"concepts_{field}", []))
    return [c["id"] for c in chapter["concepts"] if names & {pick(c["name"], "hi"), pick(c["name"], "en")}]


def _finished_at(s: dict) -> str:
    return s.get("finished_at") or s.get("created_at") or ""


def dashboard(code: str) -> dict:
    cls = db.get_class(code)
    sessions = db.class_sessions(code)

    # Latest finished session per (student, chapter): "each student's latest score per chapter".
    latest: dict[tuple[str, str], dict] = {}
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for s in sessions:
        name = clean_name(s.get("student_name")) or "Anonymous"
        key = name.lower()
        display.setdefault(key, name)
        counts[key] = counts.get(key, 0) + 1
        slot = (key, s["chapter_id"])
        if slot not in latest or _finished_at(s) > _finished_at(latest[slot]):
            latest[slot] = s

    chapters = []
    all_reteach = []
    for ch in load_chapters().values():
        group = [s for (_, cid), s in latest.items() if cid == ch["id"]]
        n = len(group)
        mis_count: dict[str, int] = {}
        miss_count: dict[str, int] = {}
        for s in group:
            for mid in {m.get("id", "other") for m in s["result"].get("misconceptions", [])}:
                mis_count[mid] = mis_count.get(mid, 0) + 1
            for cid in _ids(ch, s["result"], "missing"):
                miss_count[cid] = miss_count.get(cid, 0) + 1

        names = {m["id"]: m["name"] for m in ch["misconceptions"]}
        misconceptions = sorted(
            ({"id": mid, "name_en": pick(names[mid], "en") if mid in names else OTHER["en"],
              "name_hi": pick(names[mid], "hi") if mid in names else OTHER["hi"],
              "count": c, "percent": round(100 * c / n)} for mid, c in mis_count.items()),
            key=lambda m: (-m["count"], m["id"] == "other", m["id"]),
        )
        concept_names = {c["id"]: c["name"] for c in ch["concepts"]}
        reteach = sorted(
            ({"chapter_id": ch["id"], "chapter": ch["title"], "emoji": ch["emoji"], "id": cid,
              "name_en": pick(concept_names[cid], "en"), "name_hi": pick(concept_names[cid], "hi"),
              "count": c, "percent": round(100 * c / n)} for cid, c in miss_count.items() if cid in concept_names),
            key=lambda r: (-r["count"], r["id"]),
        )
        all_reteach += reteach
        chapters.append({
            "id": ch["id"], "title": ch["title"], "title_hi": ch["title_hi"], "emoji": ch["emoji"], "class": ch["class"],
            "students": n,
            "average": round(sum(s["result"]["score"] for s in group) / n) if n else None,
            "misconceptions": misconceptions,
            "reteach": reteach[:2],
        })

    students = []
    for key, name in display.items():
        per = {cid: {"score": s["result"]["score"], "session_id": s["id"], "at": _finished_at(s),
                     "misconceptions": len(s["result"].get("misconceptions", []))}
               for (k, cid), s in latest.items() if k == key}
        scores = [v["score"] for v in per.values()]
        students.append({"name": name, "sessions": counts[key], "chapters": per,
                         "average": round(sum(scores) / len(scores)) if scores else None})
    students.sort(key=lambda st: st["name"].lower())

    latest_scores = [s["result"]["score"] for s in latest.values()]
    # "What to reteach": the 2 concepts missed by the biggest share of students, across chapters.
    top = sorted(all_reteach, key=lambda r: (-r["percent"], -r["count"]))[:2]
    return {
        "class": {"code": cls["code"], "name": cls["name"], "demo": bool(cls["demo"]), "created_at": cls["created_at"]},
        "totals": {"students": len(display), "sessions": len(sessions),
                   "average": round(sum(latest_scores) / len(latest_scores)) if latest_scores else None},
        "chapters": chapters,
        "reteach": top,
        "students": students,
    }


def session_detail(code: str, session_id: str) -> dict | None:
    s = db.load_session(session_id)
    if not s or s.get("class_code") != code:
        return None
    ch = get_chapter(s["chapter_id"])
    return {
        "id": s["id"],
        "student_name": s.get("student_name"),
        "chapter": {"id": ch["id"], "title": ch["title"], "emoji": ch["emoji"]} if ch else {"id": s["chapter_id"]},
        "language": s["language"],
        "brain": s.get("last_brain") or s.get("brain"),
        "explanation": s.get("explanation", ""),
        "answers": [{"question": a["question"], "transcript": a["transcript"], "status": a["status"],
                     "hints": a.get("hints", 0)} for a in s.get("answers", [])],
        "copy_suspected": bool(s.get("own_words_asked")),
        "result": s.get("result"),
        "finished_at": s.get("finished_at"),
    }


# ---------- sample class for judges / demo video ----------

def seed_demo() -> tuple[str, str]:
    """A class of fictional students whose (scripted) sessions go through the real
    offline brain, so the dashboard has something to show. Clearly labelled as sample data."""
    from app import session as engine
    from app.brain.offline import OfflineBrain
    from app.demo_data import DEMO_CLASS_NAME, DEMO_STUDENTS

    code, key = create_class(DEMO_CLASS_NAME, demo=True)
    brain = OfflineBrain()
    start = datetime.now(timezone.utc) - timedelta(days=3)
    for i, (student, chapter_id, explanation, answers) in enumerate(DEMO_STUDENTS):
        ch = get_chapter(chapter_id)
        st = engine.new_session(ch, "hinglish", brain, student, code)
        engine.handle_explain(st, ch, explanation, "pause", brain)
        pool = list(answers)
        for _ in range(12):  # enough turns for 3 questions incl. hints
            if st["stage"] != "questions":
                break
            engine.handle_answer(st, ch, pool.pop(0) if pool else "pata nahi", "pause", brain)
        engine.finish(st, ch, brain)
        stamp = (start + timedelta(minutes=37 * i)).isoformat(timespec="seconds")
        st["created_at"] = st["finished_at"] = stamp
        db.save_session(st)
    return code, key
