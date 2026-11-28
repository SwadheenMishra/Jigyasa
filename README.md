# Jigyasa (जिज्ञासा)

> **You can copy an answer. You can't copy understanding.**

Jigyasa ("the desire to know") is a **voice-first learning app** for students in classes 6–12. A student
explains a school concept **out loud** to **Kyun-Kyun**, a curious little sibling, who keeps asking "why?"
until it is clear whether the student really understands — then gives a 0–100 understanding score, the
concepts covered and missed, and the exact misconception to fix. Teachers get a class dashboard that shows
*what the class actually believes* ("60% think plants eat soil") and what to reteach.

It is built for students in Hindi-medium and regional-language schools: Hinglish by default, code-mixing is
fine, accents and mispronounced science words ("clorofil", "photo sin thesis") are never penalised.

Built for **India Runs on Voice** (Scaler × Wispr Flow), **Education** theme — built by voice, using Wispr Flow.

---

## Run it (one command, no keys)

```bash
docker compose up
```

Open **http://localhost:3000**. That's it — no `.env` file and no API keys are needed. Without a key,
Kyun-Kyun runs on its **offline brain** and the whole app works end to end.

> First run builds a small Python image (~1 minute). Use Chrome or Edge for voice.

### Try it in 3 minutes

1. **Demo (90 s, no mic, no key):** on the home screen tap **▶ Demo dekho · Watch a 90-second demo**.
   A scripted student explains photosynthesis with the classic *"plants get food from soil"* misconception;
   every line goes through the real brain, so you see the targeted question, a hint after "pata nahi",
   and the scored result.
