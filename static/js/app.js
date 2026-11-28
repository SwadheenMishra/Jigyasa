/* Jigyasa student flow: home -> explain -> 3 questions -> results.
 * Voice first (voice.js), with a text box always available as a fallback.
 * All reasoning happens on the server (/api/session/...), so both brains
 * behave the same from the browser's point of view.
 *
 * Things that go wrong, and what we do (CLAUDE.md §4 "When things go wrong"):
 *  - no SpeechRecognition (Firefox) / no TTS -> notice + text box, text on screen
 *  - mic blocked / recognition network error -> notice, text box, "retry voice" button
 *  - page not on https/localhost            -> notice (browsers block the mic there)
 *  - device offline                         -> banner; typed answers still work on the offline brain
 *  - server request fails or is slow        -> retry once, then keep the student's words and ask to resend
 *  - page closed / refreshed mid-session    -> progress kept in localStorage, "continue?" card on return
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
  const MAX_TRANSCRIPT = 5000; // server accepts 6000
  const RESUME_MAX_AGE_MS = 6 * 60 * 60 * 1000;
  const PROGRESS_KEY = "jigyasa.session";
  const CLASS_KEY = "jigyasa.class"; // {code, className, student}: joined once, reused for every session

  // hi = Roman Hinglish (shown), dev = same line in Devanagari (spoken by a Hindi voice).
  const UI = {
    askTopic: { hi: "Bolo, kya samjhana hai?", en: "Tell me, what will you explain?", dev: "बोलो, क्या समझाना है?" },
    noTopic: { hi: "Yeh chapter abhi mujhe nahi aata. Neeche se chuno na!", en: "I don't know that chapter yet. Pick one below!",
               dev: "ये चैप्टर अभी मुझे नहीं आता. नीचे से चुनो ना!" },
    pickBelow: { hi: "Neeche se chapter chuno!", en: "Pick a chapter below!", dev: "नीचे से चैप्टर चुनो!" },
    thinking: { hi: "Hmm… soch raha hoon…", en: "Hmm… thinking…", dev: "हम्म, सोच रहा हूँ." },
    oops: { hi: "Oops, kuch gadbad ho gayi. Phir se try karo?", en: "Oops, something went wrong. Try again?",
            dev: "उफ़, कुछ गड़बड़ हो गई. फिर से ट्राई करो?" },
    netFail: { hi: "Internet slow hai, baat pahunchi nahi. Phir se bolo, ya Bhejo dabao.",
               en: "The internet is slow, that didn't reach me. Say it again, or press Send.",
               dev: "इंटरनेट स्लो है, बात पहुँची नहीं. फिर से बोलो, या भेजो दबाओ." },
    resumeExplain: { hi: "Chalo, wahin se shuru karte hain. Samjhao na!", en: "Let's pick up where we left off. Explain to me!",
                     dev: "चलो, वहीं से शुरू करते हैं. समझाओ ना!" },
    demoDone: { hi: "Demo khatam! Ab tumhari baari — koi bhi chapter chuno.", en: "Demo done! Your turn now — pick any chapter.",
                dev: "डेमो खत्म! अब तुम्हारी बारी, कोई भी चैप्टर चुनो." },
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
    demo: null, // scripted student (demo.js) while Demo mode runs
    lastTarget: null, // target id of the current question (Demo mode picks a fitting answer)
    voiceOk: V.canListen,
    busy: false,
    timer: null,
  };

  // ---------- small helpers ----------

  function loadPref(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function savePref(key, v) { try { localStorage.setItem(key, v); } catch (_) { /* private mode */ } }
  function dropPref(key) { try { localStorage.removeItem(key); } catch (_) { /* private mode */ } }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const lineKey = () => (state.language === "en" ? "en" : "hi");
  const ui = (name) => UI[name][lineKey()];
  /** A UI line as {text, speak} for kkSay. */
  const uiLine = (name) => ({ text: ui(name), speak: state.language === "en" ? ui(name) : UI[name].dev });
  const recLang = () => (state.languages.find((l) => l.id === state.language) || { rec: "hi-IN" }).rec;
  const chapterById = (id) => state.chapters.find((c) => c.id === id);

  /**
   * JSON API call. A network failure or timeout is retried once (slow 3G);
   * an HTTP error is not, and carries err.status.
   */
  async function api(path, body, { retries = 1, timeoutMs = 20000 } = {}) {
    const opts = body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    };
    for (let attempt = 0; ; attempt++) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const r = await fetch(path, { ...opts, signal: ctrl.signal });
        if (!r.ok) {
          const err = new Error(`${path} -> ${r.status}`);
          err.status = r.status;
          throw err;
        }
        return await r.json();
      } catch (err) {
        if (err.status || attempt >= retries) throw err;
        await sleep(1500);
      } finally {
        clearTimeout(timer);
      }
    }
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
    $("kk").classList.add("talking");
    try { await V.speakLine(line, state.language); } finally { $("kk").classList.remove("talking"); }
  }

  /** Progress dots: 0 = explain, 1-3 = questions, 4 = results. */
  function setProgress(step) {
    document.querySelectorAll("#progress-dots li").forEach((li, i) => {
      li.classList.toggle("done", i < step);
      li.classList.toggle("now", i === step);
    });
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

  // ---------- progress (localStorage): only ids, never transcripts ----------

  function saveProgress() {
    if (!state.sessionId) return;
    savePref(PROGRESS_KEY, JSON.stringify({
      id: state.sessionId, chapterId: state.chapterId, language: state.language, at: Date.now(),
    }));
  }
  function clearProgress() { dropPref(PROGRESS_KEY); }
  function loadProgress() {
    try {
      const p = JSON.parse(loadPref(PROGRESS_KEY) || "null");
      return p && p.id && Date.now() - p.at < RESUME_MAX_AGE_MS ? p : null;
    } catch (_) { return null; }
  }

  // ---------- joining a teacher's class (optional) ----------

  function joinedClass() {
    try { return JSON.parse(loadPref(CLASS_KEY) || "null"); } catch (_) { return null; }
  }

  function renderJoin() {
    const c = joinedClass();
    $("joined").hidden = !c;
    $("btn-join").hidden = !!c;
    if (c) {
      $("joined-class").textContent = c.className;
      $("joined-name").textContent = c.student;
      $("join-panel").hidden = true;
    }
  }

  async function joinClass(e) {
    e.preventDefault();
    const code = $("join-code").value.trim();
    const student = $("join-name").value.trim().replace(/\s+/g, " ").slice(0, 40);
    const fail = (msg) => { $("join-error").textContent = msg; $("join-error").hidden = false; };
    $("join-error").hidden = true;
    if (!/^\d{6}$/.test(code)) return fail("Code 6 digits ka hota hai · The code has 6 digits.");
    if (!student) return fail("Apna naam likho · Please type your first name.");
    try {
      const c = await api(`/api/class/${code}`, undefined, { retries: 1, timeoutMs: 10000 });
      savePref(CLASS_KEY, JSON.stringify({ code, className: c.name, student }));
      renderJoin();
    } catch (err) {
      fail(err.status === 404 ? "Yeh code nahi mila · No class with this code." : "Internet slow hai, phir se try karo · Try again.");
    }
  }

  // ---------- voice problems ----------

  function handleVoiceError(err) {
    state.voiceOk = false;
    micState(false);
    const msg = VOICE_ERRORS[err && err.code] || "Voice stopped working. Please type below. · नीचे लिखो।";
    $("voice-error-text").textContent = msg;
    $("voice-error").hidden = false;
    $("text-input").focus();
  }

  /** "Retry voice": e.g. after allowing the mic or getting internet back. */
  function retryVoice() {
    if (!V.canListen) return;
    state.voiceOk = true;
    $("voice-error").hidden = true;
    if (state.turn && !state.turn.voice) state.turn.startVoice();
  }

  // ---------- one turn of input: voice or typed, whichever comes first ----------

  /** Demo mode: type the scripted student's line onto the screen while a second voice says it. */
  async function demoTurn(kind) {
    const line = state.demo.next(kind === "explain" ? "explain" : "answer", state.lastTarget);
    setMood("listening");
    micState(true);
    const box = $("transcript");
    box.textContent = "";
    box.classList.add("typing");
    const typing = (async () => {
      for (const word of line.text.split(" ")) {
        if (!state.demo) return;
        box.textContent = `${box.textContent} ${word}`.trim();
        await sleep(110);
      }
    })();
    await Promise.all([typing, V.speakLine({ text: line.text, speak: line.dev }, "hinglish", { student: true })]);
    box.classList.remove("typing");
    micState(false);
    await sleep(400);
    return { transcript: line.text, reason: "typed" };
  }

  function getTurn(kind) {
    if (state.demo) return demoTurn(kind);
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
          if (turn.voice) turn.voice.cancel();
          resolve({ ...value, transcript: (value.transcript || "").slice(0, MAX_TRANSCRIPT) });
        },
        startVoice() {
          if (!state.voiceOk || settled) return;
          micState(true);
          turn.voice = V.listen({
            lang: recLang(),
            ...LIMITS[kind],
            onText: (t) => { $("transcript").textContent = t; },
          });
          turn.voice.promise.then(turn.settle).catch((err) => {
            turn.voice = null;
            handleVoiceError(err); // keep waiting: the student can type, or retry voice
          });
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
      turn.startVoice(); // no-op without voice: wait for the text box
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
      turn.settle(value);
    } else {
      state.pendingTyped = value;
      V.stopSpeaking();
    }
  }

  // ---------- the conversation ----------

  function showTalk(chapter) {
    show("talk");
    $("step-label").textContent = chapter ? `${chapter.emoji} ${chapter.title} · Samjhao! · Explain` : "Samjhao! · Explain";
    $("question-card").hidden = true;
    $("transcript").textContent = "";
    setProgress(0);
  }

  function showQuestion(question, number, total = 3) {
    setProgress(number);
    $("step-label").textContent = `Sawaal ${number}/${total} · Question`;
    $("question-card").textContent = question;
    $("question-card").hidden = false;
  }

  async function startChapter(chapterId, { demo = false } = {}) {
    if (state.busy) return;
    state.busy = true;
    state.pendingTyped = null;
    V.stopSpeaking();
    $("resume-card").hidden = true;
    try {
      const cls = demo ? null : joinedClass();
      let r;
      try {
        r = await api("/api/session/start", {
          chapter_id: chapterId, language: state.language, demo,
          class_code: cls ? cls.code : null, student_name: cls ? cls.student : null,
        });
      } catch (err) {
        if (err.status !== 404 || !cls) throw err;
        dropPref(CLASS_KEY); // the class no longer exists: continue solo
        renderJoin();
        r = await api("/api/session/start", { chapter_id: chapterId, language: state.language });
      }
      state.sessionId = r.session_id;
      state.chapterId = chapterId;
      if (!demo) saveProgress();
      setBadge(r.brain);
      showTalk(r.chapter);
      await kkSay({ text: r.say, speak: r.speak }, r.mood);
      await conversation("explain");
    } catch (err) {
      console.error(err);
      await kkSay(uiLine("oops"), "confused");
      stopDemo();
    } finally {
      state.busy = false;
    }
  }

  // ---------- Demo mode ----------

  async function startDemo() {
    if (state.busy || !window.JDemo) return;
    V.stopSpeaking();
    state.demo = window.JDemo.createDemo();
    state.language = state.demo.language; // the script is Hinglish
    renderLanguages();
    $("demo-banner").hidden = false;
    $("demo-banner-text").textContent = "▶ DEMO · A scripted student explains; Kyun-Kyun's real brain answers live.";
    await startChapter(state.demo.chapter, { demo: true });
  }

  function stopDemo() {
    if (!state.demo) return;
    state.demo = null;
    $("demo-banner").hidden = true;
  }

  async function conversation(stage) {
    while (stage === "explain" || stage === "questions") {
      const turn = await getTurn(stage === "explain" ? "explain" : "answer");
      setMood("curious");
      bubble(ui("thinking"));
      const endpoint = stage === "explain" ? "explain" : "answer";
      let reply;
      try {
        reply = await api(`/api/session/${state.sessionId}/${endpoint}`, turn);
      } catch (err) {
        if (err.status === 409) { // the server already moved on (e.g. a retried request got through): sync up
          stage = await syncFromServer();
          continue;
        }
        console.error(err);
        $("text-input").value = turn.transcript; // keep their words: one tap on "Bhejo" resends
        await kkSay(uiLine("netFail"), "confused");
        continue;
      }
      setBadge(reply.brain);
      state.lastTarget = reply.target_id;
      if (!state.demo) saveProgress();
      if (reply.question) showQuestion(reply.question, reply.q_number, reply.q_total);
      await kkSay({ text: reply.say, speak: reply.speak }, reply.mood);
      stage = reply.action === "done" ? "review" : reply.stage;
    }
    await showResults();
  }

  /** Re-read the session from the server and show its current question. Returns its stage. */
  async function syncFromServer() {
    const s = await api(`/api/session/${state.sessionId}`);
    if (s.stage === "questions" && s.current) {
      showQuestion(s.current.text, s.answers.length + 1);
      await kkSay({ text: s.current.text, speak: s.current.speak || s.current.text }, s.current.mood || "curious");
    }
    return s.stage;
  }

  async function showResults() {
    const r = await api(`/api/session/${state.sessionId}/finish`, {});
    clearProgress();
    setBadge(r.brain);
    show("results");
    countUp(r.score);
    $("celebrate").hidden = r.score < 75;
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
    if (state.demo) {
      stopDemo();
      $("demo-banner").hidden = false;
      $("demo-banner-text").textContent = "✅ Demo complete. The questions, hint and score above came from the real brain.";
      await kkSay(uiLine("demoDone"), "happy");
    }
  }

  /** Animate the score ring from 0 to the score. */
  function countUp(score) {
    const target = Math.max(0, Math.min(100, Number(score) || 0));
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / 1200);
      const v = Math.round(target * (1 - Math.pow(1 - k, 3)));
      $("score").textContent = v;
      $("score-ring").style.setProperty("--pct", v);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function fillList(ul, items) {
    ul.textContent = "";
    for (const text of items.length ? items : ["—"]) {
      const li = document.createElement("li");
      li.textContent = text;
      ul.append(li);
    }
  }

  // ---------- resume after a refresh or dropped connection ----------

  async function offerResume() {
    const p = loadProgress();
    if (!p) return;
    let s;
    try {
      s = await api(`/api/session/${p.id}`, undefined, { retries: 0, timeoutMs: 8000 });
    } catch (_) {
      clearProgress(); // gone (or server unreachable): don't nag
      return;
    }
    if (!["explain", "questions", "review"].includes(s.stage)) { clearProgress(); return; }
    const ch = chapterById(s.chapter_id);
    const where = s.stage === "explain" ? "Samjhana · Explaining"
      : s.stage === "questions" ? `Sawaal ${s.answers.length + 1}/3 · Question ${s.answers.length + 1}/3`
        : "Result · Results";
    $("resume-text").textContent = `${ch ? `${ch.emoji} ${ch.title}` : s.chapter_id} — ${where}`;
    $("resume-card").hidden = false;
    $("btn-resume").onclick = () => resume(s);
    $("btn-resume-new").onclick = () => { clearProgress(); $("resume-card").hidden = true; };
  }

  async function resume(s) {
    if (state.busy) return;
    state.busy = true;
    $("resume-card").hidden = true;
    state.sessionId = s.id;
    state.chapterId = s.chapter_id;
    if (state.languages.some((l) => l.id === s.language)) {
      state.language = s.language;
      renderLanguages();
    }
    try {
      showTalk(chapterById(s.chapter_id));
      if (s.stage === "explain") {
        await kkSay(uiLine("resumeExplain"), "curious");
        await conversation("explain");
      } else if (s.stage === "questions") {
        await conversation(await syncFromServer());
      } else {
        await showResults();
      }
    } catch (err) {
      console.error(err);
      await kkSay(uiLine("oops"), "confused");
    } finally {
      state.busy = false;
    }
  }

  // ---------- topic by voice ----------

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

  /** Browser / connection checks that don't depend on the server. */
  function environmentNotices() {
    const warn = [];
    if (!V.canListen) {
      warn.push("Voice works best in Chrome or Edge. · आवाज़ के लिए Chrome या Edge खोलें। Neeche likh kar bhi bata sakte ho.");
    } else if (!window.isSecureContext) {
      warn.push("The microphone only works on https:// or localhost. Please type below. · माइक के लिए https चाहिए — नीचे लिखो।");
      state.voiceOk = false;
    }
    if (!V.canSpeak) warn.push("This browser can't speak, so read Kyun-Kyun's words on screen. · स्क्रीन पर पढ़ो।");
    $("voice-warning").textContent = warn.join(" ");
    $("voice-warning").hidden = !warn.length;

    const net = () => { $("net-warning").hidden = navigator.onLine; };
    window.addEventListener("online", net);
    window.addEventListener("offline", net);
    net();
  }

  async function init() {
    environmentNotices();
    $("btn-topic").addEventListener("click", topicByVoice);
    $("btn-done").addEventListener("click", onDone);
    $("text-form").addEventListener("submit", onTyped);
    $("btn-voice-retry").addEventListener("click", retryVoice);
    $("btn-demo").addEventListener("click", startDemo);
    $("btn-demo-stop").addEventListener("click", () => location.reload());
    $("btn-join").addEventListener("click", () => { $("join-panel").hidden = !$("join-panel").hidden; $("join-code").focus(); });
    $("btn-leave").addEventListener("click", () => { dropPref(CLASS_KEY); renderJoin(); $("join-panel").hidden = false; });
    $("join-panel").addEventListener("submit", joinClass);
    renderJoin();
    $("btn-again").addEventListener("click", () => { $("demo-banner").hidden = true; startChapter(state.chapterId); });
    $("btn-voice-test").addEventListener("click", async () => {
      if (state.busy) return;
      await V.voicesReady();
      $("voice-name").textContent = V.canSpeak ? `Voice: ${V.voiceName(state.language)}` : "No speech voice in this browser";
      await kkSay(uiLine("voiceTest"), "happy");
      setMood("curious");
    });
    $("btn-home").addEventListener("click", () => {
      V.stopSpeaking();
      $("demo-banner").hidden = true;
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
      await offerResume();
    } catch (err) {
      console.error(err);
      bubble(ui("oops"));
    }
  }

  init();
})();
