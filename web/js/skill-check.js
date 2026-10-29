// Skill check (skill-check.html): pick a role, rate its 10 most-asked skills, get an AI report.
// Ratings stay in this browser (for the next check) and go anonymously to submit_skill_ratings()
// (a random id, the role, the numbers) so candidates can be compared. The report comes from the
// skill-report Edge Function. "Download PDF" uses the browser's print dialog (print styles in css/style.css).
(() => {
  const C = window.SITE_CONFIG || {};
  // Local testing against `supabase start`: localhost/skill-check.html?api=http://127.0.0.1:54321&anon=<local anon key>
  const params = new URLSearchParams(location.search);
  const LOCAL = location.hostname === "localhost" && params.get("api");
  const API = (LOCAL || C.SUPABASE_URL || "").replace(/\/$/, "");
  const KEY = LOCAL ? params.get("anon") : C.SUPABASE_ANON_KEY;
  const FN = `${API}/functions/v1/skill-report`;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: only this visit */ } },
  };
  const clientId = () => {
    let id = store.get("ejg.clientId", null);
    if (!id) { id = crypto.randomUUID(); store.set("ejg.clientId", id); }
    return id;
  };
  const pct = (x) => `${Math.round(x * 100)}%`;
  const READINESS = {
    apply_now: ["ok", "Ready to apply"],
    apply_while_learning: ["info", "Apply while you learn"],
    build_first: ["warn", "Build a few skills first"],
  };

  let roles = [];
  let role = null;

  async function init() {
    try { roles = (await (await fetch("data/skill-roles.json")).json()).roles; } catch { roles = []; }
    $("#skc-role-form").addEventListener("submit", (ev) => { ev.preventDefault(); pickRole($("#skc-role").value); });
    const last = store.get("ejg.skillLastRole", "");
    if (last && roles.some((r) => r.t === last)) { $("#skc-role").value = last; pickRole(last); }
  }

  function pickRole(name) {
    role = roles.find((r) => r.t.toLowerCase() === name.trim().toLowerCase());
    if (!role) {
      $("#skc-role-hint").innerHTML = `No role called “${esc(name)}” yet — pick one from the list (start typing to see suggestions).`;
      return;
    }
    $("#skc-role").value = role.t;
    $("#skc-role-hint").textContent = `Based on ${role.n} job descriptions for this role.`;
    store.set("ejg.skillLastRole", role.t);
    renderSliders();
    const prev = store.get("ejg.skillHistory", {})[role.t];
    if (prev?.report) renderReport(prev.report, prev.peers, prev.levels, null, prev.date);
    else $("#skc-report").hidden = true;
  }

  function renderSliders() {
    const saved = store.get("ejg.skillLevels", {});
    const form = $("#skc-skills");
    form.innerHTML = `<h2>Rate yourself</h2>
      <p class="skc-hint">1 = never used it · 5 = used it in a project · 10 = could teach it. Be honest; nobody sees your name.
      Priority (0–100) = how often postings ask for the skill, counting must-haves fully and nice-to-haves half.</p>
      <div class="skc-sliders">${role.skills.map((s, i) => {
        const v = saved[s.n] ?? 5;
        return `<div class="skc-slider">
          <label for="skc-s${i}"><b>${esc(s.n)}</b><span>priority ${s.p}/100 · asked in ${pct(s.s)} of postings${s.r < 0.5 ? " · often nice-to-have" : ""}</span></label>
          <input type="range" id="skc-s${i}" min="1" max="10" step="1" value="${v}" data-skill="${esc(s.n)}">
          <output for="skc-s${i}">${v}</output>
        </div>`;
      }).join("")}</div>
      <div class="skc-actions"><button class="btn primary" type="submit">Get my AI report</button>
      <span class="skc-status" role="status"></span></div>`;
    form.hidden = false;
    form.querySelectorAll("input[type=range]").forEach((el) =>
      el.addEventListener("input", () => { el.nextElementSibling.textContent = el.value; }));
    form.onsubmit = (ev) => { ev.preventDefault(); submit(); };
  }

  async function submit() {
    const levels = {};
    $("#skc-skills").querySelectorAll("input[type=range]").forEach((el) => { levels[el.dataset.skill] = Number(el.value); });
    const history = store.get("ejg.skillHistory", {});
    const before = history[role.t]?.levels || null;
    store.set("ejg.skillLevels", { ...store.get("ejg.skillLevels", {}), ...levels });

    const btn = $("#skc-skills button[type=submit]");
    const status = $("#skc-skills .skc-status");
    btn.disabled = true;
    status.textContent = "Writing your report… (about 15 seconds)";
    try {
      // Anonymous ratings for the candidate comparison — the report still works if this fails.
      await fetch(`${API}/rest/v1/rpc/submit_skill_ratings`, {
        method: "POST",
        headers: { apikey: KEY, Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" },
        body: JSON.stringify({ p_client: clientId(), p_role: role.t, p_levels: levels }),
      }).catch(() => {});
      const res = await fetch(FN, { method: "POST", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ role: role.t, levels, client: clientId() }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.report) throw new Error(data.error || "The report could not be generated. Please try again.");
      const date = new Date().toISOString().slice(0, 10);
      history[role.t] = { date, levels, report: data.report, peers: data.peers, before };
      store.set("ejg.skillHistory", history);
      status.textContent = "";
      renderReport(data.report, data.peers, levels, before, date);
      $("#skc-report").scrollIntoView({ behavior: "smooth", block: "start" });
      if (window.goatcounter?.count) window.goatcounter.count({ path: "skill-report", event: true });
    } catch (err) {
      status.textContent = err instanceof TypeError  // network error / blocked request: the browser's text is "Failed to fetch"
        ? "Could not reach the report service. Check your connection and try again."
        : err.message;
    } finally {
      btn.disabled = false;
    }
  }

  function renderReport(r, peers, levels, before, date) {
    const peerSkills = peers?.skills || null;
    const [cls, label] = READINESS[r.readiness] || READINESS.apply_while_learning;
    const list = (items, fn) => (items || []).length ? `<ul>${items.map(fn).join("")}</ul>` : "";
    const rows = role.skills.map((s) => `<tr><td>${esc(s.n)}<small class="skc-asked">asked in ${pct(s.s)}</small></td>
      <td><span class="skc-bar" style="--w:${s.p}%"></span><b>${s.p}</b></td><td><b>${levels[s.n] ?? "–"}</b>${
      before && before[s.n] != null && before[s.n] !== levels[s.n] ? ` <small>(was ${before[s.n]})</small>` : ""}</td>${
      peerSkills ? `<td>${peerSkills[s.n] ? `${peerSkills[s.n].avg}` : "–"}</td><td>${
        peerSkills[s.n] ? `higher than ${peerSkills[s.n].pct}%` : "–"}</td>` : ""}</tr>`).join("");
    $("#skc-report").innerHTML = `
      <div class="skc-report-head">
        <div><p class="skc-kicker">Skill report · ${esc(role.t)} · ${esc(date)}</p><h2>${esc(r.headline)}</h2></div>
        <span class="badge ${cls}">${label}</span>
      </div>
      <p>${esc(r.readiness_reason)}</p>
      <h3>Skills the job descriptions ask for</h3>
      <div class="skc-table-wrap"><table class="skc-table"><thead><tr><th>Skill</th><th>Priority</th><th>You</th>${
        peerSkills ? "<th>Others (avg)</th><th>You vs others</th>" : ""}</tr></thead>
        <tbody>${rows}</tbody></table></div>
      <p class="skc-hint">Based on ${role.n} job descriptions${peers?.n ? ` and ${peers.n} other candidate${peers.n === 1 ? "" : "s"} who rated this role` : ""}.${
        peerSkills ? "" : " The comparison with other candidates appears once 10 people have rated this role."}</p>
      ${r.strengths?.length ? `<h3>Your strengths</h3>${list(r.strengths, (s) => `<li><b>${esc(s.skill)}</b> — ${esc(s.note)}</li>`)}` : ""}
      ${r.focus?.length ? `<h3>Where to put your effort</h3>${list(r.focus, (f) =>
        `<li><b>${esc(f.skill)}</b><p>${esc(f.why)}</p><p><i>How:</i> ${esc(f.how)}</p></li>`)}` : ""}
      ${r.peers ? `<h3>Compared with other candidates</h3><p>${esc(r.peers)}</p>` : ""}
      ${r.interview?.length ? `<h3>Prepare for the interview</h3>${list(r.interview, (t) => `<li>${esc(t)}</li>`)}` : ""}
      ${r.plan?.length ? `<h3>Your 4-week plan</h3>${list(r.plan, (t) => `<li>${esc(t)}</li>`)}` : ""}
      ${r.encouragement ? `<p class="skc-encourage">${esc(r.encouragement)}</p>` : ""}
      <p class="skc-hint">Written by AI from job-posting statistics and your self-ratings — a starting point, not a verdict.</p>
      <div class="skc-actions no-print">
        <button class="btn primary" type="button" id="skc-pdf">Download PDF</button>
        <a class="btn ghost" href="index.html?q=${encodeURIComponent(role.t)}">See open ${esc(role.t)} jobs</a>
      </div>`;
    $("#skc-report").hidden = false;
    $("#skc-pdf").onclick = () => window.print();
  }

  init();
})();
