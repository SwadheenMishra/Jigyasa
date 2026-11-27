"""Content tests for all chapters: structure, topic matching, misconception detection."""

import os
import re
import tempfile

os.environ.setdefault("JIGYASA_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("GEMINI_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.brain.offline import OfflineBrain  # noqa: E402
from app.content import load_chapters, match_topic  # noqa: E402
from app.main import app  # noqa: E402

DEV = re.compile(r"[ऀ-ॿ]")
CHAPTERS = load_chapters()
brain = OfflineBrain()


def _lines(ch):
    """Every spoken line object in a chapter."""
    yield ch["opening"]
    yield ch["redirect"]
    for c in ch["concepts"]:
        yield from (c["name"], c["question"], c["probe"], c["hint"])
    for m in ch["misconceptions"]:
        yield from (m["name"], m["question"], m["hint"], m["correct_idea"])


def test_three_chapters_in_class_order():
    assert list(CHAPTERS) == ["fractions", "photosynthesis", "gravity"]


@pytest.mark.parametrize("cid", list(CHAPTERS))
def test_chapter_structure(cid):
    ch = CHAPTERS[cid]
    assert len(ch["concepts"]) >= 5 and len(ch["misconceptions"]) == 3
    for ln in _lines(ch):
        assert ln["hi"] and ln["en"] and DEV.search(ln["dev"]), ln
    for item in ch["concepts"] + ch["misconceptions"]:
        q = item["question"]["hi"]
        assert len(q.split()) < 15, q  # spec: questions under 15 words
    for c in ch["concepts"]:
        assert any(DEV.search(k) for k in c["keywords"]), c["id"]  # hi-IN returns Devanagari
        assert any(not DEV.search(k) for k in c["keywords"]), c["id"]


@pytest.mark.parametrize("said,expected", [
    ("Fractions samjhana hai", "fractions"),
    ("मुझे भिन्न समझाना है", "fractions"),
    ("gravity ke baare mein batata hoon", "gravity"),
    ("गुरुत्वाकर्षण", "gravity"),
    ("ग्रेविटी समझाना है", "gravity"),
    ("photosynthesis samjhana hai", "photosynthesis"),
])
def test_topic_match(said, expected):
    assert match_topic(said) == expected


def _misconceptions(cid, text):
    return [m["item"]["id"] for m in brain.analyse(CHAPTERS[cid], text)["misconceptions"]]


@pytest.mark.parametrize("cid,said,expected", [
    # Fractions
    ("fractions", "1/8 bada hai 1/4 se kyunki 8 bada number hai", "bigger_denominator_bigger"),
    ("fractions", "one eighth is bigger than one fourth", "bigger_denominator_bigger"),
    ("fractions", "1/2 + 1/3 karne ke liye upar wale aur neeche wale jodo, 2/5 aata hai", "add_tops_and_bottoms"),
    ("fractions", "fraction hamesha 1 se chhota hota hai", "always_less_than_one"),
    ("fractions", "एक बटा आठ बड़ा है", "bigger_denominator_bigger"),
    # Gravity
    ("gravity", "bhari cheez jaldi girti hai halki cheez se", "heavier_falls_faster"),
    ("gravity", "heavier objects fall faster", "heavier_falls_faster"),
    ("gravity", "space mein gravity nahi hoti isliye astronaut float karte hain", "no_gravity_in_space"),
    ("gravity", "gravity sirf girti hui cheezon par lagti hai", "only_falling_things"),
    ("gravity", "भारी चीज़ जल्दी गिरती है", "heavier_falls_faster"),
])
def test_misconception_detected(cid, said, expected):
    assert expected in _misconceptions(cid, said)


@pytest.mark.parametrize("cid,said", [
    ("fractions", "1/4 bada hai, 1/8 se bada, kyunki tukde bade hain"),
    ("fractions", "fraction hamesha 1 se chhota nahi hota, 3/2 bhi hota hai"),
    ("fractions", "same denominator ho toh upar wale jodo"),
    ("gravity", "bhari aur halki cheez ek saath girti hain agar hawa na ho"),
    ("gravity", "space mein bhi gravity hoti hai, chand isliye ghoomta hai"),
    ("gravity", "heavier objects do not fall faster"),
])
def test_correct_ideas_not_flagged(cid, said):
    assert _misconceptions(cid, said) == []


@pytest.mark.parametrize("cid,explanation,first_q_contains", [
    ("fractions", "Fraction matlab hissa. 1/8 bada hai 1/4 se kyunki 8 bada hai.", "8 logon"),
    ("gravity", "Gravity ek force hai. Bhari cheez jaldi girti hai.", "kitaab"),
])
def test_full_session_each_chapter(cid, explanation, first_q_contains):
    with TestClient(app) as c:
        sid = c.post("/api/session/start", json={"chapter_id": cid}).json()["session_id"]
        q = c.post(f"/api/session/{sid}/explain", json={"transcript": explanation}).json()
        assert first_q_contains in q["question"]
        for ans in ["kyunki tukde chhote hote hain", "pata nahi", "pata nahi", "isliye dharti kheenchti hai"]:
            r = c.post(f"/api/session/{sid}/answer", json={"transcript": ans}).json()
        assert r["action"] == "done"
        result = c.post(f"/api/session/{sid}/finish").json()
        assert result["misconceptions"] and 0 <= result["score"] <= 100
        assert set(result["breakdown"]) == {"correctness", "reasoning", "coverage"}
        assert DEV.search(result["feedback_speech"])
