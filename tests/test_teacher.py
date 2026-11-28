"""Teacher dashboard: classes, join codes, teacher key, aggregation, sample class."""

import os
import tempfile

os.environ.setdefault("JIGYASA_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SOIL = "Plant mitti se khana leta hai. Patte hare hote hain aur dhoop mein plant badhta hai."
GOOD = ("Patte dhoop ki roshni se khana banate hain. Woh hawa se carbon dioxide aur jad se paani lete hain, "
        "aur glucose banate hain. Oxygen bahar nikalti hai.")


def run_session(c, code, name, explanation, answers=("kyunki dhoop chahiye", "isliye", "kyunki paani")):
    r = c.post("/api/session/start", json={"chapter_id": "photosynthesis", "class_code": code, "student_name": name})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    c.post(f"/api/session/{sid}/explain", json={"transcript": explanation})
    for a in answers:
        c.post(f"/api/session/{sid}/answer", json={"transcript": a})
    return sid, c.post(f"/api/session/{sid}/finish").json()


def new_class(c, name="7B Science"):
    r = c.post("/api/class", json={"name": name}).json()
    assert len(r["code"]) == 6 and r["code"].isdigit() and len(r["teacher_key"]) > 20
    return r["code"], {"X-Teacher-Key": r["teacher_key"]}


def test_join_code_alone_gives_no_access():
    with TestClient(app) as c:
        code, key = new_class(c)
        assert c.get(f"/api/class/{code}").json() == {"code": code, "name": "7B Science"}  # students can check a code
        assert c.get(f"/api/class/{code}/dashboard").status_code == 403
        assert c.get(f"/api/class/{code}/dashboard", headers={"X-Teacher-Key": "guess"}).status_code == 403
        assert c.get(f"/api/class/{code}/dashboard", headers=key).status_code == 200
        assert c.get("/api/class/000000/dashboard", headers=key).status_code == 404
        assert c.get("/api/class/12ab56").status_code == 422


def test_joining_needs_valid_code_and_name():
    with TestClient(app) as c:
        code, _ = new_class(c)
        assert c.post("/api/session/start", json={"chapter_id": "fractions", "class_code": "999999",
                                                  "student_name": "Asha"}).status_code == 404
        assert c.post("/api/session/start", json={"chapter_id": "fractions", "class_code": code}).status_code == 422
        assert c.post("/api/session/start", json={"chapter_id": "fractions"}).status_code == 200  # solo use


def test_dashboard_aggregates_latest_scores_and_misconceptions():
    with TestClient(app) as c:
        code, key = new_class(c)
        run_session(c, code, "Asha", SOIL)
        run_session(c, code, "Ravi", SOIL)
        run_session(c, code, "Ravi", GOOD)  # Ravi's latest: no misconception
        run_session(c, code, "Meena", GOOD)
        _, other = run_session(c, "", "", SOIL)  # solo session: not in the class

        d = c.get(f"/api/class/{code}/dashboard", headers=key).json()
        assert d["totals"]["students"] == 3 and d["totals"]["sessions"] == 4
        ph = next(ch for ch in d["chapters"] if ch["id"] == "photosynthesis")
        assert ph["students"] == 3
        soil = ph["misconceptions"][0]
        assert soil["id"] == "food_from_soil" and soil["count"] == 1 and soil["percent"] == 33  # only Asha, latest
        ravi = next(s for s in d["students"] if s["name"] == "Ravi")
        assert ravi["sessions"] == 2 and "photosynthesis" in ravi["chapters"]
        assert all(len(d["reteach"]) <= 2 for _ in [0])

        # click-through to the transcript
        sid = ravi["chapters"]["photosynthesis"]["session_id"]
        detail = c.get(f"/api/class/{code}/session/{sid}", headers=key).json()
        assert detail["student_name"] == "Ravi" and "glucose" in detail["explanation"]
        assert len(detail["answers"]) == 3 and detail["result"]["score"] == ravi["chapters"]["photosynthesis"]["score"]
        assert c.get(f"/api/class/{code}/session/{sid}").status_code == 403


def test_teacher_cannot_read_other_classes_sessions():
    with TestClient(app) as c:
        code_a, key_a = new_class(c, "A")
        code_b, _ = new_class(c, "B")
        sid, _ = run_session(c, code_b, "Zoya", SOIL)
        assert c.get(f"/api/class/{code_a}/session/{sid}", headers=key_a).status_code == 404


def test_sample_class():
    with TestClient(app) as c:
        r = c.post("/api/class/demo").json()
        d = c.get(f"/api/class/{r['code']}/dashboard", headers={"X-Teacher-Key": r["teacher_key"]}).json()
        assert d["class"]["demo"] is True and "Sample" in d["class"]["name"]
        assert d["totals"]["students"] == 10 and d["totals"]["sessions"] == 24
        ph = next(ch for ch in d["chapters"] if ch["id"] == "photosynthesis")
        top = ph["misconceptions"][0]
        assert top["id"] == "food_from_soil" and top["percent"] == 60  # "60% think plants eat soil"
        assert len(d["reteach"]) == 2
        for ch in d["chapters"]:
            assert ch["students"] > 0 and 0 <= ch["average"] <= 100


def test_demo_session_never_joins_a_class_and_reports_targets():
    with TestClient(app) as c:
        code, key = new_class(c)
        r = c.post("/api/session/start", json={"chapter_id": "photosynthesis", "demo": True,
                                               "class_code": code, "student_name": "Judge"}).json()
        sid = r["session_id"]
        q = c.post(f"/api/session/{sid}/explain", json={"transcript": SOIL, "reason": "typed"}).json()
        assert q["target_id"] == "food_from_soil"  # Demo mode picks its scripted answer from this
        state = c.get(f"/api/session/{sid}").json()
        assert state["demo"] is True and state["class_code"] is None
        assert c.get(f"/api/class/{code}/dashboard", headers=key).json()["totals"]["sessions"] == 0
