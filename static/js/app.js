/* Jigyasa student flow: home -> explain -> 3 questions -> results.
 * Voice first (voice.js), with a text box always available as a fallback.
 * All reasoning happens on the server (/api/session/...), so both brains
 * behave the same from the browser's point of view.
 */
(function () {
  "use strict";

  const V = window.JVoice;
  const $ = (id) => document.getElementById(id);

  const LIMITS = {
    topic: { silenceMs: 2000, noSpeechMs: 8000, maxMs: 10000 },
    explain: { silenceMs: 3000, noSpeechMs: 10000, maxMs: 120000 },
    answer: { silenceMs: 3000, noSpeechMs: 8000, maxMs: 45000 },
  };

  // hi = Roman Hinglish (shown), dev = same line in Devanagari (spoken by a Hindi voice).
  const UI = {
    askTopic: { hi: "Bolo, kya samjhana hai?", en: "Tell me, what will you explain?", dev: "बोलो, क्या समझाना है?" },
    noTopic: { hi: "Yeh chapter abhi mujhe nahi aata. Neeche se chuno na!", en: "I don't know that chapter yet. Pick one below!",
               dev: "ये चैप्टर अभी मुझे नहीं आता. नीचे से चुनो ना!" },
    pickBelow: { hi: "Neeche se chapter chuno!", en: "Pick a chapter below!", dev: "नीचे से चैप्टर चुनो!" },
    thinking: { hi: "Hmm… soch raha hoon…", en: "Hmm… thinking…", dev: "हम्म, सोच रहा हूँ." },
    oops: { hi: "Oops, kuch gadbad ho gayi. Phir se try karo?", en: "Oops, something went wrong. Try again?",
            dev: "उफ़, कुछ गड़बड़ हो गई. फिर से ट्राई करो?" },
    voiceTest: { hi: "Namaste! Main Kyun-Kyun hoon. Kya meri awaaz saaf sunai de rahi hai?",
                 en: "Hello! I am Kyun-Kyun. Can you hear me clearly?",
                 dev: "नमस्ते! मैं क्यूं-क्यूं हूँ. क्या मेरी आवाज़ साफ़ सुनाई दे रही है?" },
  };

  const VOICE_ERRORS = {
    network: "Voice recognition needs internet in Chrome. Please type below. · आवाज़ पहचानने के लिए इंटरनेट चाहिए — नीचे लिखो।",
    "not-allowed": "Microphone is blocked. Allow it in the address bar, or type below. · माइक की अनुमति नहीं मिली — नीचे लिखो।",
    "service-not-allowed": "Microphone is blocked. Allow it in the address bar, or type below. · माइक की अनुमति नहीं मिली — नीचे लिखो।",
    "audio-capture": "No microphone found. Please type below. · माइक नहीं मिला — नीचे लिखो।",
    "language-not-supported": "Voice isn't available for this language here. Please type below. · इस भाषा में आवाज़ उपलब्ध नहीं — नीचे लिखो।",
  };

  const state = {
    language: loadPref("jigyasa.language") || "hinglish",
    languages: [],
    chapters: [],
    sessionId: null,
    chapterId: null,
    turn: null,
    pendingTyped: null,
    voiceOk: V.canListen,
    busy: false,
    timer: null,
  };

  // ---------- small helpers ----------

  function loadPref(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function savePref(key, v) { try { localStorage.setItem(key, v); } catch (_) { /* private mode */ } }
  const lineKey = () => (state.language === "en" ? "en" : "hi");
  const ui = (name) => UI[name][lineKey()];
  /** A UI line as {text, speak} for kkSay. */
  const uiLine = (name) => ({ text: ui(name), speak: state.language === "en" ? ui(name) : UI[name].dev });
  const recLang = () => (state.languages.find((l) => l.id === state.language) || { rec: "hi-IN" }).rec;

  async function api(path, body) {
    const opts = body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    };
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`${path} -> ${r.status}`);
    return r.json();
  }

  function show(screen) {
    for (const s of ["home", "talk", "results"]) $(`screen-${s}`).hidden = s !== screen;
    window.scrollTo(0, 0);
  }

  function setMood(mood) { $("kk").dataset.mood = mood; }
  function bubble(text) { $("bubble").textContent = text; }
  function micState(on) { $("mic-state").classList.toggle("on", on); }

  /** Show and speak a line. `line` is {text, speak}; speak is Devanagari for Hinglish. */
  async function kkSay(line, mood = "curious") {
    setMood(mood);
    bubble(line.text);
    micState(false);
    await V.speakLine(line, state.language);
  }

  function startTimer(ms) {
    stopTimer();
    const end = Date.now() + ms;
    const tick = () => {
      const left = Math.max(0, Math.round((end - Date.now()) / 1000));
      $("timer").textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    };
    tick();
    state.timer = setInterval(tick, 500);
  }
  function stopTimer() { clearInterval(state.timer); $("timer").textContent = ""; }

  function handleVoiceError(err) {
    state.voiceOk = false;
    micState(false);
    const msg = VOICE_ERRORS[err && err.code] || "Voice stopped working. Please type below. · नीचे लिखो।";
    $("voice-error").textContent = msg;
    $("voice-error").hidden = false;
    $("text-input").focus();
  }

  // ---------- one turn of input: voice or typed, whichever comes first ----------

  function getTurn(kind) {
    return new Promise((resolve) => {
      let settled = false;
      const turn = {
        voice: null,
        settle(value) {
          if (settled) return;
          settled = true;
          state.turn = null;
          stopTimer();
          micState(false);
          resolve(value);
        },
      };
      if (state.pendingTyped) { // typed while Kyun-Kyun was speaking
        const value = state.pendingTyped;
        state.pendingTyped = null;
        resolve(value);
        return;
      }
      state.turn = turn;
      $("transcript").textContent = "";
      setMood("listening");
      startTimer(LIMITS[kind].maxMs);

      if (!state.voiceOk) return; // wait for the text box
      micState(true);
      turn.voice = V.listen({
        lang: recLang(),
        ...LIMITS[kind],
        onText: (t) => { $("transcript").textContent = t; },
      });
      turn.voice.promise.then(turn.settle).catch((err) => {
        turn.voice = null;
        handleVoiceError(err); // keep waiting: the student can type instead
      });
    });
  }

  function onDone() {
    const turn = state.turn;
    if (turn && turn.voice) { turn.voice.finish("done"); return; }
    submitTyped();
  }

  function onTyped(e) {
    e.preventDefault();
    submitTyped();
  }

  /** Typed input. If Kyun-Kyun is still talking, stop and keep the text for the next turn. */
  function submitTyped() {
    const typed = $("text-input").value.trim();
    if (!typed || $("screen-talk").hidden) return;
    $("text-input").value = "";
    $("transcript").textContent = typed;
    const value = { transcript: typed, reason: "typed" };
    const turn = state.turn;
    if (turn) {
      if (turn.voice) turn.voice.cancel();
      turn.settle(value);
    } else {
      state.pendingTyped = value;
      V.stopSpeaking();
    }
  }

  // ---------- the conversation ----------

  async function startChapter(chapterId) {
    if (state.busy) return;
    state.busy = true;
    state.pendingTyped = null;
    V.stopSpeaking();
    try {
      const r = await api("/api/session/start", { chapter_id: chapterId, language: state.language });
      state.sessionId = r.session_id;
      state.chapterId = chapterId;
      setBadge(r.brain);
      show("talk");
      $("step-label").textContent = `${r.chapter.emoji} ${r.chapter.title} · Samjhao! · Explain`;
      $("question-card").hidden = true;
      $("transcript").textContent = "";
      await kkSay({ text: r.say, speak: r.speak }, r.mood);
      await conversation();
    } catch (err) {
      console.error(err);
      await kkSay(uiLine("oops"), "confused");
    } finally {
      state.busy = false;
    }
  }

  async function conversation() {
    let stage = "explain";
    for (;;) {
      const turn = await getTurn(stage === "explain" ? "explain" : "answer");
      setMood("curious");
      bubble(ui("thinking"));
      const endpoint = stage === "explain" ? "explain" : "answer";
      const reply = await api(`/api/session/${state.sessionId}/${endpoint}`, turn);
      setBadge(reply.brain);

      if (reply.question) {
        $("step-label").textContent = `Sawaal ${reply.q_number}/${reply.q_total} · Question`;
        $("question-card").textContent = reply.question;
        $("question-card").hidden = false;
      }
      await kkSay({ text: reply.say, speak: reply.speak }, reply.mood);
      if (reply.action === "done") break;
      stage = reply.stage === "questions" ? "questions" : "explain";
    }
    await showResults();
  }

  async function showResults() {
    const r = await api(`/api/session/${state.sessionId}/finish`, {});
    setBadge(r.brain);
    show("results");
    $("score").textContent = r.score;
    $("score-ring").style.setProperty("--pct", r.score);
    $("feedback").textContent = r.feedback_in_student_language;
    const parts = r.breakdown || {};
    $("breakdown").hidden = !r.breakdown;
    for (const bar of $("breakdown").querySelectorAll(".bar")) {
      const v = Math.max(0, Math.min(100, Number(parts[bar.dataset.key]) || 0));
      bar.querySelector("i").style.width = `${v}%`;
      bar.querySelector("b").textContent = v;
    }
    fillList($("covered"), r.concepts_covered);
    fillList($("missing"), r.concepts_missing);

    const box = $("misconceptions");
    box.textContent = "";
    for (const m of r.misconceptions) {
      const card = document.createElement("div");
      card.className = "miscon";
      const said = document.createElement("p");
      said.textContent = `🤔 Tumne kaha · You said: “${m.student_said}”`;
      const idea = document.createElement("p");
      idea.textContent = `💡 ${m.correct_idea}`;
      card.append(said, idea);
      box.append(card);
    }
    await kkSay({ text: r.feedback_in_student_language, speak: r.feedback_speech }, "happy");
  }

  function fillList(ul, items) {
    ul.textContent = "";
    for (const text of items.length ? items : ["—"]) {
      const li = document.createElement("li");
      li.textContent = text;
      ul.append(li);
    }
  }

  async function topicByVoice() {
    if (state.busy) return;
    if (!state.voiceOk) { await kkSay(uiLine("pickBelow"), "curious"); return; }
    state.busy = true;
    const btn = $("btn-topic");
    let chapterId = null;
    try {
      await kkSay(uiLine("askTopic"), "curious");
      setMood("listening");
      btn.classList.add("live");
      const { transcript } = await V.listen({ lang: recLang(), ...LIMITS.topic, onText: bubble }).promise;
      if (transcript) chapterId = (await api("/api/match", { transcript })).chapter_id;
      if (!chapterId) await kkSay(uiLine("noTopic"), "confused");
    } catch (err) {
      if (err instanceof V.VoiceError) handleVoiceError(err);
      else console.error(err);
    } finally {
      btn.classList.remove("live");
      state.busy = false;
    }
    if (chapterId) await startChapter(chapterId);
  }

  // ---------- home screen ----------

  function renderLanguages() {
    const box = $("lang-chips");
    box.textContent = "";
    for (const l of state.languages) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = l.label;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(l.id === state.language));
      b.addEventListener("click", () => {
        state.language = l.id;
        savePref("jigyasa.language", l.id);
        renderLanguages();
      });
      box.append(b);
    }
  }

  function renderChapters() {
    const box = $("chapter-cards");
    box.textContent = "";
    for (const c of state.chapters) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "card";
      const emoji = document.createElement("span");
      emoji.className = "emoji";
      emoji.textContent = c.emoji;
      const title = document.createElement("strong");
      title.textContent = c.title;
      const hi = document.createElement("span");
      hi.textContent = c.title_hi;
      const meta = document.createElement("small");
      meta.textContent = `Class ${c.class} · ${c.subject}`;
      b.append(emoji, title, hi, meta);
      b.addEventListener("click", () => startChapter(c.id));
      box.append(b);
    }
  }

  function setBadge(brain, why) {
    if (!brain) return;
    const b = $("brain-badge");
    b.textContent = brain === "llm" ? "AI brain" : "Offline brain";
    b.className = `badge ${brain}`;
    b.title = brain === "llm"
      ? "AI brain (Google Gemini). Falls back to the offline brain automatically."
      : `Offline brain: rule-based, works without internet or API keys.${why ? ` (AI brain off: ${why})` : ""}`;
    // Be honest about where text goes: with the AI brain, transcripts go to Google.
    $("privacy-ai").hidden = brain !== "llm";
  }

  async function init() {
    if (!V.canListen) $("voice-warning").hidden = false;
    $("btn-topic").addEventListener("click", topicByVoice);
    $("btn-done").addEventListener("click", onDone);
    $("text-form").addEventListener("submit", onTyped);
    $("btn-again").addEventListener("click", () => startChapter(state.chapterId));
    $("btn-voice-test").addEventListener("click", async () => {
      if (state.busy) return;
      await V.voicesReady();
      $("voice-name").textContent = V.canSpeak ? `Voice: ${V.voiceName(state.language)}` : "No speech voice in this browser";
      await kkSay(uiLine("voiceTest"), "happy");
      setMood("curious");
    });
    $("btn-home").addEventListener("click", () => {
      V.stopSpeaking();
      show("home");
      setMood("curious");
      bubble("Ab kya sikhaoge? · What will you teach me next?");
    });

    try {
      const [health, data] = await Promise.all([api("/api/health"), api("/api/chapters")]);
      setBadge(health.brain, health.llm_error);
      state.languages = data.languages;
      state.chapters = data.chapters;
      if (!state.languages.some((l) => l.id === state.language)) state.language = data.default_language;
      renderLanguages();
      renderChapters();
    } catch (err) {
      console.error(err);
      bubble(ui("oops"));
    }
  }

  init();
})();
