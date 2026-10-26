// English Jobs Germany — vanilla JS, no build step, no dependencies.
// Personal data (saved, applied, seen, hidden companies) lives ONLY in this
// browser's localStorage. Nothing personal is ever sent to the server.
(() => {
  "use strict";
  const C = window.SITE_CONFIG;
  const DEMO = !C.SUPABASE_URL;
  const PAGE = C.PAGE_SIZE || 20;

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------------------------------------------------------------- storage
  const store = {
    get(k, d) { try { const v = localStorage.getItem("ejg." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("ejg." + k, JSON.stringify(v)); } catch { /* private mode etc. */ } },
  };
  let saved = store.get("saved", {});        // id -> {job, at}
  let applied = store.get("applied", {});    // id -> {job, at}
  let seenList = store.get("seen", []);
  const seen = new Set(seenList);
  let hiddenCompanies = store.get("hiddenCompanies", []);
  let excludeWords = store.get("excludeWords", []);
  const prevVisit = store.get("lastVisit", null);
  store.set("lastVisit", new Date().toISOString());

  function markSeen(id) {
    if (seen.has(id)) return;
    seen.add(id); seenList.push(id);
    if (seenList.length > 3000) seenList = seenList.slice(-3000);
    store.set("seen", seenList);
  }

  // ---------------------------------------------------------------- backend
  async function rpc(name, body = {}) {
    if (DEMO) return window.DemoBackend[name](body);
    const res = await fetch(`${C.SUPABASE_URL.replace(/\/$/, "")}/rest/v1/rpc/${name}`, {
      method: "POST",
      headers: { apikey: C.SUPABASE_ANON_KEY, Authorization: `Bearer ${C.SUPABASE_ANON_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${name}: ${res.status}`);
    const text = await res.text();
    return text ? JSON.parse(text) : null;
  }

  // ---------------------------------------------------------------- glossary
  const GLOSSARY = {
    "unbefristet": "Permanent contract (no end date).",
    "befristet": "Fixed-term contract with an end date.",
    "werkstudent": "Working student: part-time job (usually max 20 h/week in semester) for enrolled students.",
    "praktikum": "Internship. Mandatory internships may be unpaid; voluntary ones over 3 months must pay minimum wage.",
    "minijob": "Small job with a monthly earnings cap; low or no taxes and social contributions.",
    "teilzeit": "Part-time.",
    "vollzeit": "Full-time.",
    "ausbildung": "Vocational training: paid apprenticeship combining school and work, usually 2–3.5 years.",
    "berufserfahren": "Experienced professional (not entry level).",
    "berufseinsteiger": "Entry level / career starter.",
    "quereinsteiger": "Career changer: no formal training in this field required.",
    "probezeit": "Probation period, usually up to 6 months, with a shorter notice period.",
    "m/w/d": "männlich/weiblich/divers — male/female/diverse. Required in German job titles; it just means 'all genders'.",
    "teamleitung": "Team lead role.",
    "festanstellung": "Permanent employment.",
    "freiberuflich": "Freelance.",
    "brutto": "Gross (before tax). Salaries in Germany are almost always quoted gross per year.",
  };
  function glossaryHtml(text) {
    const low = String(text).toLowerCase();
    const key = Object.keys(GLOSSARY).find((k) => low.includes(k));
    return key ? `<abbr title="${esc(GLOSSARY[key])}">${esc(text)}</abbr>` : esc(text);
  }

  // ---------------------------------------------------------------- filters
  const NO_GERMAN = ["not_required", "nice_to_have", "not_mentioned"];
  const REMOTE = ["remote_de", "remote_eu"];
  const checked = (name) => $$(`input[name="${name}"]:checked`).map((i) => i.value);
  const setChecked = (name, vals) => $$(`input[name="${name}"]`).forEach((i) => { i.checked = vals.includes(i.value); });
  const sameSet = (a, b) => a.length === b.length && b.every((x) => a.includes(x));

  let tags = [];

  function readFilters() {
    return {
      q: $("#q").value.trim(),
      city: $("#city").value,
      tags: [...tags],
      german: checked("german"),
      remote: checked("remote"),
      seniority: checked("seniority"),
      salary: $("#f-salary").checked,
      visa: $("#f-visa").checked,
      reloc: $("#f-reloc").checked,
      direct: $("#f-direct").checked,
      years: $("#years").value,
      bluecard: $("#bluecard").value,
      days: $("#days").value,
      sort: $("#sort").value,
    };
  }

  function writeFilters(f) {
    $("#q").value = f.q || "";
    ensureCityOption(f.city);
    $("#city").value = f.city || "";
    tags = f.tags || [];
    setChecked("german", f.german || []);
    setChecked("remote", f.remote || []);
    setChecked("seniority", f.seniority || []);
    $("#f-salary").checked = !!f.salary;
    $("#f-visa").checked = !!f.visa;
    $("#f-reloc").checked = !!f.reloc;
    $("#f-direct").checked = !!f.direct;
    $("#years").value = f.years || "";
    $("#bluecard").value = f.bluecard || "";
    $("#days").value = f.days || "";
    $("#sort").value = f.sort || "newest";
    syncQuickChips();
  }

  function syncQuickChips() {
    $("#f-nogerman").checked = sameSet(checked("german"), NO_GERMAN);
    $("#f-remote").checked = sameSet(checked("remote"), REMOTE);
  }

  // URL <-> filters (so searches can be bookmarked and shared)
  const LIST_KEYS = ["tags", "german", "remote", "seniority"];
  const BOOL_KEYS = ["salary", "visa", "reloc", "direct"];
  function filtersToQuery(f) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) {
      if (LIST_KEYS.includes(k)) { if (v.length) p.set(k, v.join(",")); }
      else if (BOOL_KEYS.includes(k)) { if (v) p.set(k, "1"); }
      else if (v && !(k === "sort" && v === "newest")) p.set(k, v);
    }
    return p;
  }
  function filtersFromQuery() {
    const p = new URLSearchParams(location.search);
    const f = {};
    for (const [k, v] of p) {
      if (LIST_KEYS.includes(k)) f[k] = v.split(",").filter(Boolean);
      else if (BOOL_KEYS.includes(k)) f[k] = v === "1";
      else f[k] = v;
    }
    return f;
  }

  function rpcParams(f, offset) {
    const bc = f.bluecard ? C.BLUE_CARD[f.bluecard] : null;
    return {
      p_q: f.q || null,
      p_tags: f.tags.length ? f.tags : null,
      p_city: f.city || null,
      p_remote: f.remote.length ? f.remote : null,
      p_german: f.german.length ? f.german : null,
      p_seniority: f.seniority.length ? f.seniority : null,
      p_has_salary: f.salary,
      p_min_salary: bc || null,
      p_visa: f.visa,
      p_relocation: f.reloc,
      p_direct_only: f.direct,
      p_max_years: f.years ? Number(f.years) : null,
      p_days: f.days ? Number(f.days) : null,
      p_exclude_terms: excludeWords.length ? excludeWords : null,
      p_hide_companies: hiddenCompanies.length ? hiddenCompanies : null,
      p_sort: f.sort,
      p_limit: PAGE,
      p_offset: offset,
    };
  }

  // ---------------------------------------------------------------- rendering helpers
  const GERMAN_BADGE = {
    not_required: ["ok", "🇬🇧 No German needed"],
    nice_to_have: ["info", "German: nice to have"],
    not_mentioned: ["", "German: not mentioned"],
    required: ["bad", "German required"],
  };
  const REMOTE_LABEL = { remote_de: "🏠 Remote (DE)", remote_eu: "🏠 Remote (EU)", hybrid: "Hybrid", onsite: "On-site", unknown: "" };
  const SENIORITY_LABEL = { intern: "Intern / student", junior: "Junior", mid: "Mid-level", senior: "Senior", lead: "Lead", unspecified: "Not specified" };

  const k = (n) => (n >= 1000 ? `€${Math.round(n / 1000)}k` : `€${n}`);
  function salaryText(j) {
    if (!j.salary_min) return null;
    return j.salary_max && j.salary_max !== j.salary_min ? `${k(j.salary_min)}–${k(j.salary_max).slice(1)}` : k(j.salary_min);
  }
  function blueCard(j) {
    const BC = C.BLUE_CARD;
    const lo = j.salary_min, hi = j.salary_max ?? j.salary_min;
    if (!lo) return null;
    if (lo >= BC.standard) return ["ok", "Blue Card ✓", `Listed salary meets the ${BC.year} standard Blue Card minimum (€${BC.standard.toLocaleString("en")}).`];
    if (hi >= BC.standard) return ["info", "Blue Card possible", `Top of the range meets the ${BC.year} standard minimum (€${BC.standard.toLocaleString("en")}).`];
    if (hi >= BC.reduced) return ["info", "Blue Card (reduced) possible", `Meets the ${BC.year} reduced minimum (€${BC.reduced.toLocaleString("en")}) for IT/STEM, health and recent graduates.`];
    return null;
  }
  function ago(iso) {
    const s = (Date.now() - new Date(iso)) / 1000;
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    const d = Math.round(s / 86400);
    return d === 1 ? "yesterday" : `${d} days ago`;
  }
  const isNew = (j) => prevVisit && j.first_seen_at && new Date(j.first_seen_at) > new Date(prevVisit);

  function badges(j) {
    const out = [];
    if (isNew(j)) out.push(`<span class="badge new">NEW</span>`);
    const [gc, gl] = GERMAN_BADGE[j.german_level] || GERMAN_BADGE.not_mentioned;
    out.push(`<span class="badge ${gc}">${gl}</span>`);
    const sal = salaryText(j);
    if (sal) out.push(`<span class="badge ok">💶 ${sal}</span>`);
    const bc = blueCard(j);
    if (bc) out.push(`<span class="badge ${bc[0]}" title="${esc(bc[2])}">${bc[1]}</span>`);
    if (REMOTE_LABEL[j.remote_type]) out.push(`<span class="badge">${REMOTE_LABEL[j.remote_type]}</span>`);
    if (j.visa_sponsorship) out.push(`<span class="badge ok">🛂 Visa sponsorship</span>`);
    if (j.relocation) out.push(`<span class="badge ok">📦 Relocation</span>`);
    if (j.is_agency) out.push(`<span class="badge warn" title="Posted by a recruiting agency, not the employer">Recruiting agency</span>`);
    if (j.repost_count > 0) out.push(`<span class="badge warn" title="This job disappeared and came back — it may be hard to fill or an evergreen posting">Reposted ×${j.repost_count}</span>`);
    (j.job_types || []).slice(0, 2).forEach((t) => out.push(`<span class="badge">${glossaryHtml(t)}</span>`));
    const titleTerm = Object.keys(GLOSSARY).find((g) => j.title.toLowerCase().includes(g) && g !== "m/w/d");
    if (titleTerm) out.push(`<span class="badge"><abbr title="${esc(GLOSSARY[titleTerm])}">What is "${esc(titleTerm)}"?</abbr></span>`);
    return out.join("");
  }

  function factsHtml(j) {
    const facts = [
      ["Salary", salaryText(j) ? `${salaryText(j)} / year` : "Not listed"],
      ["German", (GERMAN_BADGE[j.german_level] || GERMAN_BADGE.not_mentioned)[1].replace("🇬🇧 ", "")],
      ["Work setup", REMOTE_LABEL[j.remote_type] || "Not specified"],
      ["Level", SENIORITY_LABEL[j.seniority] || "Not specified"],
      ["Experience asked", j.years_experience ? `${j.years_experience}+ years` : "Not specified"],
      ["Visa / relocation", [j.visa_sponsorship && "Visa sponsorship", j.relocation && "Relocation"].filter(Boolean).join(" + ") || "Not mentioned"],
      ["Location", j.location || j.city || "—"],
      ["Posted", j.posted_at ? ago(j.posted_at) : "—"],
    ];
    return `<dl class="facts">${facts.map(([a, b]) => `<div><dt>${esc(a)}</dt><dd>${esc(b)}</dd></div>`).join("")}</dl>`;
  }

  function jobHtml(j) {
    const isSaved = !!saved[j.id], isApplied = !!applied[j.id];
    return `
    <li class="job${seen.has(j.id) ? " seen" : ""}" data-id="${esc(j.id)}">
      <div class="job-top">
        <div>
          <h3 class="job-title"><button type="button" data-act="toggle" aria-expanded="false">${esc(j.title)}</button></h3>
          <div class="job-meta"><span class="company">${esc(j.company)}</span> · ${esc(j.city || j.location || "Germany")} · ${j.posted_at ? ago(j.posted_at) : ""}</div>
        </div>
        <div class="job-actions">
          <button type="button" class="btn ghost" data-act="save" aria-pressed="${isSaved}" title="Save for later">${isSaved ? "★ Saved" : "☆ Save"}</button>
          <button type="button" class="btn ghost" data-act="applied" aria-pressed="${isApplied}" title="Mark as applied">${isApplied ? "✓ Applied" : "Applied?"}</button>
          <button type="button" class="btn ghost" data-act="hide" title="Hide all jobs from this company">🚫</button>
        </div>
      </div>
      <div class="badges">${badges(j)}</div>
      <div class="job-details" hidden></div>
    </li>`;
  }

  function detailsHtml(j) {
    const kununu = `https://www.google.com/search?q=${encodeURIComponent(`${j.company} kununu`)}`;
    return `
      ${factsHtml(j)}
      ${j.snippet ? `<p class="snippet">${esc(j.snippet)}${j.snippet.length >= 600 ? "…" : ""}</p>` : ""}
      <div class="job-tags">${(j.tags || []).map((t) => `<button type="button" class="tag" data-tag="${esc(t)}">#${esc(t)}</button>`).join("")}</div>
      <div class="detail-actions">
        <a class="btn primary" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer nofollow" data-act="apply">Apply on original site ↗</a>
        <a class="btn" href="${kununu}" target="_blank" rel="noopener noreferrer nofollow">Company reviews ↗</a>
      </div>`;
  }

  // ---------------------------------------------------------------- state & search
  let tab = "all";
  let offset = 0;
  let total = 0;
  let current = new Map();   // id -> job (jobs currently on screen)
  let reqId = 0;

  async function search({ append = false } = {}) {
    if (tab !== "all") return;
    const f = readFilters();
    const qs = filtersToQuery(f).toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
    updateRss(qs);
    renderActiveTags();
    if (!append) offset = 0;
    const my = ++reqId;
    $("#result-count").textContent = "Searching…";
    try {
      const data = await rpc("search_jobs", rpcParams(f, offset));
      if (my !== reqId) return; // a newer search started
      total = data.total;
      if (!append) { current.clear(); $("#results").innerHTML = ""; }
      data.items.forEach((j) => current.set(j.id, j));
      $("#results").insertAdjacentHTML("beforeend", data.items.map(jobHtml).join(""));
      if (!append && !data.items.length) {
        $("#results").innerHTML = `<li class="empty">No jobs match these filters. Try removing a filter or a tag.</li>`;
      }
      offset += data.items.length;
      $("#result-count").textContent = `${total.toLocaleString("en")} job${total === 1 ? "" : "s"} found`;
      $("#load-more").hidden = offset >= total;
    } catch (e) {
      console.error(e);
      if (my === reqId) $("#result-count").textContent = "Couldn't load jobs right now. Please try again in a minute.";
    }
  }

  function renderLocal(kind) {
    const map = kind === "saved" ? saved : applied;
    const list = Object.values(map).sort((a, b) => new Date(b.at) - new Date(a.at));
    current.clear();
    list.forEach((x) => current.set(x.job.id, x.job));
    $("#results").innerHTML = list.length ? list.map((x) => jobHtml(x.job)).join("")
      : `<li class="empty">${kind === "saved" ? "No saved jobs yet. Tap ☆ Save on any job." : "Nothing marked as applied yet. Tap “Applied?” after you apply — it stays private in this browser."}</li>`;
    $("#result-count").textContent = `${list.length} ${kind} job${list.length === 1 ? "" : "s"} (stored only in this browser)`;
    $("#load-more").hidden = true;
  }

  function setTab(t) {
    tab = t;
    $$(".tab").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
    $("#applied-tools").hidden = t !== "applied";
    $(".toolbar-right").hidden = t !== "all";
    if (t === "all") search(); else renderLocal(t);
  }

  function updateCounts() {
    const s = Object.keys(saved).length, a = Object.keys(applied).length;
    $("#saved-count").textContent = s ? `(${s})` : "";
    $("#applied-count").textContent = a ? `(${a})` : "";
  }

  function renderActiveTags() {
    $("#active-tags").innerHTML = tags.map((t) =>
      `<button type="button" class="tag" aria-pressed="true" data-tag="${esc(t)}" title="Remove filter">#${esc(t)} ✕</button>`).join("");
    $$("#tag-cloud .tag").forEach((b) => b.setAttribute("aria-pressed", String(tags.includes(b.dataset.tag))));
  }

  function toggleTag(t) {
    tags = tags.includes(t) ? tags.filter((x) => x !== t) : [...tags, t];
    if (tab !== "all") setTab("all"); else search();
  }

  function updateRss(qs) {
    const a = $("#rss-link");
    a.href = DEMO ? "#" : `${C.SUPABASE_URL.replace(/\/$/, "")}/functions/v1/rss${qs ? `?${qs}` : ""}`;
  }

  function ensureCityOption(city) {
    if (city && !$$("#city option").some((o) => o.value === city)) {
      $("#city").insertAdjacentHTML("beforeend", `<option value="${esc(city)}">${esc(city)}</option>`);
    }
  }

  // ---------------------------------------------------------------- job actions
  function snapshot(j) { return { ...j }; }

  function onJobClick(e) {
    const tagBtn = e.target.closest("[data-tag]");
    if (tagBtn) { toggleTag(tagBtn.dataset.tag); return; }
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const li = btn.closest(".job");
    const j = current.get(li.dataset.id);
    if (!j) return;
    const act = btn.dataset.act;

    if (act === "toggle") {
      const box = $(".job-details", li);
      const open = box.hidden;
      if (open && !box.innerHTML) box.innerHTML = detailsHtml(j);
      box.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      if (open) { markSeen(j.id); li.classList.add("seen"); }
    } else if (act === "apply") {
      markSeen(j.id); li.classList.add("seen");
    } else if (act === "save") {
      if (saved[j.id]) delete saved[j.id]; else saved[j.id] = { job: snapshot(j), at: new Date().toISOString() };
      store.set("saved", saved);
      btn.setAttribute("aria-pressed", String(!!saved[j.id]));
      btn.textContent = saved[j.id] ? "★ Saved" : "☆ Save";
      updateCounts();
      if (tab === "saved") renderLocal("saved");
    } else if (act === "applied") {
      if (applied[j.id]) delete applied[j.id]; else applied[j.id] = { job: snapshot(j), at: new Date().toISOString() };
      store.set("applied", applied);
      btn.setAttribute("aria-pressed", String(!!applied[j.id]));
      btn.textContent = applied[j.id] ? "✓ Applied" : "Applied?";
      markSeen(j.id); li.classList.add("seen");
      updateCounts();
      maybeNudge();
      if (tab === "applied") renderLocal("applied");
    } else if (act === "hide") {
      if (!hiddenCompanies.includes(j.company)) hiddenCompanies.push(j.company);
      store.set("hiddenCompanies", hiddenCompanies);
      $$(".job").forEach((el) => { if (current.get(el.dataset.id)?.company === j.company && tab === "all") el.remove(); });
      $("#result-count").textContent = `Hidden all jobs from ${j.company}. Undo under “My hidden companies & words”.`;
    }
  }

  // ---------------------------------------------------------------- support / nudge / hired
  function maybeNudge() {
    const n = Object.keys(applied).length;
    if (n < (C.NUDGE_AFTER_APPLIED || 5) || store.get("nudged", false)) return;
    store.set("nudged", true);
    const box = $("#nudge");
    box.innerHTML = `<p>🙌 You've tracked ${n} applications here — glad it's helping! This site runs on coffee.</p>
      <span><a class="btn support small" href="${esc(C.KOFI_URL)}" target="_blank" rel="noopener">☕ Support</a>
      <button type="button" class="btn ghost small" id="nudge-close">Not now</button></span>`;
    box.hidden = false;
    $("#nudge-close").onclick = () => { box.hidden = true; };
  }

  function costsHtml() {
    const rows = (C.COSTS || []).map((c) => `<tr><td>${esc(c.label)}</td><td>€${Number(c.eur).toFixed(2)}</td></tr>`).join("");
    const sum = (C.COSTS || []).reduce((s, c) => s + Number(c.eur), 0);
    const goal = C.MONTHLY_GOAL_EUR || 0, raised = C.RAISED_THIS_MONTH_EUR || 0;
    const pct = goal ? Math.min(100, Math.round((raised / goal) * 100)) : 0;
    return `<table><tbody>${rows}<tr><td><b>Monthly running costs</b></td><td><b>€${sum.toFixed(2)}</b></td></tr></tbody></table>
      ${goal ? `<div class="goal"><div class="goal-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${goal}" aria-valuenow="${raised}"><span style="width:${pct}%"></span></div>
      <p>€${raised} of €${goal} this month — covers costs plus better job matching (AI tagging, more sources).</p></div>` : ""}`;
  }

  async function loadStats() {
    try {
      const s = await rpc("site_stats");
      $("#stats").innerHTML = `<b>${s.active.toLocaleString("en")}</b> English-friendly jobs · <b>${s.added_today.toLocaleString("en")}</b> added today`
        + (s.hired ? ` · <b>${s.hired.toLocaleString("en")}</b> people hired 🎉` : "");
    } catch { $("#stats").textContent = ""; }
  }

  async function loadFacets() {
    try {
      const f = await rpc("facets", { p_limit: 30 });
      const sel = $("#city").value;
      f.cities.forEach((c) => ensureCityOption(c.city));
      $("#city").value = sel;
      $("#tag-cloud").innerHTML = f.tags.map((t) =>
        `<button type="button" class="tag" data-tag="${esc(t.tag)}" aria-pressed="${tags.includes(t.tag)}">#${esc(t.tag)}<span class="n">${t.count}</span></button>`).join("");
    } catch (e) { console.error(e); }
  }

  // ---------------------------------------------------------------- prefs dialog
  function renderPrefs() {
    $("#hidden-companies").innerHTML = hiddenCompanies.length
      ? hiddenCompanies.map((c, i) => `<li>${esc(c)} <button type="button" data-unhide="${i}" aria-label="Show ${esc(c)} again">✕</button></li>`).join("")
      : `<li class="muted">None yet — use 🚫 on a job card.</li>`;
    $("#exclude-words").value = excludeWords.join(", ");
  }

  function exportCsv() {
    const rows = Object.values(applied).sort((a, b) => new Date(a.at) - new Date(b.at));
    const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [["Applied on", "Title", "Company", "City", "Salary", "German", "Link"].map(cell).join(",")]
      .concat(rows.map(({ job: j, at }) => [at.slice(0, 10), j.title, j.company, j.city, salaryText(j) || "", j.german_level, j.url].map(cell).join(",")))
      .join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = `my-applications-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---------------------------------------------------------------- init
  function init() {
    document.title = `${C.SITE_NAME} — German level, salary & visa info up front`;
    $("#brand").textContent = C.SITE_NAME;
    $("#owner-note").textContent = C.OWNER_NOTE || "";
    if (C.SPONSOR) $("#sponsor-slot").innerHTML =
      `<a class="sponsor" href="${esc(C.SPONSOR.url)}" rel="sponsored noopener" target="_blank">
         <span class="sponsor-label">Sponsored</span><b>${esc(C.SPONSOR.label)}</b><span>${esc(C.SPONSOR.text)}</span></a>`;
    $("#cost-box").innerHTML = costsHtml();
    $("#support-costs").innerHTML = costsHtml();
    $$("[data-kofi]").forEach((a) => { a.href = C.KOFI_URL; });
    $$("[data-supporters]").forEach((a) => { a.href = C.SUPPORTERS_URL || C.KOFI_URL; });
    $("#glossary-list").innerHTML = Object.entries(GLOSSARY).map(([t, d]) => `<dt>${esc(t)}</dt><dd>${esc(d)}</dd>`).join("");
    if (!window.matchMedia("(min-width: 861px)").matches) $("#more-filters").open = false;
    if (DEMO) $(".quick").insertAdjacentHTML("afterend",
      `<p class="demo-note">Demo mode with sample jobs — add your Supabase URL and anon key in <code>config.js</code> to go live.</p>`);

    writeFilters(filtersFromQuery());
    updateCounts();

    // search triggers
    $("#search-form").addEventListener("submit", (e) => { e.preventDefault(); setTab("all"); });
    let t;
    $("#q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => search(), 350); });
    $$(".filters select, .filters input, #city, #sort, #f-salary, #f-visa, #f-direct").forEach((el) =>
      el.addEventListener("change", () => { syncQuickChips(); search(); }));
    $("#f-nogerman").addEventListener("change", (e) => { setChecked("german", e.target.checked ? NO_GERMAN : []); search(); });
    $("#f-remote").addEventListener("change", (e) => { setChecked("remote", e.target.checked ? REMOTE : []); search(); });
    $("#reset-filters").addEventListener("click", () => { writeFilters({}); search(); });
    $("#load-more").addEventListener("click", () => search({ append: true }));
    $("#results").addEventListener("click", onJobClick);
    $("#tag-cloud").addEventListener("click", (e) => { const b = e.target.closest("[data-tag]"); if (b) toggleTag(b.dataset.tag); });
    $("#active-tags").addEventListener("click", (e) => { const b = e.target.closest("[data-tag]"); if (b) toggleTag(b.dataset.tag); });
    $$(".tab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
    $("#export-csv").addEventListener("click", exportCsv);
    $("#rss-link").addEventListener("click", (e) => { if (DEMO) { e.preventDefault(); alert("The RSS feed works once the database is connected."); } });

    // dialogs
    $$("[data-open]").forEach((b) => b.addEventListener("click", (e) => {
      e.preventDefault();
      const d = document.getElementById(b.dataset.open);
      if (d.id === "prefs-dialog") renderPrefs();
      if (d.id === "hired-dialog" && store.get("hired", false)) { $("#hired-ask").hidden = true; $("#hired-thanks").hidden = false; }
      d.showModal();
    }));
    $$("dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close(); })); // click backdrop

    $("#hidden-companies").addEventListener("click", (e) => {
      const b = e.target.closest("[data-unhide]"); if (!b) return;
      hiddenCompanies.splice(Number(b.dataset.unhide), 1);
      store.set("hiddenCompanies", hiddenCompanies); renderPrefs(); search();
    });
    $("#save-prefs").addEventListener("click", () => {
      excludeWords = $("#exclude-words").value.split(",").map((s) => s.trim()).filter(Boolean);
      store.set("excludeWords", excludeWords);
      $("#prefs-dialog").close(); search();
    });
    $("#clear-data").addEventListener("click", () => {
      if (!confirm("Delete your saved jobs, applications, hidden companies and settings from this browser?")) return;
      try { Object.keys(localStorage).filter((k) => k.startsWith("ejg.")).forEach((k) => localStorage.removeItem(k)); } catch { /* ignore */ }
      location.href = location.pathname;
    });

    $("#hired-yes").addEventListener("click", async () => {
      store.set("hired", true);
      $("#hired-ask").hidden = true; $("#hired-thanks").hidden = false;
      try { await rpc("record_hire"); loadStats(); } catch { /* counter is best-effort */ }
    });
    $("#share-site").addEventListener("click", async (e) => {
      const url = location.origin + location.pathname;
      const text = "English-friendly jobs in Germany, with German level, salary and visa info up front:";
      if (navigator.share) { try { await navigator.share({ title: C.SITE_NAME, text, url }); } catch { /* cancelled */ } }
      else { try { await navigator.clipboard.writeText(url); e.target.textContent = "Link copied ✓"; } catch { prompt("Copy this link:", url); } }
    });

    $("#theme-toggle").addEventListener("click", () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("ejg.theme", root.dataset.theme); } catch { /* ignore */ }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); $("#q").focus(); }
    });

    loadStats();
    loadFacets();
    search();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
