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

  // ---------------------------------------------------------------- "Updated 2 h ago · next in 03:42:10"
  const RUN_HOURS_UTC = [0, 6, 12, 18], RUN_MINUTE = 17; // schedule of .github/workflows/ingest.yml
  let lastUpdate = null;

  async function loadFreshness() {
    if (DEMO) return;
    try {
      const [row] = await restGet("jobs?select=last_seen_at&is_active=eq.true&order=last_seen_at.desc&limit=1");
      if (!row) return;
      lastUpdate = new Date(row.last_seen_at);
      tickFreshness();
      setInterval(tickFreshness, 1000);
    } catch { /* the pill just stays hidden */ }
  }

  function nextRun(now) {
    const d = new Date(now);
    for (let day = 0; day < 2; day++) {
      for (const h of RUN_HOURS_UTC) {
        const t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + day, h, RUN_MINUTE);
        if (t > now) return t;
      }
    }
    return now;
  }

  function tickFreshness() {
    const now = Date.now(), el = $("#updated-pill");
    const mins = Math.max(0, Math.floor((now - lastUpdate) / 60000));
    const ago = mins < 1 ? "just now" : mins < 60 ? `${mins} min ago` : `${Math.floor(mins / 60)} h ${mins % 60} min ago`;
    const left = Math.max(0, Math.floor((nextRun(now) - now) / 1000));
    const two = (n) => String(n).padStart(2, "0");
    const clock = `${two(Math.floor(left / 3600))}:${two(Math.floor((left % 3600) / 60))}:${two(left % 60)}`;
    el.innerHTML = `<span class="live-dot" aria-hidden="true"></span>Updated ${ago}<span class="next"> · next in ${clock}</span>`;
    el.title = `Jobs were last refreshed ${lastUpdate.toLocaleString()}. New jobs are fetched every 6 hours — next in ${clock}.`;
    el.hidden = false;
  }

  // ---------------------------------------------------------------- anonymous event counts
  // GoatCounter (cookieless). If it's blocked or not loaded, this does nothing.
  function track(path, title = "") {
    try {
      if (window.goatcounter && window.goatcounter.count) window.goatcounter.count({ path, title: String(title).slice(0, 120), event: true });
    } catch { /* analytics must never break the site */ }
  }
  let lastTrackedQuery = "";

  // Anonymous popularity counts per job (no visitor data is sent — only the job id and "open"/"apply").
  // Each browser counts once per job, kind and day, so reloading doesn't inflate the numbers.
  function countJobEvent(id, kind) {
    if (DEMO || !id) return;
    const today = new Date().toISOString().slice(0, 10);
    const seenEvents = store.get("events", {});
    if (seenEvents[`${kind}:${id}`] === today) return;
    for (const [k, day] of Object.entries(seenEvents)) if (day !== today) delete seenEvents[k]; // keep it small
    seenEvents[`${kind}:${id}`] = today;
    store.set("events", seenEvents);
    rpc("record_job_event", { p_id: id, p_kind: kind }).catch(() => {});
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
  let descFor = null; // the keyword the visitor also wants matched in job descriptions

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
      // Keyword in descriptions too? Only after the visitor asked for it, and only for that keyword.
      desc: descFor !== null && descFor === $("#q").value.trim(),
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
    descFor = f.desc ? (f.q || "") : null;
    syncQuickChips();
  }

  function syncQuickChips() {
    $("#f-nogerman").checked = sameSet(checked("german"), NO_GERMAN);
    $("#f-remote").checked = sameSet(checked("remote"), REMOTE);
  }

  // URL <-> filters (so searches can be bookmarked and shared)
  const LIST_KEYS = ["tags", "german", "remote", "seniority"];
  const BOOL_KEYS = ["salary", "visa", "reloc", "direct", "desc"];
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
      if (k === "job" || k === "page") continue; // popup / page number, not filters
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
      p_scope: f.desc ? "all" : "title",
    };
  }

  // ---------------------------------------------------------------- rendering helpers
  const GERMAN_BADGE = {
    not_required: ["ok", "No German needed"],
    nice_to_have: ["info", "German: nice to have"],
    not_mentioned: ["", "German: not mentioned"],
    required: ["bad", "German required"],
  };
  const REMOTE_LABEL = { remote_de: "Remote (DE)", remote_eu: "Remote (EU)", hybrid: "Hybrid", onsite: "On-site", unknown: "" };
  const SENIORITY_LABEL = { intern: "Intern / student", junior: "Junior", mid: "Mid-level", senior: "Senior", lead: "Lead", unspecified: "Not specified" };

  const k = (n) => (n >= 1000 ? `€${Math.round(n / 1000)}k` : `€${n}`);
  // A salary no student job pays (old rows parsed from funding amounts) counts as "not listed".
  const hasSalary = (j) => !!j.salary_min && !(j.seniority === "intern" && j.salary_min > 60000) && j.salary_min <= 300000;
  function salaryText(j) {
    if (!hasSalary(j)) return null;
    return j.salary_max && j.salary_max !== j.salary_min ? `${k(j.salary_min)}–${k(j.salary_max).slice(1)}` : k(j.salary_min);
  }
  function blueCard(j) {
    const BC = C.BLUE_CARD;
    const lo = j.salary_min, hi = j.salary_max ?? j.salary_min;
    if (!hasSalary(j)) return null;
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
    if ((j.popularity || 0) >= 6) out.unshift(`<span class="badge popular" title="Many people opened or applied to this job in the last 14 days">Popular</span>`);
    const bc = blueCard(j);
    if (bc) out.push(`<span class="badge ${bc[0]}" title="${esc(bc[2])}">${bc[1]}</span>`);
    if (REMOTE_LABEL[j.remote_type]) out.push(`<span class="badge">${REMOTE_LABEL[j.remote_type]}</span>`);
    if (j.visa_sponsorship) out.push(`<span class="badge ok">Visa sponsorship</span>`);
    if (j.relocation) out.push(`<span class="badge ok">Relocation support</span>`);
    if (j.is_agency) out.push(`<span class="badge warn" title="Posted by a recruiting agency, not the employer">Recruiting agency</span>`);
    if (j.repost_count > 0) out.push(`<span class="badge warn" title="This job disappeared and came back — it may be hard to fill or an evergreen posting">Reposted ×${j.repost_count}</span>`);
    (j.job_types || []).slice(0, 2).forEach((t) => out.push(`<span class="badge">${glossaryHtml(t)}</span>`));
    const titleTerm = Object.keys(GLOSSARY).find((g) => j.title.toLowerCase().includes(g) && g !== "m/w/d");
    if (titleTerm) out.push(`<span class="badge"><abbr title="${esc(GLOSSARY[titleTerm])}">What is "${esc(titleTerm)}"?</abbr></span>`);
    // Hints from the daily insights job: warnings and positives on the card, the rest in the details.
    hints(j).filter((h) => h.l !== "info").forEach((h) =>
      out.push(`<span class="badge ${h.l === "warn" ? "warn" : "ok"} hint" title="${esc(h.t)}">${esc(plain(h.s))}</span>`));
    return out.join("");
  }

  // ---------------------------------------------------------------- insights (similar jobs, hints)
  const hints = (j) => ((j.insights && j.insights.hints) || [])
    .filter((h) => hasSalary(j) || !/^salary_/.test(h.k)); // no salary talk for jobs without a stated salary
  const plain = (s) => String(s || "").replace(/^[^\p{L}\p{N}]+\s*/u, ""); // "⚠ Check salary" → "Check salary"
  const pct = (x) => `${Math.round(x * 100)}%`;

  const midSalary = (j) => (hasSalary(j) ? (j.salary_min + (j.salary_max || j.salary_min)) / 2 : null);

  // Warnings and positives from the daily check, shown above the description.
  function jobCheckHtml(j) {
    const list = hints(j);
    if (!list.length) return "";
    const label = { warn: "Check", good: "Plus", info: "Note" };
    return `<section class="jd-card check-card">
        <h3>Job check</h3>
        <ul class="check-list">${list.map((h) => `<li class="${h.l}"><span class="check-tag">${label[h.l]}</span><span>${esc(h.t)}</span></li>`).join("")}</ul>
      </section>`;
  }

  function salaryCardHtml(j) {
    const p = j.insights && j.insights.peers;
    const s = p && p.salary, v = midSalary(j);
    // Only when the employer states a salary: never show estimates for jobs that don't.
    if (!v || !s) return "";
    const lo = Math.min(s.p25, v ?? s.p25) * 0.8, hi = Math.max(s.p75, v ?? s.p75) * 1.15;
    const x = (n) => `${Math.max(0, Math.min(100, ((n - lo) / (hi - lo)) * 100)).toFixed(1)}%`;
    let verdict = "", tone = "";
    if (v) {
      const diff = Math.round(((v - s.p50) / s.p50) * 100);
      const flagged = hints(j).some((h) => /^salary_(error|high|low)$/.test(h.k));
      tone = flagged ? "warn" : v >= s.p75 ? "good" : "";
      verdict = `This job pays <b>${salaryText(j)}</b> — ${diff === 0 ? "right at the median" : `${Math.abs(diff)}% ${diff > 0 ? "above" : "below"} the median`}.`;
    }
    return `<section class="jd-card sal-card">
        <h3>Salary benchmark</h3>
        <p class="card-sub">${s.n} similar jobs at other companies that list a salary</p>
        <div class="sal-figures">
          <div><span>Median</span><b>${k(s.p50)}</b></div>
          <div><span>Typical range</span><b>${k(s.p25)}–${k(s.p75).slice(1)}</b></div>
        </div>
        <div class="sal-chart" role="img" aria-label="Typical salary ${k(s.p25)} to ${k(s.p75)}, median ${k(s.p50)}${v ? `, this job ${k(v)}` : ""}">
          <div class="sal-track"><span class="sal-band" style="left:${x(s.p25)};right:calc(100% - ${x(s.p75)})"></span>
            <span class="sal-median" style="left:${x(s.p50)}"></span>
            ${v ? `<span class="sal-job" style="left:${x(v)}"><em>This job</em></span>` : ""}</div>
          <div class="sal-axis"><span style="left:${x(s.p25)}">${k(s.p25)}</span><span style="left:${x(s.p75)}">${k(s.p75)}</span></div>
        </div>
        <p class="sal-verdict ${tone}">${verdict}</p>
      </section>`;
  }

  function compareCardHtml(j) {
    const p = j.insights && j.insights.peers;
    if (!p || !p.n) return "";
    const [gc, gl] = GERMAN_BADGE[j.german_level] || GERMAN_BADGE.not_mentioned;
    // Each row: what THIS job says first, then how common it is among similar jobs.
    const rows = [
      { label: "German", mine: gl.replace(/^German:\s*/, "").replace(/^./, (c) => c.toUpperCase()),
        tone: gc === "ok" ? "good" : gc === "bad" ? "warn" : "", share: p.german_req, peer: "of similar jobs require German" },
      { label: "Visa sponsorship", mine: j.visa_sponsorship ? "Offered" : "Not mentioned", tone: j.visa_sponsorship ? "good" : "",
        share: p.visa, peer: "of similar jobs mention it" },
    ];
    const row = (r) => `<li>
        <div class="cmp-top"><span>${r.label}</span><span class="pill ${r.tone}">This job: ${esc(r.mine)}</span></div>
        <div class="cmp-meter"><span style="width:${Math.max(2, r.share * 100)}%"></span></div>
        <p class="cmp-peer"><b>${pct(r.share)}</b> ${r.peer}</p></li>`;
    const years = p.years != null ? `<li>
        <div class="cmp-top"><span>Experience</span><span class="pill ${j.years_experience && j.years_experience >= p.years + 4 ? "warn" : ""}">This job: ${j.years_experience ? `${j.years_experience}+ years` : "Not specified"}</span></div>
        <p class="cmp-peer">Similar jobs usually ask for <b>${Math.round(p.years)}+ years</b></p></li>` : "";
    return `<section class="jd-card cmp-card">
        <h3>How this job compares</h3>
        <p class="card-sub">With ${p.n} similar jobs at other companies</p>
        <ul class="cmp-list">${rows.map(row).join("")}${years}</ul>
        <p class="tiny muted">Automatic comparison of the job texts. It can be wrong — always read the original.</p>
      </section>`;
  }

  function similarCardHtml(j) {
    const ids = j.insights && j.insights.similar;
    if (!ids || !ids.length || DEMO) return "";
    return `<section class="jd-card similar" data-ids="${esc(ids.join(","))}">
        <h3>Similar jobs at other companies</h3><p class="small muted">Loading…</p></section>`;
  }

  async function loadSimilar(box) {
    const el = $(".similar", box);
    if (!el || el.dataset.loaded) return;
    el.dataset.loaded = "1";
    try {
      const items = await rpc("jobs_by_ids", { p_ids: el.dataset.ids.split(",") });
      if (!items.length) { el.remove(); return; }
      el.innerHTML = `<h3>Similar jobs at other companies</h3><ul class="similar-list">${items.map((s) => `
          <li>${logoHtml(s.company, "logo-xs")}<div><a href="${esc(jobUrl(s.id))}" data-similar="${esc(s.id)}">${esc(s.title)}</a>
          <span class="muted">${esc(s.company)} · ${esc(s.city || "Germany")}${salaryText(s) ? ` · ${salaryText(s)}` : ""}</span></div></li>`).join("")}</ul>`;
    } catch (e) {
      el.remove();
    }
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

  // ---------------------------------------------------------------- companies & logos
  // Same key as co_key() in build/build_site.py, so "Trade Republic Bank GmbH" finds "Trade Republic".
  const LEGAL = new Set(["gmbh", "ag", "se", "kg", "kgaa", "co", "inc", "ltd", "llc", "plc", "bv", "nv", "sa", "sas",
    "oy", "ab", "ug", "haftungsbeschrankt", "mbh", "group", "holding", "the"]);
  const coKey = (name) => (name || "").normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase()
    .split(/[^a-z0-9]+/).filter((t) => t && !LEGAL.has(t)).join("");
  let companies = {};
  const companyInfo = (name) => companies[coKey(name)] || null;

  function logoHtml(name, cls = "") {
    const c = companyInfo(name);
    if (c && c.l) return `<img class="logo ${cls}" src="${esc(c.l)}" alt="" loading="lazy" data-name="${esc(name)}">`;
    const words = (name || "?").replace(/\(.*?\)/g, "").trim().split(/\s+/);
    const initials = (words[0][0] + (words[1] ? words[1][0] : words[0][1] || "")).toUpperCase();
    let h = 0;
    for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) % 360;
    return `<span class="logo mono ${cls}" style="--h:${h}" aria-hidden="true">${esc(initials)}</span>`;
  }

  // ---------------------------------------------------------------- Stellenly Hiring Score (computed by the build)
  const SCORE_WEIGHTS = { salary: 20, language: 25, visa: 15, activity: 15, freshness: 10, reposts: 15 };
  const grade = (p) => (p >= 85 ? "Excellent" : p >= 70 ? "Very good" : p >= 55 ? "Good" : p >= 40 ? "Fair" : "Limited");
  const starsHtml = (points, cls = "") => `<span class="stars ${cls}" role="img" aria-label="${(points / 20).toFixed(1)} out of 5 stars">
      <span class="stars-fill" style="width:${Math.round(points / 10) * 10}%">★★★★★</span>★★★★★</span>`;
  const scoreOf = (company) => (companyInfo(company) || {}).sc || null;

  function scoreChip(j) {
    const sc = scoreOf(j.company);
    return sc ? `<span class="score-chip inline" title="Stellenly Hiring Score ${sc.t}/100 — based on this company's job postings">★ ${(sc.t / 20).toFixed(1)}</span>` : "";
  }

  function scoreCardHtml(j) {
    const sc = scoreOf(j.company);
    if (!sc) return "";
    const rows = sc.f.map(([, label, p, text]) => `<li><div class="sc-row"><span>${esc(label)}</span>${starsHtml(p, "sm")}<b>${p}</b></div>
        <p>${esc(text)}</p></li>`).join("");
    const weights = sc.f.map(([key, label]) => `<li><b>${esc(label)}</b> — ${SCORE_WEIGHTS[key]}%</li>`).join("");
    return `<section class="score-card">
        <div class="sc-top">
          <div><p class="sc-kicker">Stellenly Hiring Score</p>
            <div class="sc-total"><b>${(sc.t / 20).toFixed(1)}</b>${starsHtml(sc.t)}</div>
            <p class="sc-grade">${grade(sc.t)} · ${sc.t}/100 points · based on ${sc.n} open jobs</p></div>
          <button type="button" class="sc-help" popovertarget="jd-score-help">ⓘ How we calculate this</button>
        </div>
        <ul class="sc-list">${rows}</ul>
        <div popover id="jd-score-help" class="sc-pop">
          <h4>How the Hiring Score works</h4>
          <p>It rates how ${esc(j.company)} hires — based only on its current job postings on Stellenly, <b>not on employee
          reviews</b>. Each factor gives 0–100 points; the total is their weighted average (100 points = 5 stars):</p>
          <ul>${weights}</ul>
          <p class="muted small">Salary: full points when 60%+ of jobs show a salary · English: "German not needed" counts
          fully, "not mentioned" 60% · Visa: full points at 50%+ · Activity: full points at 5+ new jobs in 30 days ·
          Freshness: full points when jobs are under 2 weeks old · Stable: fewer reposts score higher. Needs at least 3
          open jobs; updated daily.</p>
        </div>
      </section>`;
  }

  // "23 views · 5 applied" — anonymous all-time counts from record_job_event (no visitor data).
  function clicksBadge(j) {
    const views = j.views || 0, applies = j.apply_clicks || 0;
    if (!views && !applies) return "";
    const n = (x) => x.toLocaleString("en");
    const parts = [`${n(views)} view${views === 1 ? "" : "s"}`];
    if (applies) parts.push(`${n(applies)} applied`);
    return `<span class="clicks-badge" title="How often people opened this job and clicked Apply on Stellenly">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2"/></svg>
        ${parts.join(" · ")}</span>`;
  }

  const jobUrl = (id) => { const p = new URLSearchParams(location.search); p.set("job", id); return `?${p}`; };
  const skillsOf = (j) => (j.insights && j.insights.skills) || [];

  function jobHtml(j) {
    const isSaved = !!saved[j.id], isApplied = !!applied[j.id];
    const sal = salaryText(j);
    const skills = skillsOf(j).slice(0, 4).map((s) => `<span class="skill${s.r ? "" : " nice"}">${esc(s.n)}</span>`).join("");
    return `
    <li class="job${seen.has(j.id) ? " seen" : ""}" data-id="${esc(j.id)}">
      ${logoHtml(j.company, "job-logo")}
      <div class="job-main">
        <h3 class="job-title"><a href="${esc(jobUrl(j.id))}" data-act="open">${esc(j.title)}</a></h3>
        <div class="job-meta"><span class="company">${esc(j.company)}${scoreChip(j)}</span><span>${esc(j.city || j.location || "Germany")}</span>${j.posted_at ? `<span>${ago(j.posted_at)}</span>` : ""}${j.match === "text" ? `<span class="match-note" title="Your search word appears only in the job description, not in the title">mentioned in description</span>` : ""}</div>
        <div class="badges">${badges(j)}</div>
        ${skills ? `<div class="skills-row">${skills}</div>` : ""}
      </div>
      <div class="job-side">
        ${sal ? `<div class="job-salary">${sal}<small>/ year</small></div>` : `<div class="job-salary none">Salary not listed</div>`}
        ${clicksBadge(j)}
        <div class="job-actions">
          <button type="button" class="btn ghost" data-act="save" aria-pressed="${isSaved}" title="Save for later">${isSaved ? "★ Saved" : "☆ Save"}</button>
          <button type="button" class="btn ghost" data-act="applied" aria-pressed="${isApplied}" title="Mark as applied">${isApplied ? "✓ Applied" : "Applied?"}</button>
          <button type="button" class="btn ghost" data-act="hide" title="Hide all jobs from this company" aria-label="Hide this company">🚫</button>
        </div>
      </div>
    </li>`;
  }

  // ---------------------------------------------------------------- job popup (?job=<id>)
  const DETAIL_COLS = "id,url,title,company,location,city,remote_type,description,tags,job_types,german_level," +
    "visa_sponsorship,relocation,salary_min,salary_max,years_experience,seniority,is_agency,posted_at,first_seen_at," +
    "repost_count,insights";

  async function restGet(path) {
    const res = await fetch(`${C.SUPABASE_URL.replace(/\/$/, "")}/rest/v1/${path}`,
      { headers: { apikey: C.SUPABASE_ANON_KEY, Authorization: `Bearer ${C.SUPABASE_ANON_KEY}` } });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res.json();
  }

  // Job text arrives as plain text with line breaks: turn bullets into lists and short "Heading:" lines into headings.
  function descHtml(text) {
    if (/<\/?[a-z][^>]*>|&[a-z]+;|&#\d+;/i.test(text || "")) {
      // Leftover HTML from a source: keep line structure, drop the markup.
      const box = document.createElement("textarea");
      box.innerHTML = (text || "").replace(/<\/(p|div|li|h\d|tr)>|<br\s*\/?>/gi, "\n").replace(/<li[^>]*>/gi, "\n• ").replace(/<[^>]+>/g, " ");
      text = box.value.replace(/[ \t ]+/g, " ");
    }
    text = (text || "").replace(/^[ \t]*[•·▪][ \t]*\n\s*/gm, "• "); // "<li><p>…" leaves the bullet on its own line
    // Job-board promo lines ("Find more English Speaking Jobs in Germany on Arbeitnow").
    text = text.replace(/(?:Find\s+(?:more\s+)?)?(?:English\s+Speaking\s+)?Jobs\s+in\s+[A-Z][\w .'-]{1,40}?\s+on\s+Arbeitnow\.?/gi, "")
      .replace(/^[ \t]*[:,–-]?[ \t]*$\n?/gm, "");
    const out = [];
    let list = [];
    const flush = () => { if (list.length) out.push(`<ul>${list.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`); list = []; };
    for (const raw of (text || "").split(/\n+/)) {
      const line = raw.trim();
      if (!line) continue;
      const bullet = line.match(/^(?:[•*·▪–-]|\d{1,2}[.)])\s+(.*)$/);
      if (bullet) { list.push(bullet[1]); continue; }
      flush();
      if (line.length <= 70 && (/:$/.test(line) || !/[.!?]$/.test(line)) && line.split(" ").length <= 9) {
        out.push(`<h4>${esc(line.replace(/:$/, ""))}</h4>`);
      } else out.push(`<p>${esc(line)}</p>`);
    }
    flush();
    return out.join("");
  }

  function skillsHtml(j) {
    const skills = skillsOf(j);
    const missing = (j.insights && j.insights.peer_skills) || [];
    if (!skills.length && !missing.length) return "";
    const rows = skills.map((s) => `
      <li>
        <span class="sk-name">${esc(s.n)}${s.r ? "" : ' <span class="sk-nice">nice to have</span>'}</span>
        <span class="sk-bar" role="img" aria-label="Importance ${Math.round(s.w * 100)} of 100"><span style="width:${Math.max(8, s.w * 100)}%"></span></span>
        <span class="sk-peer">${s.p == null ? "" : `in ${pct(s.p)} of similar jobs`}</span>
      </li>`).join("");
    return `<section class="jd-card">
        <h3>Skills this job asks for</h3>
        <p class="small muted">Ranked by importance in the posting — the title and the requirements count most, “nice to have” least.</p>
        ${rows ? `<ul class="sk-list">${rows}</ul>` : ""}
        ${missing.length ? `<p class="small"><b>Often asked in similar jobs:</b> ${missing.map((m) => `<span class="skill ghost">${esc(m.n)} <small>${pct(m.p)}</small></span>`).join(" ")}</p>` : ""}
      </section>`;
  }

  function aiHtml(j) {
    const ai = j.insights && j.insights.ai;
    if (!ai) return "";
    return `<section class="jd-card jd-ai">
        <h3><span class="ai-dot" aria-hidden="true">✦</span> AI summary</h3>
        ${ai.summary ? `<p>${esc(ai.summary)}</p>` : ""}
        ${ai.tasks && ai.tasks.length ? `<p class="small"><b>What you'd do</b></p><ul>${ai.tasks.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
        ${ai.flags && ai.flags.length ? `<p class="small"><b>Worth double-checking</b></p><ul class="flags">${ai.flags.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
        <p class="tiny muted">Generated automatically from the posting. Always read the original.</p>
      </section>`;
  }

  function companyHtml(j) {
    const c = companyInfo(j.company);
    const kununu = `https://www.google.com/search?q=${encodeURIComponent(`${j.company} kununu`)}`;
    const facts = c ? [["Founded", c.f], ["Employees", c.z], ["HQ", c.h], ["Industry", c.i]].filter(([, v]) => v) : [];
    return `<section class="jd-card">
        <h3>About ${esc(j.company)}</h3>
        <div class="jd-co-head">${logoHtml(j.company, "logo-sm")}<div><b>${esc(c ? c.n : j.company)}</b>
          ${c && c.st ? ' <span class="badge new">Startup</span>' : ""}</div></div>
        ${c && c.d ? `<p>${esc(c.d)}</p>` : `<p class="muted small">No company profile yet.</p>`}
        ${facts.length ? `<dl class="co-facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
        <p class="jd-links">
          ${c && c.u ? `<a href="${esc(c.u)}">All jobs at ${esc(c.n)} →</a>` : ""}
          ${c && c.w ? `<a href="${esc(c.w)}" target="_blank" rel="noopener">Website ↗</a>` : ""}
          <a href="${kununu}" target="_blank" rel="noopener noreferrer nofollow">Employee reviews ↗</a>
        </p>
      </section>`;
  }

  function jobDialogHtml(j, loading) {
    const isSaved = !!saved[j.id], isApplied = !!applied[j.id];
    const sal = salaryText(j);
    const meta = [j.city || j.location || "Germany", REMOTE_LABEL[j.remote_type], j.posted_at && `Posted ${ago(j.posted_at)}`]
      .filter(Boolean).map((m) => `<span>${esc(m)}</span>`).join("");
    return `
      <header class="jd-head">
        ${logoHtml(j.company, "logo-lg")}
        <div class="jd-titles">
          <p class="jd-company">${esc(j.company)}</p>
          <h2 id="jd-title">${esc(j.title)}</h2>
          <p class="jd-meta">${meta}${sal ? `<span class="jd-salary">${sal} / year</span>` : ""}</p>
        </div>
        <button type="button" class="jd-close" data-jd="close" aria-label="Close">✕</button>
      </header>
      <div class="jd-actions">
        <a class="btn primary big" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer nofollow" data-jd="apply">Apply on original site ↗</a>
        <button type="button" class="btn" data-jd="save" aria-pressed="${isSaved}">${isSaved ? "★ Saved" : "☆ Save"}</button>
        <button type="button" class="btn" data-jd="applied" aria-pressed="${isApplied}">${isApplied ? "✓ Applied" : "Mark applied"}</button>
        <button type="button" class="btn ghost" data-jd="copy" title="Copy a link to this job">🔗 Copy link</button>
      </div>
      <div class="jd-body">
        <div class="jd-main">
          <div class="badges">${badges(j)}</div>
          ${aiHtml(j)}
          ${jobCheckHtml(j)}
          <section class="jd-card jd-desc">
            <h3>Job description</h3>
            ${loading ? `<p class="muted">Loading the full description…</p>` : (j.description ? descHtml(j.description) : `<p>${esc(j.snippet || "")}</p>`)}
            <div class="job-tags">${(j.tags || []).map((t) => `<button type="button" class="tag" data-tag="${esc(t)}">#${esc(t)}</button>`).join("")}</div>
          </section>
        </div>
        <aside class="jd-side">
          <section class="jd-card"><h3>At a glance</h3>${factsHtml(j)}</section>
          ${scoreCardHtml(j)}
          ${j.insights || loading ? "" : `<section class="jd-card pending-card"><h3>Analysis coming soon</h3>
            <p class="small muted">This job is new. Skills, salary benchmark and similar jobs are added automatically
            within a few hours.</p></section>`}
          ${salaryCardHtml(j)}
          ${compareCardHtml(j)}
          ${skillsHtml(j)}
          ${companyHtml(j)}
          ${similarCardHtml(j)}
        </aside>
      </div>`;
  }

  let openId = null;
  async function openJob(idOrJob, { push = true } = {}) {
    const id = typeof idOrJob === "string" ? idOrJob : idOrJob.id;
    let j = typeof idOrJob === "string" ? current.get(id) : idOrJob;
    const dlg = $("#job-dialog"), box = $("#jd");
    openId = id;
    if (push) history.pushState({ job: id }, "", jobUrl(id));
    box.innerHTML = j ? jobDialogHtml(j, !DEMO) : `<p class="muted jd-wait">Loading job…</p>`;
    if (!dlg.open) dlg.showModal();
    box.scrollTop = 0;
    markSeen(id);
    track("job-open", j ? j.company : id);
    countJobEvent(id, "open");
    $$(`.job[data-id="${CSS.escape(id)}"]`).forEach((li) => li.classList.add("seen"));
    if (DEMO) return;
    try {
      const [full] = await restGet(`jobs?id=eq.${encodeURIComponent(id)}&select=${DETAIL_COLS}`);
      if (openId !== id) return; // another job was opened meanwhile
      if (!full) { box.innerHTML = `<p class="jd-wait">This job is no longer online. <button class="btn" data-jd="close">Close</button></p>`; return; }
      j = withDevInsights({ ...(j || {}), ...full });
      current.set(id, j);
      box.innerHTML = jobDialogHtml(j, false);
      document.title = `${j.title} at ${j.company} — ${C.SITE_NAME}`;
      loadSimilar(box);
    } catch (e) {
      console.error(e);
      if (j) box.innerHTML = jobDialogHtml(j, false);
    }
  }

  function closeJob({ pop = false } = {}) {
    const dlg = $("#job-dialog");
    openId = null;
    if (dlg.open) dlg.close();
    document.title = `${C.SITE_NAME} — English-speaking jobs in Germany`;
    if (!pop) {
      const p = new URLSearchParams(location.search); p.delete("job");
      history.pushState(null, "", p.toString() ? `?${p}` : location.pathname);
    }
  }

  function onDialogClick(e) {
    const tagBtn = e.target.closest("[data-tag]");
    if (tagBtn) { closeJob(); toggleTag(tagBtn.dataset.tag); return; }
    const sim = e.target.closest("[data-similar]");
    if (sim) { e.preventDefault(); openJob(sim.dataset.similar); return; }
    const btn = e.target.closest("[data-jd]");
    if (!btn) return;
    const j = current.get(openId);
    const act = btn.dataset.jd;
    if (act !== "close") track(`popup-${act}`, j ? j.company : "");
    if (act === "apply") countJobEvent(openId, "apply");
    if (act === "close") closeJob();
    else if (act === "copy") {
      // The job's own page (built at deploy time) shares better: it has a proper title and preview.
      const link = j && !DEMO ? new URL(`job/${j.id}.html`, location.href).href : location.href;
      navigator.clipboard?.writeText(link).then(() => { btn.textContent = "✓ Link copied"; }, () => {});
    } else if (j && (act === "save" || act === "applied")) {
      toggleList(act, j);
      btn.setAttribute("aria-pressed", String(act === "save" ? !!saved[j.id] : !!applied[j.id]));
      btn.textContent = act === "save" ? (saved[j.id] ? "★ Saved" : "☆ Save") : (applied[j.id] ? "✓ Applied" : "Mark applied");
      $$(`.job[data-id="${CSS.escape(j.id)}"] [data-act="${act}"]`).forEach((b) => {
        b.setAttribute("aria-pressed", btn.getAttribute("aria-pressed"));
        b.textContent = act === "save" ? (saved[j.id] ? "★ Saved" : "☆ Save") : (applied[j.id] ? "✓ Applied" : "Applied?");
      });
    }
  }

  // Local preview only: config.js may point DEV_INSIGHTS_URL at an insights JSON produced by `insights.py --dry-run`.
  let devInsights = null;
  const withDevInsights = (j) => (devInsights && devInsights[j.id] ? { ...j, insights: devInsights[j.id] } : j);

  // ---------------------------------------------------------------- state & search
  let tab = "all";
  let offset = 0;
  let page = 1;
  let total = 0;
  let current = new Map();   // id -> job (jobs currently on screen)
  let reqId = 0;

  // One page of results at a time; ?page=N keeps the page in the URL (back button, sharing).
  async function search({ page: wanted = 1, scroll = false } = {}) {
    if (tab !== "all") return;
    const f = readFilters();
    const qs = filtersToQuery(f).toString();
    const params = new URLSearchParams(qs);
    if (wanted > 1) params.set("page", String(wanted));
    if (openId) params.set("job", openId); // keep the open job in the URL
    history.replaceState(history.state, "", params.toString() ? `?${params}` : location.pathname);
    updateRss(qs);
    renderActiveTags();
    page = wanted;
    offset = (page - 1) * PAGE;
    const my = ++reqId;
    $("#result-count").textContent = "Searching…";
    $("#results").classList.add("loading");
    try {
      const term = (f.q || "").trim().toLowerCase().slice(0, 60);
      if (page === 1 && term && term !== lastTrackedQuery) { lastTrackedQuery = term; track(`search/${term}`, "Search"); }
      const data = await rpc("search_jobs", rpcParams(f, offset));
      if (my !== reqId) return; // a newer search started
      total = data.total;
      const pages = Math.max(1, Math.ceil(total / PAGE));
      if (page > pages && total) return search({ page: pages, scroll });
      current.clear();
      const items = data.items.map(withDevInsights);
      items.forEach((j) => current.set(j.id, j));
      $("#results").innerHTML = items.length ? items.map(jobHtml).join("")
        : `<li class="empty">No jobs match these filters. Try another keyword, or remove a filter or a tag.</li>`;
      const from = total ? offset + 1 : 0, to = Math.min(offset + items.length, total);
      // A keyword matches titles, companies and skill tags; jobs that only mention it in the description
      // are offered separately ("pilot" must not list every job with "pilot projects" in its text).
      const q = (f.q || "").trim(), n = (x) => x.toLocaleString("en");
      const more = q && !f.desc ? (data.all_total ?? total) - total : 0;
      const plural = (x) => `job${x === 1 ? "" : "s"}`;
      const moreBtn = more > 0 ? ` <button type="button" class="link-btn" data-scope="all">Show ${n(more)} more ${plural(more)} that mention “${esc(q)}” in the description</button>` : "";
      $("#result-count").innerHTML = (!total
          ? (q ? "0 jobs" : "No jobs found")
          : `${n(from)}–${n(to)} of ${n(total)} ${plural(total)}${q && !f.desc ? ` with “${esc(q)}” in the title or skills` : ""}`)
        + (total ? moreBtn : "")
        + (f.desc && q ? ` <button type="button" class="link-btn" data-scope="title">Only jobs with “${esc(q)}” in the title or skills</button>` : "");
      if (!total && q) {  // a keyword nobody hires for: say so loudly, offer the description matches
        $("#results").innerHTML = `<li class="no-match" role="status"><b>No jobs have “${esc(q)}” in the title or skills.</b>
          <span>Try another keyword, or remove a filter.</span>${more > 0 ? `<button type="button" class="link-btn" data-scope="all">Show ${n(more)} ${plural(more)} that mention “${esc(q)}” in the description</button>` : ""}</li>`;
      }
      renderPager(pages);
      if (scroll) $(".results-col").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      console.error(e);
      if (my === reqId) $("#result-count").textContent = "Couldn't load jobs right now. Please try again in a minute.";
    } finally {
      if (my === reqId) $("#results").classList.remove("loading");
    }
  }

  // 1 … 4 5 [6] 7 8 … 42
  function renderPager(pages) {
    const nav = $("#pager");
    if (pages <= 1) { nav.innerHTML = ""; return; }
    const nums = new Set([1, pages, page - 2, page - 1, page, page + 1, page + 2].filter((n) => n >= 1 && n <= pages));
    const list = [...nums].sort((a, b) => a - b);
    let html = `<button type="button" class="pg" data-page="${page - 1}" ${page === 1 ? "disabled" : ""} aria-label="Previous page">‹ Prev</button>`;
    list.forEach((n, i) => {
      if (i && n - list[i - 1] > 1) html += `<span class="pg-gap" aria-hidden="true">…</span>`;
      html += `<button type="button" class="pg${n === page ? " current" : ""}" data-page="${n}" ${n === page ? 'aria-current="page"' : ""}>${n}</button>`;
    });
    html += `<button type="button" class="pg" data-page="${page + 1}" ${page === pages ? "disabled" : ""} aria-label="Next page">Next ›</button>`;
    nav.innerHTML = html;
  }

  function renderLocal(kind) {
    const map = kind === "saved" ? saved : applied;
    const list = Object.values(map).sort((a, b) => new Date(b.at) - new Date(a.at));
    current.clear();
    list.forEach((x) => current.set(x.job.id, x.job));
    $("#results").innerHTML = list.length ? list.map((x) => jobHtml(x.job)).join("")
      : `<li class="empty">${kind === "saved" ? "No saved jobs yet. Tap ☆ Save on any job." : "Nothing marked as applied yet. Tap “Applied?” after you apply — it stays private in this browser."}</li>`;
    $("#result-count").textContent = `${list.length} ${kind} job${list.length === 1 ? "" : "s"} (stored only in this browser)`;
    $("#pager").innerHTML = "";
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
  function snapshot(j) { const { description, ...rest } = j; return rest; } // keep localStorage small

  function toggleList(kind, j) {
    const map = kind === "save" ? saved : applied;
    if (map[j.id]) delete map[j.id]; else map[j.id] = { job: snapshot(j), at: new Date().toISOString() };
    store.set(kind === "save" ? "saved" : "applied", map);
    if (kind === "applied") { markSeen(j.id); maybeNudge(); }
    updateCounts();
    if (tab === (kind === "save" ? "saved" : "applied")) renderLocal(tab);
  }

  function onJobClick(e) {
    const tagBtn = e.target.closest("[data-tag]");
    if (tagBtn) { toggleTag(tagBtn.dataset.tag); return; }
    const card = e.target.closest(".job");
    if (card && !e.target.closest("[data-act], a, button") && current.get(card.dataset.id)) {
      openJob(current.get(card.dataset.id)); // the whole card is clickable
      return;
    }
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const li = btn.closest(".job");
    const j = current.get(li.dataset.id);
    if (!j) return;
    const act = btn.dataset.act;

    if (act === "open") {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return; // let "open in new tab" work
      e.preventDefault();
      openJob(j);
    } else if (act === "save") {
      toggleList("save", j);
      if (saved[j.id]) track("save", j.company);
      btn.setAttribute("aria-pressed", String(!!saved[j.id]));
      btn.textContent = saved[j.id] ? "★ Saved" : "☆ Save";
    } else if (act === "applied") {
      toggleList("applied", j);
      if (applied[j.id]) track("mark-applied", j.company);
      btn.setAttribute("aria-pressed", String(!!applied[j.id]));
      btn.textContent = applied[j.id] ? "✓ Applied" : "Applied?";
      li.classList.add("seen");
    } else if (act === "hide") {
      track("hide-company", j.company);
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
    const costs = C.COSTS || [];
    const eur = (n) => `€${Number(n).toFixed(n % 1 ? 2 : 0)}`;
    const rows = costs.map((c) => `<tr><td>${esc(c.label)}${c.note ? `<small>${esc(c.note)}</small>` : ""}</td>
        <td>${eur(c.now || 0)}</td><td>${eur(c.grow ?? c.now ?? 0)}</td></tr>`).join("");
    const now = costs.reduce((s, c) => s + Number(c.now || 0), 0);
    const grow = costs.reduce((s, c) => s + Number(c.grow ?? c.now ?? 0), 0);
    const hours = C.HOURS_PER_MONTH ? `<tr class="time"><td>Development, data checks &amp; guides<small>unpaid</small></td>
        <td colspan="2">~${C.HOURS_PER_MONTH} h / month</td></tr>` : "";
    const goal = C.MONTHLY_GOAL_EUR || 0, raised = C.RAISED_THIS_MONTH_EUR || 0;
    const pct = goal ? Math.min(100, Math.round((raised / goal) * 100)) : 0;
    return `<table class="cost-table"><thead><tr><th></th><th>Today</th><th>To keep growing</th></tr></thead>
      <tbody>${rows}${hours}</tbody>
      <tfoot><tr><td>Per month</td><td>${eur(now)}</td><td>${eur(grow)}</td></tr></tfoot></table>
      ${goal ? `<div class="goal"><div class="goal-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${goal}" aria-valuenow="${raised}"><span style="width:${pct}%"></span></div>
      <p><b>€${raised}</b> of €${goal} raised this month</p></div>` : ""}`;
  }

  let siteStats = null;
  async function loadStats() {
    try { siteStats = await rpc("site_stats"); } catch { siteStats = null; }
    renderStats();
  }

  function renderStats() {
    const s = siteStats;
    if (!s) { $("#stats").innerHTML = ""; return; }
    const n = (x) => x.toLocaleString("en");
    const employers = new Set(Object.values(companies).map((c) => c.n)).size;
    const items = [["Open roles", n(s.active)]];
    if (s.total) items.push(["Roles so far", n(s.total)]);
    if (employers) items.push(["Companies hiring", n(employers)]);
    // Right after a full re-import every job counts as "new"; only show the figure when it is meaningful.
    if (s.added_today && s.added_today < s.active * 0.4) items.push(["New in 24 hours", n(s.added_today)]);
    if (s.hired) items.push(["People hired", n(s.hired)]);
    items.push(["Refreshed", "every 6 h"]);
    $("#stats").innerHTML = items.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  }

  // Logos of well-known employers that currently have a profile (and a logo) on the site.
  const FEATURED = ["Celonis", "N26", "DeepL", "Trade Republic", "HelloFresh", "GetYourGuide", "SumUp", "Helsing",
    "Databricks", "Enpal", "Contentful", "Raisin", "Babbel", "Doctolib", "Flix", "Spotify"];
  function renderHiring() {
    const picks = FEATURED.map((name) => companyInfo(name)).filter((c) => c && c.l && c.u).slice(0, 6);
    $("#hiring-logos").innerHTML = picks.map((c) =>
      `<a href="${esc(c.u)}" title="${esc(c.n)}"><img src="${esc(c.l)}" alt="${esc(c.n)}" loading="lazy"><span>${esc(c.n)}</span></a>`).join("");
    $(".hiring-strip").hidden = !picks.length;
  }

  async function loadFacets() {
    try {
      const [f, german] = await Promise.all([
        rpc("facets", { p_limit: 60 }),
        fetch("german-cities.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
      ]);
      const sel = $("#city").value;
      // Only German cities in the dropdown (german-cities.json is written by the daily build).
      const ok = german ? new Set(german) : null;
      f.cities.filter((c) => !ok || ok.has(c.city)).slice(0, 30).forEach((c) => ensureCityOption(c.city));
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
    document.title = `${C.SITE_NAME} — English-speaking jobs in Germany`;
    $("#brand").textContent = C.SITE_NAME;
    $("#owner-note").innerHTML = `Built by ${C.OWNER_URL ? `<a href="${esc(C.OWNER_URL)}" rel="noopener">${esc(C.OWNER_NAME || "us")}</a>`
      : esc(C.OWNER_NAME || "us")} ${esc(C.OWNER_NOTE || "")}`;
    // Sponsor slot: one real sponsor / partner / ad offer, picked at random per visit.
    const sponsors = C.SPONSORS || (C.SPONSOR ? [C.SPONSOR] : []);
    if (sponsors.length) {
      const sp = sponsors[Math.floor(Math.random() * sponsors.length)];
      const label = { sponsor: "Sponsored", partner: "Partner", offer: "Advertise here" }[sp.kind] || "Sponsored";
      $("#sponsor-slot").innerHTML = `<a class="sponsor${sp.kind === "offer" ? " offer" : ""}" href="${esc(sp.url)}"
         rel="${sp.kind === "offer" ? "noopener" : "sponsored noopener"}" target="_blank" data-goatcounter-click="sponsor-${esc(sp.label)}">
         <span class="sponsor-label">${label}</span><b>${esc(sp.label)}</b><span>${esc(sp.text)}</span></a>`;
    }
    $("#cost-box").innerHTML = costsHtml();
    $("#support-costs").innerHTML = costsHtml();
    $$("[data-kofi]").forEach((a) => { a.href = C.KOFI_URL; a.addEventListener("click", () => track("kofi")); });
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
    $$(".hero .chip input").forEach((el) => el.addEventListener("change", () => { if (el.checked) track(`filter/${el.id.replace(/^f-/, "")}`); }));
    $("#f-nogerman").addEventListener("change", (e) => { setChecked("german", e.target.checked ? NO_GERMAN : []); search(); });
    $("#f-remote").addEventListener("change", (e) => { setChecked("remote", e.target.checked ? REMOTE : []); search(); });
    $("#reset-filters").addEventListener("click", () => { writeFilters({}); search(); });
    $(".results-col").addEventListener("click", (e) => {
      const b = e.target.closest("[data-scope]");
      if (!b) return;
      descFor = b.dataset.scope === "all" ? $("#q").value.trim() : null;
      if (descFor) track("search/descriptions", "Search");
      search();
    });
    $("#pager").addEventListener("click", (e) => {
      const b = e.target.closest("[data-page]");
      if (!b || b.disabled) return;
      track(`page/${b.dataset.page}`);
      search({ page: Number(b.dataset.page), scroll: true });
    });
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
      track(`open/${d.id.replace(/-dialog$/, "")}`);
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
      track("hired");
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

    // A logo that fails to load becomes coloured initials instead of a broken-image icon.
    document.addEventListener("error", (e) => {
      const img = e.target;
      if (!(img instanceof HTMLImageElement) || !img.classList.contains("logo")) return;
      const tmp = document.createElement("div");
      companies[coKey(img.dataset.name)] = { ...(companies[coKey(img.dataset.name)] || {}), l: null };
      tmp.innerHTML = logoHtml(img.dataset.name || "?", [...img.classList].filter((c) => c !== "logo").join(" "));
      img.replaceWith(tmp.firstElementChild);
    }, true);

    // job popup: its own URL (?job=<id>), back button closes it
    $("#job-dialog").addEventListener("click", onDialogClick);
    $("#job-dialog").addEventListener("close", () => { if (openId) closeJob(); });
    window.addEventListener("popstate", () => {
      const id = new URLSearchParams(location.search).get("job");
      if (id) openJob(id, { push: false }); else if (openId) closeJob({ pop: true });
    });
    const startJob = new URLSearchParams(location.search).get("job");

    loadStats();
    loadFacets();
    loadFreshness();
    const ready = Promise.all([
      fetch("companies-index.json").then((r) => (r.ok ? r.json() : {})).then((d) => { companies = d; }).catch(() => {}),
      C.DEV_INSIGHTS_URL ? fetch(C.DEV_INSIGHTS_URL).then((r) => r.json()).then((d) => { devInsights = d; }).catch(() => {}) : null,
    ]);
    const startPage = Math.max(1, parseInt(new URLSearchParams(location.search).get("page"), 10) || 1);
    ready.then(() => {
      renderStats();
      renderHiring();
      search({ page: startPage });
      if (startJob) openJob(startJob, { push: false });
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
