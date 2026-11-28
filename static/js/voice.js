/* Jigyasa voice layer: browser Web Speech API only (free, no key).
 *
 * Honest limits of the Web Speech API in this prototype:
 *  - Chrome sends audio to Google's servers for recognition, so it needs internet.
 *    A "network" error is surfaced so the app can switch to the text box.
 *  - No real noise suppression, no second-speaker detection.
 *  - Confidence scores are unreliable (Chrome often returns 0), so we ignore them.
 *  - Firefox has no SpeechRecognition; the app falls back to typing.
 * We never record or store audio — the API does not even expose it.
 */
(function () {
  "use strict";

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const FATAL_ERRORS = ["network", "not-allowed", "service-not-allowed", "audio-capture", "language-not-supported"];

  class VoiceError extends Error {
    constructor(code) {
      super(code);
      this.code = code;
    }
  }

  /**
   * Listen for one turn. Resolves {transcript, reason, heard}:
   *   reason "pause"   — speech, then `silenceMs` of quiet (end of turn)
   *   reason "silence" — nothing at all for `noSpeechMs`
   *   reason "noise"   — the recogniser returned results it could not turn into words
   *                      (Chrome's speechstart event alone is NOT used: it fires for fans,
   *                      traffic and breathing, which made plain silence look like noise)
   *   reason "timeout" — `maxMs` reached
   *   reason "done"    — finish() called (the "Done" button)
   * Rejects with VoiceError on fatal errors (network, mic blocked...).
   * Chrome often stops recognition on its own; we restart it while the turn is active.
   */
  function listen({ lang = "hi-IN", silenceMs = 3000, noSpeechMs = 8000, maxMs = 45000, onText } = {}) {
    let finalText = "";
    let interim = "";
    let active = true;
    let heard = false; // got words
    let unclear = false; // recogniser heard something but produced no words
    let rec = null;
    let resolveFn, rejectFn;
    const timers = {};
    const promise = new Promise((res, rej) => { resolveFn = res; rejectFn = rej; });

    const text = () => `${finalText} ${interim}`.replace(/\s+/g, " ").trim();
    const clearTimers = () => Object.values(timers).forEach(clearTimeout);
    const stopRec = () => { try { rec && rec.abort(); } catch (_) { /* already stopped */ } };

    function end(reason) {
      if (!active) return;
      active = false;
      clearTimers();
      stopRec();
      const transcript = text();
      if (reason === "silence" && unclear && !transcript) reason = "noise";
      resolveFn({ transcript, reason, heard });
    }

    function fail(code) {
      if (!active) return;
      active = false;
      clearTimers();
      stopRec();
      rejectFn(new VoiceError(code));
    }

    function armSilence() {
      clearTimeout(timers.silence);
      timers.silence = setTimeout(() => end("pause"), silenceMs);
    }

    function startRec() {
      rec = new Recognition();
      rec.lang = lang;
      rec.continuous = true;
      rec.interimResults = true;

      rec.onnomatch = () => { unclear = true; };
      rec.onresult = (e) => {
        if (!e.results.length || !e.results[e.results.length - 1][0].transcript.trim()) unclear = true;
        let now = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i];
          if (r.isFinal) finalText += " " + r[0].transcript;
          else now += r[0].transcript;
        }
        interim = now;
        if (text()) {
          heard = true;
          clearTimeout(timers.noSpeech);
          armSilence();
        }
        if (onText) onText(text());
      };
      rec.onerror = (e) => {
        if (FATAL_ERRORS.includes(e.error)) fail(e.error);
        // "no-speech" and "aborted" are normal; our own timers handle silence.
      };
      rec.onend = () => {
        if (!active) return;
        // Chrome stopped by itself: keep what we have and restart.
        if (interim) { finalText += " " + interim; interim = ""; }
        setTimeout(() => {
          if (!active) return;
          try { startRec(); } catch (_) { fail("restart-failed"); }
        }, 150);
      };
      rec.start();
    }

    timers.noSpeech = setTimeout(() => { if (!heard) end("silence"); }, noSpeechMs);
    timers.max = setTimeout(() => end("timeout"), maxMs);
    try { startRec(); } catch (_) { fail("start-failed"); }

    return {
      promise,
      finish: (reason = "done") => end(reason),
      cancel: () => { if (active) { active = false; clearTimers(); stopRec(); } },
    };
  }

  // ---------- speech synthesis ----------
  //
  // Why Kyun-Kyun used to sound bad: Roman Hinglish ("Mujhe samjhao na") read by
  // an English voice, at a chipmunk pitch, with whatever voice came first.
  // Now: Hinglish lines are spoken from their Devanagari form by the best Hindi
  // voice on the device, natural/neural voices are preferred, pitch is only
  // slightly raised, and long lines are spoken sentence by sentence (Chrome's
  // online voices cut off long utterances).

  const KK_PITCH = 1.15; // a little younger-sounding, still clear
  const KK_RATE = 0.95;
  let voices = [];
  let speakToken = 0;

  function loadVoices() { voices = window.speechSynthesis ? speechSynthesis.getVoices() : []; }
  if (window.speechSynthesis) {
    loadVoices();
    speechSynthesis.addEventListener("voiceschanged", loadVoices);
  }

  /** Chrome loads voices asynchronously; wait briefly for them on first use. */
  function voicesReady() {
    if (!window.speechSynthesis || voices.length) return Promise.resolve();
    return new Promise((resolve) => {
      const t = setTimeout(resolve, 1200);
      speechSynthesis.addEventListener("voiceschanged", () => { clearTimeout(t); loadVoices(); resolve(); }, { once: true });
    });
  }

  const norm = (v) => v.lang.replace("_", "-").toLowerCase();

  function rankVoice(v, lang) {
    const want = lang.toLowerCase();
    let score;
    if (norm(v) === want) score = 100;
    else if (norm(v).split("-")[0] === want.split("-")[0]) score = 50;
    else return -1;
    if (/natural|neural/i.test(v.name)) score += 40; // Edge "Online (Natural)" voices
    if (/google/i.test(v.name)) score += 30; // Chrome's Google voices
    if (/online|premium|enhanced/i.test(v.name)) score += 10;
    if (/swara|neerja|kalpana|heera|female/i.test(v.name)) score += 3; // lighter voice suits a child character
    return score;
  }

  /** Best voice for a locale; with `avoid`, the best *other* voice (for the demo student). */
  function bestVoice(lang, avoid = null) {
    let best = null;
    let bestScore = -1;
    for (const v of voices) {
      if (avoid && v.name === avoid.name) continue;
      const s = rankVoice(v, lang);
      if (s > bestScore) { best = v; bestScore = s; }
    }
    return best;
  }

  /** Which voice and text to use for a line, for the student's language. */
  // Script of the spoken text -> voice locales to try, best first. Only hand a voice
  // text in its own script: Roman Hindi through a Hindi voice sounds garbled.
  const SCRIPTS = [
    { re: /[਀-੿]/, langs: ["pa-IN"] }, // Gurmukhi (Punjabi)
    { re: /[஀-௿]/, langs: ["ta-IN"] }, // Tamil
    { re: /[ঀ-৿]/, langs: ["bn-IN", "bn-BD"] }, // Bengali
    { re: /[ऀ-ॿ]/, langs: ["hi-IN"] }, // Devanagari (Hindi, Hinglish, Marathi)
  ];

  function chooseSpeech(line, language, student = false) {
    if (student) {
      // Demo student: a different voice from Kyun-Kyun's when the device has one.
      const kk = chooseSpeech(line, language);
      const other = kk.voice ? bestVoice(kk.lang, kk.voice) : null;
      return { ...kk, voice: other && rankVoice(other, kk.lang) >= 100 ? other : kk.voice };
    }
    const speak = line.speak || "";
    if (language !== "en") {
      for (const s of SCRIPTS) {
        if (!s.re.test(speak)) continue;
        // Marathi is Devanagari too: prefer a Marathi voice, else a Hindi voice reads it acceptably.
        const langs = s.langs[0] === "hi-IN" && language === "mr" ? ["mr-IN", "hi-IN"] : s.langs;
        for (const l of langs) {
          const v = bestVoice(l);
          if (v) return { text: speak, voice: v, lang: v.lang };
        }
        break;
      }
    }
    // English, or no matching voice on this device: speak the Roman text in Indian English.
    // If the on-screen text has no Roman letters (e.g. Tamil only), stay silent rather than garble it.
    if (!/[a-z]/i.test(line.text || "")) return { text: "", voice: null, lang: "en-IN" };
    const english = bestVoice("en-IN") || bestVoice("en-GB") || bestVoice("en-US");
    return { text: line.text, voice: english, lang: english ? english.lang : "en-IN" };
  }

  function speakOne(text, voice, lang, pitch = KK_PITCH, rate = KK_RATE) {
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang;
      if (voice) u.voice = voice;
      u.pitch = pitch;
      u.rate = rate;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        clearTimeout(guard);
        clearTimeout(noStart);
        resolve();
      };
      // Chrome sometimes never fires onend; don't let the conversation hang.
      const guard = setTimeout(finish, 3000 + text.length * 110);
      // No voice / audio blocked: speech never starts, so move on.
      const noStart = setTimeout(finish, 4000);
      u.onstart = () => clearTimeout(noStart);
      u.onend = finish;
      u.onerror = finish;
      speechSynthesis.speak(u);
    });
  }

  const splitSentences = (text) =>
    (text.match(/[^.!?।]+[.!?।]*/g) || [text]).map((s) => s.trim()).filter(Boolean);

  /**
   * Speak one of Kyun-Kyun's lines: {text (shown), speak (for TTS)}.
   * { student: true } speaks as the Demo-mode student instead: another voice
   * if available, normal pitch, a little faster.
   * Always resolves, even if TTS is missing, blocked or stalls.
   */
  async function speakLine(line, language = "hinglish", { student = false } = {}) {
    if (!window.speechSynthesis || !line || !(line.text || line.speak)) return;
    const token = ++speakToken;
    speechSynthesis.cancel();
    await voicesReady();
    const { text, voice, lang } = chooseSpeech(line, language, student);
    const [pitch, rate] = student ? [0.9, 1.05] : [KK_PITCH, KK_RATE];
    await new Promise((r) => setTimeout(r, 60)); // Chrome drops an utterance queued right after cancel()
    for (const sentence of splitSentences(text)) {
      if (token !== speakToken) return; // interrupted
      await speakOne(sentence, voice, lang, pitch, rate);
    }
  }

  function stopSpeaking() {
    speakToken++;
    if (window.speechSynthesis) speechSynthesis.cancel();
  }

  /** For the "test voice" button: which voice will be used for this language. */
  function voiceName(language = "hinglish") {
    const { voice } = chooseSpeech({ text: "x", speak: "x" }, language);
    return voice ? `${voice.name} (${voice.lang})` : "default voice";
  }

  window.JVoice = {
    canListen: !!Recognition,
    canSpeak: !!window.speechSynthesis,
    listen,
    speakLine,
    stopSpeaking,
    voiceName,
    voicesReady,
    VoiceError,
  };
})();
