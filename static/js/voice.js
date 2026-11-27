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
   *   reason "noise"   — sound detected but nothing recognised by `noSpeechMs`
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
    let sound = false; // browser detected speech-like sound
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
      if (reason === "silence" && sound && !transcript) reason = "noise";
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

      rec.onspeechstart = () => { sound = true; };
      rec.onresult = (e) => {
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

  function bestVoice(lang) {
    let best = null;
    let bestScore = -1;
    for (const v of voices) {
      const s = rankVoice(v, lang);
      if (s > bestScore) { best = v; bestScore = s; }
    }
    return best;
  }

  /** Which voice and text to use for a line, for the student's language. */
  function chooseSpeech(line, language) {
    // Only hand Devanagari to the Hindi voice; Roman Hindi through it sounds garbled.
    if (language !== "en" && /[ऀ-ॿ]/.test(line.speak || "")) {
      const hindi = bestVoice("hi-IN");
      if (hindi) return { text: line.speak, voice: hindi, lang: hindi.lang };
    }
    // English, or no Hindi voice on this device: speak the Roman text in Indian English.
    const english = bestVoice("en-IN") || bestVoice("en-GB") || bestVoice("en-US");
    return { text: line.text, voice: english, lang: english ? english.lang : "en-IN" };
  }

  function speakOne(text, voice, lang) {
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang;
      if (voice) u.voice = voice;
      u.pitch = KK_PITCH;
      u.rate = KK_RATE;
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
   * Always resolves, even if TTS is missing, blocked or stalls.
   */
  async function speakLine(line, language = "hinglish") {
    if (!window.speechSynthesis || !line || !(line.text || line.speak)) return;
    const token = ++speakToken;
    speechSynthesis.cancel();
    await voicesReady();
    const { text, voice, lang } = chooseSpeech(line, language);
    await new Promise((r) => setTimeout(r, 60)); // Chrome drops an utterance queued right after cancel()
    for (const sentence of splitSentences(text)) {
      if (token !== speakToken) return; // interrupted
      await speakOne(sentence, voice, lang);
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
