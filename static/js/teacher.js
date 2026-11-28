/* Jigyasa teacher dashboard.
 * The teacher key is kept in this browser (localStorage) and sent as the
 * X-Teacher-Key header. A teacher link (#code=…&key=…) logs in on any device;
 * the key is removed from the address bar right after reading it.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const CREDS_KEY = "jigyasa.teacher";
  const REFRESH_MS = 30000;

  let creds = null; // {code, key}
  let refreshTimer = null;
  let chapters = []; // from the last dashboard, for table columns

  // ---------- helpers ----------

  function load() { try { return JSON.parse(localStorage.getItem(CREDS_KEY) || "null"); } catch (_) { return null; } }
  function save(c) { try { localStorage.setItem(CREDS_KEY, JSON.stringify(c)); } catch (_) { /* private mode */ } }
  function forget() { try { localStorage.removeItem(CREDS_KEY); } catch (_) { /* private mode */ } }

  async function api(path, { method = "GET", body } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (creds) headers["X-Teacher-Key"] = creds.key;
    const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) {
      const err = new Error(`${path} -> ${r.status}`);
      err.status = r.status;
      throw err;
    }
    return r.json();
  }

  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v;
      else if (k === "on") Object.entries(v).forEach(([ev, fn]) => e.addEventListener(ev, fn));
      else if (v !== undefined && v !== null) e.setAttribute(k, v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined) e.append(c);
    return e;
  }

  const teacherLink = (c) => `${location.origin}/teacher.html#code=${encodeURIComponent(c.code)}&key=${encodeURIComponent(c.key)}`;
  const band = (score) => (score >= 70 ? "good" : score >= 40 ? "mid" : "low");

  function view(name) {
    for (const v of ["setup", "created", "dash"]) $(v).hidden = v !== name;
    clearInterval(refreshTimer);
    if (name === "dash") {
      refreshTimer = setInterval(() => { if (!document.hidden) refresh(); }, REFRESH_MS);
    }
  }

  function setupError(msg) {
    $("setup-error").textContent = msg;
    $("setup-error").hidden = !msg;
  }

  async function copy(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
      const old = btn.textContent;
      btn.textContent = "✓ Copied";
      setTimeout(() => { btn.textContent = old; }, 1500);
    } catch (_) {
      window.prompt("Copy this link:", text);
    }
  }

  /** Read #code=…&key=… (teacher link), store it, and clean the address bar. */
  function credsFromHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    if (p.get("code") && p.get("key")) {
      history.replaceState(null, "", location.pathname);
      return { code: p.get("code"), key: p.get("key") };
    }
    return null;
  }

  function credsFromLink(text) {
    try {
      const u = new URL(text.trim());
      const p = new URLSearchParams(u.hash.slice(1));
      if (p.get("code") && p.get("key")) return { code: p.get("code"), key: p.get("key") };
    } catch (_) { /* not a URL */ }
    return null;
  }

  // ---------- setup ----------

  async function createClass(e) {
    e.preventDefault();
    setupError("");
    try {
      creds = null;
      const r = await api("/api/class", { method: "POST", body: { name: $("class-name").value } });
      creds = { code: r.code, key: r.teacher_key };
      save(creds);
      $("c-code").textContent = r.code;
      $("c-link").value = teacherLink(creds);
      view("created");
    } catch (err) {
      setupError("Couldn't create the class. Is the server running? · क्लास नहीं बनी।");
    }
  }

  async function openClass(e) {
    e.preventDefault();
    setupError("");
    const c = credsFromLink($("open-link").value)
      || { code: $("open-code").value.trim(), key: $("open-key").value.trim() };
    if (!/^\d{6}$/.test(c.code) || !c.key) {
      setupError("Paste your teacher link, or enter the 6-digit code and the teacher key.");
      return;
    }
    creds = c;
    await showDashboard();
  }

  async function demoClass() {
    setupError("");
    $("btn-demo").disabled = true;
    $("btn-demo").textContent = "Loading…";
    try {
      creds = null;
      const r = await api("/api/class/demo", { method: "POST" });
      creds = { code: r.code, key: r.teacher_key };
      save(creds);
      await showDashboard();
    } catch (err) {
      setupError("Couldn't load the sample class. · नमूना क्लास नहीं खुली।");
    } finally {
      $("btn-demo").disabled = false;
      $("btn-demo").textContent = "Load sample class";
    }
  }

  // ---------- dashboard ----------

  async function showDashboard() {
    try {
      const d = await api(`/api/class/${encodeURIComponent(creds.code)}/dashboard`);
      save(creds);
      render(d);
      view("dash");
    } catch (err) {
      const msg = err.status === 403 ? "That teacher key doesn't match this class. · टीचर की गलत है।"
        : err.status === 404 || err.status === 422 ? "No class with that code. · इस कोड की कोई क्लास नहीं।"
          : "Couldn't load the dashboard. Is the server running?";
      if (err.status === 403 || err.status === 404) forget();
      creds = err.status === 403 || err.status === 404 ? null : creds;
      setupError(msg);
      view("setup");
    }
  }

  async function refresh() {
    if (!creds) return;
    try { render(await api(`/api/class/${encodeURIComponent(creds.code)}/dashboard`)); } catch (_) { /* keep old view */ }
  }

  function render(d) {
    chapters = d.chapters;
    $("d-name").textContent = d.class.name;
    $("d-code").textContent = d.class.code;
    $("empty-code").textContent = d.class.code;
    $("demo-note").hidden = !d.class.demo;
    $("s-students").textContent = d.totals.students;
    $("s-sessions").textContent = d.totals.sessions;
    $("s-average").textContent = d.totals.average ?? "—";

    const empty = d.totals.sessions === 0;
    $("empty").hidden = !empty;
    $("dash-body").hidden = empty;
    if (empty) return;

    // What to reteach: top 2 missed concepts across the class
    $("reteach").replaceChildren(...(d.reteach.length ? d.reteach.map((r) => el("li", {},
      el("div", { class: "barline" },
        el("span", {}, `${r.emoji} `, el("b", {}, r.name_en), ` · ${r.name_hi}`),
        el("span", { class: "pct" }, `${r.percent}%`)),
      el("div", { class: "track" }, el("i", { style: `width:${r.percent}%` })),
      el("small", { class: "muted" }, `${r.count} students missed this in ${r.chapter}`))) : [el("li", {}, "Nothing major — everyone covered the key ideas. 🎉")]));

    // Ranked misconceptions across chapters ("60% think plants eat soil")
    const all = d.chapters.flatMap((ch) => ch.misconceptions.map((m) => ({ ...m, emoji: ch.emoji, chapter: ch.title, n: ch.students })));
    all.sort((a, b) => b.percent - a.percent || b.count - a.count);
    $("miscon").replaceChildren(...(all.length ? all.map((m) => el("li", {},
      el("div", { class: "barline" },
        el("span", {}, `${m.emoji} `, el("b", {}, `${m.percent}% think: `), `“${m.name_en}”`),
        el("span", { class: "pct" }, `${m.count}/${m.n}`)),
      el("div", { class: "track warn" }, el("i", { style: `width:${m.percent}%` })),
      el("small", { class: "muted" }, m.name_hi))) : [el("li", {}, "No misconceptions found yet.")]));

    // Per-chapter averages
    $("chapters").replaceChildren(...d.chapters.map((ch) => el("div", { class: "chapter-stat" },
      el("span", { class: "emoji" }, ch.emoji),
      el("b", {}, ch.title),
      el("small", { class: "muted" }, `Class ${ch.class} · ${ch.students} student${ch.students === 1 ? "" : "s"}`),
      el("span", { class: `pill ${ch.average === null ? "" : band(ch.average)}` }, ch.average === null ? "—" : `${ch.average}`))));

    // Students × chapters
    $("students-head").replaceChildren(el("th", {}, "Name · नाम"),
      ...d.chapters.map((ch) => el("th", { title: ch.title }, `${ch.emoji} ${ch.title}`)),
      el("th", {}, "Avg"));
    $("students").tBodies[0].replaceChildren(...d.students.map((st) => el("tr", {},
      el("td", {}, el("b", {}, st.name), el("small", { class: "muted" }, ` · ${st.sessions} session${st.sessions === 1 ? "" : "s"}`)),
      ...d.chapters.map((ch) => {
        const c = st.chapters[ch.id];
        if (!c) return el("td", { class: "muted" }, "—");
        return el("td", {}, el("button", {
          class: `pill ${band(c.score)}`, type: "button", title: "See transcript",
          on: { click: () => openDetail(c.session_id) },
        }, `${c.score}`, c.misconceptions ? " ⚠" : ""));
      }),
      el("td", {}, st.average ?? "—"))));
  }

  // ---------- one student's session ----------

  async function openDetail(sessionId) {
    let s;
    try {
      s = await api(`/api/class/${encodeURIComponent(creds.code)}/session/${encodeURIComponent(sessionId)}`);
    } catch (_) { return; }
    const r = s.result || {};
    $("x-title").textContent = `${s.student_name || "Student"} · ${s.chapter.emoji || ""} ${s.chapter.title || s.chapter.id}`;
    const statusLabel = { answered: "", skipped: " (pata nahi — skipped)" };
    $("x-body").replaceChildren(...[
      el("div", { class: "detail-score" },
        el("span", { class: `pill big ${band(r.score)}` }, `${r.score ?? "—"}/100`),
        r.breakdown ? el("small", { class: "muted" },
          `Correct ideas ${r.breakdown.correctness} · Reasoning ${r.breakdown.reasoning} · Coverage ${r.breakdown.coverage}`) : null,
        el("small", { class: "muted" }, `${s.brain === "llm" ? "AI brain" : "Offline brain"} · ${s.language} · ${(s.finished_at || "").replace("T", " ").slice(0, 16)}`)),
      s.copy_suspected ? el("p", { class: "notice" }, "⚠ The explanation sounded read from a textbook, and a follow-up answer was weak. Reasoning was scored lower.") : null,
      el("h3", {}, "Explanation · समझाया"),
      el("blockquote", {}, s.explanation || "—"),
      el("h3", {}, "Kyun-Kyun's questions · सवाल"),
      el("ol", { class: "qa" }, ...s.answers.map((a) => el("li", {},
        el("b", {}, a.question),
        el("div", {}, `→ ${a.transcript || "—"}`, el("small", { class: "muted" }, `${statusLabel[a.status] || ""}${a.hints ? ` · ${a.hints} hint` : ""}`))))),
      r.misconceptions && r.misconceptions.length ? el("h3", {}, "Misconceptions · गलत-फ़हमियाँ") : null,
      ...(r.misconceptions || []).map((m) => el("div", { class: "miscon" },
        el("p", {}, `🤔 “${m.student_said}”`), el("p", {}, `💡 ${m.correct_idea}`))),
      el("h3", {}, "Covered / missing"),
      el("p", {}, "✅ ", (r.concepts_covered || []).join(", ") || "—"),
      el("p", {}, "🔍 ", (r.concepts_missing || []).join(", ") || "—"),
      el("h3", {}, "Feedback the student heard"),
      el("p", {}, r.feedback_in_student_language || "—"),
    ].filter(Boolean)); // replaceChildren would print "null" for skipped parts
    $("detail").showModal();
  }

  // ---------- start ----------

  function init() {
    $("create-form").addEventListener("submit", createClass);
    $("open-form").addEventListener("submit", openClass);
    $("btn-demo").addEventListener("click", demoClass);
    $("btn-open-new").addEventListener("click", showDashboard);
    $("btn-copy-new").addEventListener("click", (e) => copy($("c-link").value, e.target));
    $("btn-link").addEventListener("click", (e) => copy(teacherLink(creds), e.target));
    $("btn-refresh").addEventListener("click", refresh);
    $("btn-switch").addEventListener("click", () => { forget(); creds = null; view("setup"); });
    $("btn-close").addEventListener("click", () => $("detail").close());
    $("detail").addEventListener("click", (e) => { if (e.target === $("detail")) $("detail").close(); });

    creds = credsFromHash() || load();
    if (creds) showDashboard();
    else view("setup");
  }

  init();
})();