2. **Your own voice:** pick a language chip, tap a chapter card (or the big 🎤 and say *"Photosynthesis
   samjhana hai"*), allow the microphone and explain. Stop talking for 3 s to end your turn.
3. **Teacher view:** open **http://localhost:3000/teacher.html** → **Load sample class** for a filled
   dashboard, or **Create a class** and join it from the student app with the 6-digit code.

### AI brain (optional but recommended)

```bash
cp .env.example .env      # Windows: copy .env.example .env
# set GEMINI_API_KEY=... (free key: https://aistudio.google.com/apikey)
docker compose up -d --force-recreate
```

The badge in the top-right switches to **AI brain**. If the key is wrong, the network drops or Gemini is
slow, Kyun-Kyun silently falls back to the offline brain (see below). `.env` is git-ignored.

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | Optional. Empty = offline brain only. |
| `LLM_PROVIDER` | `gemini` | Only `gemini` is supported for now. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Optional model override. |

---

## How a session works

```
 pick language ─▶ tap chapter (or say the topic) ─▶ Kyun-Kyun: "Wah! Mujhe samjhao na!"
        │
        ▼
 EXPLAIN  (up to 2 min, live transcript; 3 s of silence or "Done" ends the turn)
        │
        ▼
 3 FOLLOW-UP QUESTIONS, one at a time, each < 15 words, built from the student's own words:
   biggest misconception first → missing concepts → "why" about what they said
   e.g. "plant mitti se khana leta hai" → "Mitti se khana? Toh gamle ki mitti kam kyun nahi hoti?"
   · "pata nahi" or 8 s of silence → one small hint, never the answer · a 2nd "pata nahi" → next question
        │
        ▼
 RESULT: Kyun-Kyun speaks 3 sentences (a strength, the main misconception, encouragement);
         screen shows the 0–100 score, its breakdown, covered / missing concepts, "Phir se samjhao"
```

**Scoring** (both brains): **40% correct ideas** (100 minus 30 per misconception) + **30% reasoning** in the
follow-up answers (causal words like *kyunki / isliye / because / क्योंकि* plus real concept words, not
"pata nahi") + **30% concept coverage**. Both brains report what they found; the number is always computed
in code the same way, so scores are comparable.

**Chapters included:** Fractions (Class 6), Photosynthesis (Class 7), Gravity (Class 9) — each with 6 concepts
and 3 common misconceptions, e.g. *"1/8 is bigger than 1/4"*, *"heavier things fall faster"*,
*"there is no gravity in space"*.

## Two brains, one interface

| | Offline brain (default) | AI brain (optional but recommended) |
|---|---|---|
| Needs | nothing | `GEMINI_API_KEY` + internet |
| How | per-chapter concepts, keyword lists in Roman + Devanagari, misconception trigger phrases, pre-written questions and hints | Google Gemini writes personalised questions, hints and feedback that quote the student |
| Languages | Hinglish and English lines (other languages fall back to Hinglish) | all 7: Hinglish, English, Hindi, Punjabi, Tamil, Bengali, Marathi |
| Code | `app/brain/offline.py` + `app/chapters/*.json` | `app/brain/llm.py` |

**Graceful fallback** (`app/brain/fallback.py`): every AI call has a hard **8-second deadline**. On a timeout,
network error, rejected key, safety block, or a reply that fails validation (e.g. a question over 14 words
or aimed at an unknown concept), *the same turn* is answered by the offline brain — mid-session, with no
error shown. After a failure the AI is skipped for 60 s so a dropped connection doesn't cost 8 s per turn;
a rejected key or unknown model keeps it off until restart, and `/api/health` says why. The badge shows
which brain answered each turn. This is also our answer to "what if the AI gets costly or goes down":
the product keeps working, just less personalised.

Turn rules (noise, "pata nahi", off-topic, copied answers) live in `app/session.py` and are shared by both
brains, so behaviour stays consistent whichever brain answers.

## Built for Indian classrooms

- **Code-mixing and scripts:** Chrome's `hi-IN` recognition returns Devanagari, even for English words
  (फोटोसिंथेसिस), so every keyword and trigger exists in Roman *and* Devanagari. Transcripts are kept as spoken.
- **Accents and mispronunciation:** before scoring, transcripts are normalised against each chapter's
  vocabulary fixes ("clorofil" → chlorophyll, "ek bata aath" / "one eighth" / "1/8" → the same fraction).
  Ideas are scored, never pronunciation.
- **Negation-aware:** "plant mitti se khana *nahi* leta" is not flagged as the soil misconception;
  "bhari aur halki cheez *ek saath* girti hain" is not flagged as "heavier falls faster".
- **Kyun-Kyun's voice:** lines are shown in Roman Hinglish but *spoken* from a Devanagari version by the
  best Hindi voice on the device (Roman Hindi through a Hindi voice sounds garbled).
- **Noise:** an empty, one-character or filler-only turn ("hmm", "uh") → *"Bahut shor hai, thoda paas aakar
  bolo na?"* and the question is repeated. A turn that couldn't be heard is never scored.
- **Off-topic / joking:** redirected once ("Haha, par photosynthesis mein hota kya hai?"); a second
  off-topic answer counts as "pata nahi".
- **Copied answers:** a long, textbook-style explanation followed by a weak answer gets *"Achha bola! Ab apne
  words mein batao, kyun?"*, and reasoning is scored lower. A textbook explanation with strong answers is not
  penalised.
- **Slow 3G / dropped connection:** requests retry once; if they still fail the student's words stay in the
  box to resend with one tap. Progress is kept in the browser (session id only) and a "Continue your last
  session?" card appears after a refresh.
- **Low-end phones:** no frameworks, no build step, no images except one SVG — the whole frontend is a few
  small HTML/CSS/JS files.

## Teacher dashboard

`/teacher.html` → create a class → a **6-digit join code** for students and a **private teacher link**.
Students tap **🏫 Join a class** once and enter the code and their first name (optional — solo use needs
nothing). The dashboard shows:

- students, sessions and class average; average per chapter
- **ranked misconceptions** across the class, e.g. *"60% think: Plants get food from soil (6/10)"*
- **What to reteach**: the two concepts missed by the largest share of students
- a student × chapter table of each student's **latest** score; tap a score for the full transcript,
  Kyun-Kyun's questions, the answers, misconceptions and the feedback the student heard
- **Load sample class**: fictional students whose sessions are scored by the real offline brain, clearly
  labelled as sample data

**Access:** the join code alone opens nothing (students know it). The dashboard needs the teacher key from
the teacher link, sent as `X-Teacher-Key`; only its SHA-256 hash is stored.

## Privacy (users are minors)

- **No audio is ever recorded or stored** — the Web Speech API doesn't even expose it. Only transcripts (text)
  and scores are saved, in a local SQLite file inside the container.
- No ads, no messaging, no public profiles. A class needs only a first name.
- With the AI brain on, transcripts (text only) are sent to Google Gemini — the app says so on screen.
  Without a key, nothing leaves the server. (Chrome's own speech recognition sends audio to Google to turn it
  into text; that is the browser, not Jigyasa, and we say so in the app.)

## Browser requirements

| | Voice in (speech recognition) | Voice out (Kyun-Kyun speaks) |
|---|---|---|
| **Chrome / Edge** (desktop, Android) | ✅ needs internet (recognition runs on Google/Microsoft servers) | ✅ |
| Safari | ⚠ partial | ✅ |
| Firefox | ❌ → app shows "Voice works best in Chrome or Edge" and a text box | ✅ |

- The microphone only works on `https://` or `localhost`. A hosted copy must use HTTPS.
- Voices depend on the device. Chrome usually offers "Google हिन्दी"; on Windows you can also add a Hindi
  voice in *Settings → Time & language → Speech*. The 🔊 **Test voice** button shows which voice
  is used. If no suitable voice exists, text is always on screen.
- **Voice first, inclusive by design:** Jigyasa is built to be spoken to. A clearly labelled
  **"Can't speak? Type instead"** option is there for students with a speech disability, and it opens
  automatically when a browser or device can't use the microphone.

## Known limits (honest list)

What the browser's Web Speech API **cannot** do in this prototype — we don't fake these:

- **No real noise suppression** — we only detect empty / filler-only turns and ask the student to come closer.
- **No second-speaker detection** — we can't tell if someone else is answering.
- **No reliable confidence scores** — Chrome often returns 0, so we ignore them.
- **Speech recognition needs internet** in Chrome; offline, students type (the offline brain still works).

Other limits:

- The offline brain is keyword-based: it can be fooled by someone who says the right words without meaning,
  and it writes only Hinglish/English lines. The AI brain handles nuance and all 7 languages.
- Three chapters are included; adding one means writing one JSON file (`app/chapters/`).
- Regional-language voices depend on what the device has installed.
- SQLite in one container is fine for a classroom, not for a whole state.

## Roadmap

- **On-device speech recognition** (e.g. a small Whisper / IndicWhisper model) for true offline use,
  noise robustness and confidence scores.
- **More chapters**: a content tool for teachers to add NCERT chapters, and offline lines in more languages.
- **PWA / low-data mode** for patchy connections; a feature-phone channel (IVR / missed-call) for students
  without smartphones.
- Teacher accounts, multiple classes per teacher, and progress over time per student.
- Speaker-aware sessions for group explanations in class.

---

## For developers

### Project layout

```
docker-compose.yml  Dockerfile  .env.example  requirements.txt  requirements-dev.txt
app/
  main.py            FastAPI app: JSON API + static files
  session.py         turn rules shared by both brains (hints, noise, off-topic, copied answers)
  content.py         loads chapters + shared lines, language helpers, topic matching
  classes.py         classes, teacher key, dashboard aggregation, sample class
  db.py              SQLite (sessions, classes)
  demo_data.py       fictional students for the sample class
  brain/
    base.py          Brain interface + shared scoring weights
    offline.py       rule-based brain
    llm.py           Gemini brain (REST, JSON replies validated in code)
    fallback.py      8 s deadline, cooldown, automatic offline fallback
    text.py          normalisation + Roman/Devanagari phrase matching
    common.json      "pata nahi" triggers, causal words, fillers, shared lines
  chapters/          fractions.json  photosynthesis.json  gravity.json
static/
  index.html  teacher.html  css/style.css  favicon.svg
  js/voice.js        speech recognition (timers, auto-restart) + speech synthesis (voice choice)
  js/app.js          student flow, error handling, resume, class join
  js/demo.js         scripted Demo-mode student
  js/teacher.js      teacher dashboard
tests/               66 API and content tests (Gemini is faked; no key or network needed)
```

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{status, brain: "llm"\|"offline", llm_configured, llm_error}` |
| GET | `/api/chapters` | chapters and languages |
| POST | `/api/match` | `{transcript}` → `{chapter_id}` (spoken topic → chapter) |
| POST | `/api/session/start` | `{chapter_id, language, class_code?, student_name?, demo?}` → opening line |
| POST | `/api/session/{id}/explain` | `{transcript, reason}` → first question, nudge, redirect or noise |
| POST | `/api/session/{id}/answer` | `{transcript, reason}` → next question, hint, redirect, noise or done |
| POST | `/api/session/{id}/finish` | scoring JSON |
| GET | `/api/session/{id}` | session state (used to resume) |
| POST | `/api/class` | `{name}` → `{code, teacher_key}` |
| POST | `/api/class/demo` | sample class → `{code, teacher_key}` |
| GET | `/api/class/{code}` | public: class name for a join code |
| GET | `/api/class/{code}/dashboard` | needs `X-Teacher-Key` |
| GET | `/api/class/{code}/session/{id}` | one transcript; needs `X-Teacher-Key` |

Every reply carries `say` (shown on screen) and `speak` (for text-to-speech; Devanagari for Hinglish).
The scoring JSON:

```json
{
  "score": 0,
  "concepts_covered": [], "concepts_missing": [],
  "misconceptions": [{"id": "", "student_said": "", "correct_idea": ""}],
  "reasoning_quality": "low|medium|high",
  "strengths": [],
  "feedback_in_student_language": "",
  "feedback_speech": "",
  "breakdown": {"correctness": 0, "reasoning": 0, "coverage": 0}
}
```

### Tests

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

### Adding a chapter

Copy `app/chapters/photosynthesis.json` and edit it: `topic_keywords`, `concepts` (keywords in Roman *and*
Devanagari, a question if missing, a probe, a hint), `misconceptions` (trigger phrases — `*` allows a gap of
up to 3 words — question, hint, correct idea, optional `exceptions`), and `vocab_fixes`. Every line has
`hi` (Roman Hinglish, shown), `en` and `dev` (Devanagari, spoken). `tests/test_chapters.py` checks the
structure, the 15-word rule and that keywords exist in both scripts.
