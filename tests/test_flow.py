"""End-to-end API tests for the offline brain. Run: pip install -r requirements-dev.txt && pytest"""

import os
import tempfile

os.environ["JIGYASA_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.brain.text import normalize  # noqa: E402
from app.main import app  # noqa: E402

SOIL_EXPLANATION = (
    "Photosynthesis mein plant mitti se khana leta hai. Patte hare hote hain "
    "aur dhoop mein plant badhta hai."
)


def start(client, language="hinglish"):
    r = client.post("/api/session/start", json={"chapter_id": "photosynthesis", "language": language})
    assert r.status_code == 200
    return r.json()


def test_health_offline_without_key():
    with TestClient(app) as c:
        assert c.get("/api/health").json() == {"status": "ok", "brain": "offline", "llm_configured": False, "llm_error": None}


def test_index_served():
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200 and "Jigyasa" in r.text


def test_topic_match_hinglish_and_devanagari():
    with TestClient(app) as c:
        for said in ["Photosynthesis samjhana hai", "फोटोसिंथेसिस समझाना है", "photo sin thesis"]:
            assert c.post("/api/match", json={"transcript": said}).json()["chapter_id"] == "photosynthesis"
        assert c.post("/api/match", json={"transcript": "cricket match"}).json()["chapter_id"] is None


def test_vocab_fixes():
    fixes = {"clorofil": "chlorophyll", "photo sin thesis": "photosynthesis"}
    assert normalize("Clorofil, photo-sin-thesis!", fixes) == "chlorophyll photosynthesis"


def test_soil_misconception_full_flow():
    with TestClient(app) as c:
        s = start(c)
        sid = s["session_id"]
        assert "photosynthesis" in s["say"].lower()

        q1 = c.post(f"/api/session/{sid}/explain", json={"transcript": SOIL_EXPLANATION}).json()
        assert q1["action"] == "question"
        assert "gamle ki mitti" in q1["question"].lower()  # biggest misconception first
        assert len(q1["question"].split()) < 15

        # First "pata nahi" -> hint, second -> move on
        h = c.post(f"/api/session/{sid}/answer", json={"transcript": "pata nahi"}).json()
        assert h["action"] == "hint" and h["q_number"] == 1
        q2 = c.post(f"/api/session/{sid}/answer", json={"transcript": "पता नहीं"}).json()
        assert q2["action"] == "question" and q2["q_number"] == 2

        q3 = c.post(f"/api/session/{sid}/answer",
                    json={"transcript": "kyunki plant hawa se carbon dioxide leta hai"}).json()
        assert q3["action"] == "question" and q3["q_number"] == 3

        done = c.post(f"/api/session/{sid}/answer",
                      json={"transcript": "oxygen chhodta hai isliye hum saans le paate hain"}).json()
        assert done["action"] == "done"

        result = c.post(f"/api/session/{sid}/finish").json()
        assert 0 <= result["score"] <= 100
        assert result["misconceptions"][0]["id"] == "food_from_soil"
        assert "Dhoop (sunlight)" in result["concepts_covered"]
        assert result["feedback_in_student_language"].count(".") + result["feedback_in_student_language"].count("!") >= 3


def test_negated_misconception_not_flagged():
    with TestClient(app) as c:
        sid = start(c)["session_id"]
        c.post(f"/api/session/{sid}/explain",
               json={"transcript": "Plant mitti se khana nahi leta, woh dhoop aur paani se khana banata hai"})
        for _ in range(3):
            c.post(f"/api/session/{sid}/answer", json={"transcript": "kyunki patte hare hote hain"})
        result = c.post(f"/api/session/{sid}/finish").json()
        assert result["misconceptions"] == []


def test_noise_and_offtopic():
    with TestClient(app) as c:
        sid = start(c)["session_id"]
        assert c.post(f"/api/session/{sid}/explain", json={"transcript": "", "reason": "noise"}).json()["action"] == "noise"
        assert c.post(f"/api/session/{sid}/explain",
                      json={"transcript": "kal cricket match dekha bahut maza aaya"}).json()["action"] == "redirect"
        q = c.post(f"/api/session/{sid}/explain", json={"transcript": SOIL_EXPLANATION}).json()
        assert q["action"] == "question"
        r = c.post(f"/api/session/{sid}/answer", json={"transcript": "", "reason": "noise"}).json()
        assert r["action"] == "noise" and q["question"] in r["say"]
        # silence counts as "pata nahi" -> hint
        assert c.post(f"/api/session/{sid}/answer", json={"transcript": "", "reason": "silence"}).json()["action"] == "hint"


def test_english_lines():
    with TestClient(app) as c:
        s = start(c, "en")
        assert s["say"].startswith("Wow")
        q = c.post(f"/api/session/{s['session_id']}/explain",
                   json={"transcript": "Plants take food from the soil using roots"}).json()
        assert "soil" in q["question"].lower()


def test_speech_is_devanagari_for_hinglish_and_english_for_en():
    import re
    dev = re.compile(r"[ऀ-ॿ]")
    with TestClient(app) as c:
        s = start(c)
        assert dev.search(s["speak"]) and not dev.search(s["say"])
        q = c.post(f"/api/session/{s['session_id']}/explain", json={"transcript": SOIL_EXPLANATION}).json()
        assert "गमले की मिट्टी" in q["speak"]
        h = c.post(f"/api/session/{s['session_id']}/answer", json={"transcript": "pata nahi"}).json()
        assert dev.search(h["speak"])
        for _ in range(2):
            c.post(f"/api/session/{s['session_id']}/answer", json={"transcript": "pata nahi"})
        c.post(f"/api/session/{s['session_id']}/answer", json={"transcript": "pata nahi"})
        r = c.post(f"/api/session/{s['session_id']}/finish").json()
        assert dev.search(r["feedback_speech"]) and "{x}" not in r["feedback_speech"]

        e = start(c, "en")
        assert e["speak"] == e["say"]


def test_finish_before_explain_is_rejected():
    with TestClient(app) as c:
        sid = start(c)["session_id"]
        assert c.post(f"/api/session/{sid}/finish").status_code == 409


# ---------- milestone 5: error handling ----------

TEXTBOOK = (
    "Photosynthesis is the process by which green plants prepare their food. In the presence of sunlight, "
    "the chlorophyll in the leaves absorbs light energy. Plants take carbon dioxide from the air and water "
    "from the roots, and with the help of this energy they make glucose. Oxygen is released as a by-product, "
    "therefore photosynthesis is very important for all living beings on the earth."
)


def test_fillers_count_as_noise():
    with TestClient(app) as c:
        sid = start(c)["session_id"]
        for filler in ["hmm", "uh umm", "हम्म", "a"]:
            assert c.post(f"/api/session/{sid}/explain", json={"transcript": filler}).json()["action"] == "noise"
        # nothing was scored: still in the explain stage
        assert c.get(f"/api/session/{sid}").json()["stage"] == "explain"


def test_copied_answer_asks_own_words_and_lowers_reasoning():
    with TestClient(app) as c:
        sid = start(c)["session_id"]
        c.post(f"/api/session/{sid}/explain", json={"transcript": TEXTBOOK})
        state = c.get(f"/api/session/{sid}").json()
        assert state["copy_suspected"] is True
        r = c.post(f"/api/session/{sid}/answer", json={"transcript": "plant ko achha lagta hai"}).json()  # on-topic but weak
        assert r["action"] == "question" and "apne words" in r["question"]
        for ans in ["kyunki patte dhoop lete hain", "isliye oxygen nikalti hai"]:
            r = c.post(f"/api/session/{sid}/answer", json={"transcript": ans}).json()
        assert r["action"] == "done"
        result = c.post(f"/api/session/{sid}/finish").json()
        assert result["breakdown"]["reasoning"] == 33  # 2 good answers (67) halved


def test_textbook_explanation_with_strong_answers_is_not_penalised():
    with TestClient(app) as c:
        sid = start(c)["session_id"]
        c.post(f"/api/session/{sid}/explain", json={"transcript": TEXTBOOK})
        for ans in ["kyunki raat ko dhoop nahi hoti", "isliye patte hare hote hain", "because roots se paani aata hai"]:
            r = c.post(f"/api/session/{sid}/answer", json={"transcript": ans}).json()
            assert "apne words" not in (r.get("question") or "")
        result = c.post(f"/api/session/{sid}/finish").json()
        assert result["breakdown"]["reasoning"] == 100


def test_short_own_explanation_not_suspected():
    with TestClient(app) as c:
        sid = start(c)["session_id"]
        c.post(f"/api/session/{sid}/explain", json={"transcript": SOIL_EXPLANATION})
        assert c.get(f"/api/session/{sid}").json()["copy_suspected"] is False
