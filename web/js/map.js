// The job map (map.html): every open job in 3D, placed by what its posting describes and asks for (3D UMAP of the
// embeddings, ingest/insights.py): close means similar. Each category (AI & ML, Sales, ...) is a hub in the middle
// of its jobs, and each job is linked to the one of its categories whose cluster it lies closest to. 3d-force-graph
// (three.js, MIT, js/vendor/): rotate, zoom, drag, 2D/3D, sliders. Hover: a job's requirements and its nearest jobs
// with their cosine similarity. Click a category: its jobs, listed. "Show me on the map" adds you, linked to your
// best matches. Nothing leaves the browser: the profile is matched here.
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem("ejg." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("ejg." + k, JSON.stringify(v)); } catch { /* private mode */ } },
  };
  // German level: colour + label (palette validated against the navy map surface, dark mode)
  const GERMAN = [["No German needed", "#1a9a8c"], ["German nice to have", "#c27c1f"], ["German not mentioned", "#7a82f2"], ["German required", "#dd5a6a"]];
  const LEVEL = { intern: "Intern / student", junior: "Junior", mid: "Mid-level", senior: "Senior", lead: "Lead" };
  const FIELD_NAMES = { "ai-ml": "AI & machine learning", it: "IT", hr: "HR", qa: "QA", devops: "DevOps" };  // as in app.js
  const fieldName = (t) => FIELD_NAMES[t] || t.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase());
  const HUB = "#e6e9f5", DIM = "#252b48", YOU = "#ffffff";
  const MAX_HUBS = 16, MIN_JOBS = 15;
  const k = (n) => `€${Math.round(n / 1000)}k`;

  const tt = $("#theme-toggle");
  if (tt) tt.addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("ejg.theme", root.dataset.theme); } catch { /* ignore */ }
  });

  let D, G, nodes = [], links = [], hubs = [];
  const shown = new Set([0, 1, 2, 3]);   // German levels visible
  let city = "";                         // city filter ("" = all)
  const lit = new Set();                 // highlighted nodes (hover, a chosen category or "you")
  let hovered = null, me = null, picked = null, fitted = false, charge = null;
  let pickOk = () => true;  // extra filter on a picked category's jobs (level / remote from the form)
  let spread = 6, meaning = 0.15, hubLines = false;  // category lines: off at first (5,000 lines are heavy)
  let breathing = !matchMedia("(prefers-reduced-motion: reduce)").matches;  // the slow "alive" drift

  fetch("data/job-map.json").then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then(start)
    .catch((err) => { console.error(err); $("#map-loading").textContent = "The map isn't ready yet. It is built every day; please try again later."; });

  function start(data) {
    D = data;
    // each job's semantic 3D position (0-1000 -> about -700..700) is its home
    const at = (v) => (v - 500) * 1.4;
    const home = (x, y, z) => ({ x, y, z, hx: x, hy: y, hz: z });
    D.jobs.forEach((j, i) => nodes.push({ id: `j${i}`, kind: "j", ji: i, ...home(at(j[1]), -at(j[2]), at(j[15])) }));
    // categories: the biggest fields, each at the centre of its jobs
    const byField = new Map();
    D.jobs.forEach((j, i) => j[10].forEach((f) => { if (!byField.has(f)) byField.set(f, []); byField.get(f).push(i); }));
    hubs = [...byField].filter(([, js]) => js.length >= MIN_JOBS).sort((a, b) => b[1].length - a[1].length).slice(0, MAX_HUBS)
      .map(([f, js]) => {
        const c = (a) => js.reduce((t, i) => t + nodes[i][a], 0) / js.length;
        return { f, name: fieldName(D.fields[f]), jobs: [], ...home(c("hx"), c("hy"), c("hz")) };
      });
    // each job joins the one of its categories whose centre is nearest (named, but by meaning)
    const hubOf = new Map(hubs.map((h, hi) => [h.f, hi]));
    D.jobs.forEach((j, i) => {
      const n = nodes[i];
      let best = -1, bestD = Infinity;
      j[10].forEach((f) => {
        if (!hubOf.has(f)) return;
        const h = hubs[hubOf.get(f)], d = (h.hx - n.hx) ** 2 + (h.hy - n.hy) ** 2 + (h.hz - n.hz) ** 2;
        if (d < bestD) { bestD = d; best = hubOf.get(f); }
      });
      if (best >= 0) { n.hub = best; hubs[best].jobs.push(i); }
    });
    hubs.forEach((h, hi) => {
      nodes.push({ id: `f${hi}`, kind: "f", hi, name: h.name, n: h.jobs.length, x: h.hx, y: h.hy, z: h.hz, hx: h.hx, hy: h.hy, hz: h.hz });
      h.jobs.forEach((i) => links.push({ source: `j${i}`, target: `f${hi}`, kind: "f" }));
    });
    D.jobs.forEach((j, i) => j[11].forEach(([s, sim]) => links.push({ source: `j${i}`, target: `j${s}`, kind: "s", sim })));

    G = window.ForceGraph3D()($("#map"))
      .backgroundColor("#0a1024")
      .showNavInfo(false)
      .nodeRelSize(4.2)
      .nodeResolution(8)
      .nodeVal((n) => (n.kind === "f" ? 6 + Math.sqrt(n.n) * 1.2 : n.kind === "you" ? 14 : 1))
      .nodeColor(color)
      .nodeVisibility(nodeVisible)
      .nodeLabel(label)
      .linkVisibility(linkVisible)
      .linkColor(linkColor)
      .linkWidth((l) => (focused(l) ? 1.2 : 0))
      .linkOpacity(0.5)
      .onNodeHover((n) => { hovered = n || null; light(); $("#map").style.cursor = n ? "pointer" : "grab"; })
      .onNodeClick((n) => {
        if (n.kind === "j") location.href = `job.html?id=${encodeURIComponent(D.jobs[n.ji][0])}`;
        else if (n.kind === "f") pick(n.hi);
      })
      .onNodeDragEnd((n) => { n.fx = n.fy = n.fz = undefined; })   // let it flow back to its place
      .cooldownTime(breathing ? Infinity : 15000)
      .d3AlphaMin(0)
      .d3VelocityDecay(0.35)
      .onEngineStop(() => { if (!fitted) { fitted = true; fit(); } })
      .graphData({ nodes, links });
    // meaning first: a strong pull to the semantic position; the category line only pulls a little
    G.d3Force("link").distance(30).strength((l) => (l.kind === "f" ? 0.03 : l.kind === "you" ? 0.3 : 0));
    G.d3Force("charge").strength(-spread);
    const pull = (alpha) => nodes.forEach((n) => {
      if (n.hx == null) return;
      const a = meaning * Math.max(alpha, 0.03);  // never zero, so the breathing can't drift away
      n.vx += (n.hx - n.x) * a; n.vy += (n.hy - n.y) * a; n.vz += (n.hz - (n.z || 0)) * a;
    });
    pull.initialize = () => {};
    G.d3Force("home", pull);
    // breathing: each node sways slowly around its place, with its own rhythm (a few units, every few seconds)
    const breath = () => {
      if (!breathing) return;
      const t = performance.now() / 1000;
      nodes.forEach((n) => {
        if (n.ph == null) { n.ph = Math.random() * 6.283; n.fr = 0.35 + Math.random() * 0.35; }
        n.vx += Math.cos(t * n.fr + n.ph) * 0.03;
        n.vy += Math.sin(t * n.fr * 1.13 + n.ph) * 0.03;
        n.vz = (n.vz || 0) + Math.cos(t * n.fr * 0.87 + n.ph * 1.7) * 0.03;
      });
    };
    breath.initialize = () => {};
    G.d3Force("breath", breath);
    // the engine never stops while breathing: once settled, fit the view and drop the costly node-node repulsion
    // (the pull keeps every node at its place anyway); the Spread slider brings it back
    if (breathing) setTimeout(() => { if (!fitted) { fitted = true; fit(); } charge = G.d3Force("charge"); G.d3Force("charge", null); }, 5000);
    resize();
    addEventListener("resize", resize);

    $("#map-loading").hidden = true;
    $("#map-note").textContent = `${D.jobs.length.toLocaleString("en")} jobs in ${hubs.length} categories · updated ${D.updated}. `
      + "Drag to rotate, scroll to zoom, drag a dot to move it, click a job to open it.";
    hubLabels();
    categories();
    legend();
    controls();
    form();
  }

  const id = (x) => (typeof x === "object" ? x.id : x);
  const node = (x) => (typeof x === "object" ? x : nodes.find((n) => n.id === x));
  const jobShown = (j) => shown.has(j[6]) && (!city || j[5] === city);
  const nodeVisible = (n) => n.kind !== "j" || jobShown(D.jobs[n.ji]);
  const visible = (x) => { const n = node(x); return !n || nodeVisible(n); };
  const focused = (l) => lit.size > 0 && lit.has(id(l.source)) && lit.has(id(l.target));
  const touches = (l) => hovered && (id(l.source) === hovered.id || id(l.target) === hovered.id);
  // category lines only while the button is on, in every state; "you" lines always; similar-job lines on hover
  const linkVisible = (l) => visible(l.source) && visible(l.target) && (l.kind !== "f" || hubLines)
    && (lit.size ? focused(l) || touches(l) : l.kind !== "s");
  function color(n) {
    const base = n.kind === "f" ? HUB : n.kind === "you" ? YOU : GERMAN[D.jobs[n.ji][6]][1];
    return lit.size && !lit.has(n.id) ? DIM : base;
  }
  function linkColor(l) {
    if (lit.size) return focused(l) ? "#c7d2fe" : "#161b38";
    return l.kind === "you" ? YOU : l.kind === "f" ? "#323a68" : "#2a3160";
  }
  function light() {
    lit.clear();
    const focus = hovered || (me && node("you")) || (picked != null && node(`f${picked}`));
    if (focus) {
      lit.add(focus.id);
      links.forEach((l) => {
        if (l.kind === "s" && focus.kind !== "j") return;  // a category or "you": only its own lines
        const s = id(l.source), t = id(l.target), other = s === focus.id ? t : t === focus.id ? s : null;
        if (other && !(focus.kind === "f" && other[0] === "j" && !pickOk(D.jobs[+other.slice(1)]))) lit.add(other);
      });
    }
    G.nodeColor(color).linkColor(linkColor).linkWidth((l) => (focused(l) ? 1.2 : 0)).linkVisibility(linkVisible);
  }
  const fit = () => G.zoomToFit(800, 0, (n) => n.kind === "j" && nodeVisible(n));
  // look at a set of nodes from far enough to see them all (most of them: the farthest 10% may fall outside)
  function frame(pts) {
    pts = pts.filter(Boolean);
    if (!pts.length) return;
    const c = { x: 0, y: 0, z: 0 };
    pts.forEach((p) => { c.x += p.x / pts.length; c.y += p.y / pts.length; c.z += (p.z || 0) / pts.length; });
    const d = pts.map((p) => Math.hypot(p.x - c.x, p.y - c.y, (p.z || 0) - c.z)).sort((a, b) => a - b);
    const r = Math.max(60, d[Math.floor(0.9 * (d.length - 1))]);
    G.cameraPosition({ x: c.x, y: c.y, z: c.z + r * 3 }, c, 1200);
  }
  function resize() { const box = $("#map").getBoundingClientRect(); G.width(box.width).height(box.height); }

  // ------------------------------------------------------------------ category names, always on the map
  let matchEls = [];  // [label element, job index] for your matches
  function matchLabels() {
    const box = $("#map-labels");
    box.querySelectorAll(".match-label").forEach((el) => el.remove());
    matchEls = (me || []).map(([s, i, pct]) => {
      const el = document.createElement("a");
      el.className = "match-label";
      el.href = `job.html?id=${encodeURIComponent(D.jobs[i][0])}`;
      el.innerHTML = `<b>${pct}%</b>${esc(D.jobs[i][3])}`;
      box.appendChild(el);
      return [el, i];
    });
  }
  function hubLabels() {
    const box = $("#map-labels");
    box.innerHTML = hubs.map((h, hi) => `<button type="button" class="hub-label" data-hub="${hi}">${esc(h.name)}<b>${h.jobs.length}</b></button>`).join("");
    box.addEventListener("click", (e) => { const b = e.target.closest("[data-hub]"); if (b) pick(+b.dataset.hub); });
    const els = [...box.children];
    const hubNodes = hubs.map((h, hi) => nodes.find((x) => x.id === `f${hi}`));
    const tick = () => {
      const placed = [];  // hubs are sorted biggest first: a smaller name that would overlap a bigger one hides
      hubs.forEach((h, hi) => {
        const n = hubNodes[hi], p = G.graph2ScreenCoords(n.x, n.y, n.z || 0), el = els[hi];
        const w = el.offsetWidth, ht = el.offsetHeight, box = [p.x - w / 2, p.y - ht * 1.5, p.x + w / 2, p.y - ht * 0.5];
        const chosen = picked === hi || (hovered && hovered.id === `f${hi}`);
        const clash = !chosen && placed.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1]);
        if (!clash) placed.push(box);
        el.style.transform = `translate(${p.x}px, ${p.y}px) translate(-50%, -150%)`;
        el.classList.toggle("dim", lit.size > 0 && !lit.has(`f${hi}`));
        el.classList.toggle("hide", clash || (!!me && !hovered));
      });
      matchEls.forEach(([el, i]) => {
        const n = nodes[i], p = G.graph2ScreenCoords(n.x, n.y, n.z || 0);
        el.style.transform = `translate(${p.x}px, ${p.y}px) translate(12px, -50%)`;
        el.hidden = !!hovered && hovered.id !== n.id && hovered.id !== "you";
      });
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------------ hover card (HTML tooltip of the library)
  function label(n) {
    if (n.kind === "you") return `<div class="map-tip"><b>You</b><span class="muted">Linked to your ${me ? me.length : 0} closest jobs</span></div>`;
    if (n.kind === "f") return `<div class="map-tip"><b>${esc(n.name)}</b><span class="muted">${n.n} jobs · click to list them</span></div>`;
    const j = D.jobs[n.ji], [gl, gc] = GERMAN[j[6]];
    const skills = j[9].slice(0, 8).map(([s, w]) => `<li><span>${esc(D.skills[s])}</span><i style="width:${Math.max(8, w)}%"></i></li>`).join("");
    const sal = j[13] ? `${k(j[13])}${j[14] && j[14] !== j[13] ? `–${k(j[14]).slice(1)}` : ""}` : "";
    const cat = n.hub != null ? `<span class="tip-cat">${esc(hubs[n.hub].name)}</span>` : "";
    return `<div class="map-tip">${cat}<b>${esc(j[3])}</b><span class="muted">${esc(D.companies[j[4]][0])}${j[5] ? ` · ${esc(j[5])}` : ""}${j[7] ? " · Remote" : ""}</span>
      <span class="tip-tags"><em style="--c:${gc}">${gl}</em>${j[12] ? "<em>Visa sponsorship</em>" : ""}${sal ? `<em>${sal}</em>` : ""}${LEVEL[j[8]] ? `<em>${LEVEL[j[8]]}</em>` : ""}</span>
      ${skills ? `<p class="tip-h">What it asks for</p><ul class="tip-skills">${skills}</ul>` : ""}
      ${j[11].length ? `<p class="tip-h">Most similar jobs (cosine similarity)</p><ul class="tip-nn">${j[11].slice(0, 4).map(([s, sim]) =>
        `<li><span>${esc(D.jobs[s][3])} · ${esc(D.companies[D.jobs[s][4]][0])}</span><b>${sim.toFixed(2)}</b></li>`).join("")}</ul>` : ""}</div>`;
  }

  // ------------------------------------------------------------------ categories: list, pick, show their jobs
  function categories() {
    $("#map-cats").innerHTML = hubs.map((h, hi) => `<button type="button" class="cat" data-hub="${hi}">${esc(h.name)}<b>${h.jobs.length}</b></button>`).join("");
    $("#map-cats").addEventListener("click", (e) => { const b = e.target.closest("[data-hub]"); if (b) pick(+b.dataset.hub); });
  }
  function pick(hi, ok = () => true, toggle = true) {
    picked = toggle && picked === hi ? null : hi;
    pickOk = ok;
    $$(".cat").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.hub === picked)));
    light();
    const box = $("#cat-result");
    if (picked == null) { box.hidden = true; return; }
    const h = hubs[hi], list = h.jobs.filter((i) => jobShown(D.jobs[i]) && ok(D.jobs[i]));
    box.hidden = false;
    box.innerHTML = `<p class="kicker">${esc(h.name)} · ${list.length} jobs</p><ol class="me-list">${list.slice(0, 60).map((i) => {
      const j = D.jobs[i];
      return `<li><a href="job.html?id=${encodeURIComponent(j[0])}"><b>${esc(j[3])}</b><span>${esc(D.companies[j[4]][0])}${j[5] ? ` · ${esc(j[5])}` : ""}</span></a>
        <em style="--c:${GERMAN[j[6]][1]}" title="${GERMAN[j[6]][0]}">${GERMAN[j[6]][0].replace("German ", "").replace("No German needed", "no German")}</em></li>`; }).join("")}</ol>
      ${list.length > 60 ? `<p class="tiny muted">The 60 first of ${list.length}. Search them all on the jobs page.</p>` : ""}`;
    frame([node(`f${hi}`), ...list.map((i) => nodes[i])]);
    $("#map-side").classList.remove("open");
  }
  const $$ = (s) => [...document.querySelectorAll(s)];

  // ------------------------------------------------------------------ legend = German filter; city; view controls
  function legend() {
    const counts = [0, 0, 0, 0];
    D.jobs.forEach((j) => counts[j[6]]++);
    $("#map-legend").innerHTML = GERMAN.map(([lbl, c], i) => `<label class="lg"><input type="checkbox" data-g="${i}" checked>
      <span class="lg-dot" style="background:${c}"></span>${lbl}<b>${counts[i].toLocaleString("en")}</b></label>`).join("");
    $("#map-legend").addEventListener("change", (e) => {
      const g = Number(e.target.dataset.g);
      if (e.target.checked) shown.add(g); else shown.delete(g);
      G.nodeVisibility(nodeVisible).linkVisibility(linkVisible);
    });
  }
  function controls() {
    $("#map-dim").addEventListener("click", (e) => {
      const three = G.numDimensions() === 3;
      G.numDimensions(three ? 2 : 3);
      e.target.textContent = three ? "3D" : "2D";
      e.target.title = three ? "Switch to 3D" : "Switch to 2D";
    });
    $("#map-spread").addEventListener("input", (e) => {
      spread = +e.target.value;
      if (!G.d3Force("charge") && charge) G.d3Force("charge", charge);
      G.d3Force("charge").strength(-spread);
      G.d3ReheatSimulation();
    });
    $("#map-meaning").addEventListener("input", (e) => { meaning = +e.target.value / 100; G.d3ReheatSimulation(); });
    const cities = new Map();
    D.jobs.forEach((j) => j[5] && cities.set(j[5], (cities.get(j[5]) || 0) + 1));
    $("#map-city").insertAdjacentHTML("beforeend", [...cities].sort((a, b) => b[1] - a[1]).slice(0, 40)
      .map(([c, n]) => `<option value="${esc(c)}">${esc(c)} (${n})</option>`).join(""));
    $("#map-city").addEventListener("change", (e) => { city = e.target.value; G.nodeVisibility(nodeVisible).linkVisibility(linkVisible); });
    $("#map-lines").addEventListener("click", (e) => {
      hubLines = !hubLines;
      e.currentTarget.setAttribute("aria-pressed", String(hubLines));
      G.linkVisibility(linkVisible);
    });
    const bb = $("#map-breathe");
    bb.setAttribute("aria-pressed", String(breathing));
    bb.addEventListener("click", () => {
      breathing = !breathing;
      bb.setAttribute("aria-pressed", String(breathing));
      G.cooldownTime(breathing ? Infinity : 4000);
      G.d3ReheatSimulation();
    });
    $("#map-shake").addEventListener("click", () => {
      nodes.forEach((n) => { n.vx = (Math.random() - 0.5) * 20; n.vy = (Math.random() - 0.5) * 20; n.vz = (Math.random() - 0.5) * 20; });
      G.d3ReheatSimulation();
    });
    $("#map-fit").addEventListener("click", fit);
    $("#map-panel").addEventListener("click", () => $("#map-side").classList.toggle("open"));
  }

  // ------------------------------------------------------------------ "where do you fit?"
  function form() {
    const skillCount = new Map();
    D.jobs.forEach((j) => j[9].forEach(([s]) => skillCount.set(s, (skillCount.get(s) || 0) + 1)));
    $("#me-field").insertAdjacentHTML("beforeend", hubs.map((h) => `<option value="${h.f}">${esc(h.name)} (${h.jobs.length})</option>`).join(""));
    $("#me-skill-list").innerHTML = [...skillCount].sort((a, b) => b[1] - a[1]).slice(0, 400)
      .map(([s]) => `<option value="${esc(D.skills[s])}">`).join("");
    let skills = [];
    const chips = () => { $("#me-chips").innerHTML = skills.map((s, i) => `<button type="button" class="me-chip" data-i="${i}">${esc(s)} ×</button>`).join(""); };
    const add = () => {
      const v = $("#me-skill").value.trim();
      if (v && !skills.some((s) => s.toLowerCase() === v.toLowerCase())) skills.push(v);
      $("#me-skill").value = ""; chips();
    };
    $("#me-skill").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } });
    $("#me-skill").addEventListener("change", add);
    $("#me-chips").addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) { skills.splice(+b.dataset.i, 1); chips(); } });
    $("#me-form").addEventListener("submit", (e) => { e.preventDefault(); add(); locate(skills); });
    $("#me-reset").addEventListener("click", () => {   // forget the profile: form, "you" node, list, saved copy
      skills = []; chips();
      $("#me-field").value = ""; $("#me-level").value = ""; $("#me-remote").checked = false; $("#me-skill").value = "";
      try { localStorage.removeItem("ejg.mapProfile"); } catch { /* private mode */ }
      nodes = nodes.filter((n) => n.kind !== "you");
      links = links.filter((l) => l.kind !== "you");
      me = null;
      G.graphData({ nodes, links });
      light();
      matchLabels();
      $("#me-result").hidden = true;
      fit();
    });
    const saved = store.get("mapProfile", null);
    if (saved) {
      $("#me-field").value = saved.field || ""; $("#me-level").value = saved.level || ""; $("#me-remote").checked = !!saved.remote;
      skills = saved.skills || []; chips();
      if (skills.length || saved.field) setTimeout(() => locate(skills, false), 400);
    }
  }

  // Score every job: skills it asks for (weighted by how important the posting makes them), the category, the level,
  // remote. You join the map linked to your 5 best matches (everything else dims), each labelled with its score.
  function locate(skills, fly = true) {
    const field = $("#me-field").value, level = $("#me-level").value, remote = $("#me-remote").checked;
    store.set("mapProfile", { field, level, remote, skills });
    const want = skills.map((s) => s.toLowerCase());
    if (!want.length) {
      // no skills: nothing to rank by, so show the whole category (with the level / remote choice), not 5 random ties
      nodes = nodes.filter((n) => n.kind !== "you");
      links = links.filter((l) => l.kind !== "you");
      me = null;
      G.graphData({ nodes, links });
      matchLabels();
      $("#me-result").hidden = false;
      const hi = hubs.findIndex((h) => String(h.f) === field);
      if (hi < 0) {
        $("#me-result").innerHTML = `<p class="muted small">Choose a category or add your skills.</p>`;
        light();
        return;
      }
      $("#me-result").innerHTML = `<p class="muted small">Add your skills to see your 5 closest jobs with a score.</p>`;
      pick(hi, (j) => (!level || j[8] === level) && (!remote || j[7]), false);
      return;
    }
    const max = want.length + (field ? 1 : 0) + (level ? 0.5 : 0);
    const scored = [];
    D.jobs.forEach((j, i) => {
      if (!jobShown(j) || (remote && !j[7])) return;
      let s = 0;
      for (const [sk, w] of j[9]) {
        const name = D.skills[sk].toLowerCase();
        if (want.some((x) => name === x || name.includes(x) || x.includes(name))) s += 0.5 + w / 200;
      }
      if (field && j[10].includes(+field)) s += 1;
      if (level && j[8] === level) s += 0.5;
      if (s > 0) scored.push([s, i]);
    });
    scored.sort((a, b) => b[0] - a[0]);
    const best = scored.slice(0, 5).map(([s, i]) => [s, i, Math.min(99, Math.round((100 * s) / Math.max(max, 1)))]);
    picked = null;
    $$(".cat").forEach((b) => b.setAttribute("aria-pressed", "false"));
    $("#cat-result").hidden = true;
    nodes = nodes.filter((n) => n.kind !== "you");
    links = links.filter((l) => l.kind !== "you");
    me = null;
    if (best.length) {
      const pts = best.map(([, i]) => node(`j${i}`));
      const c = (a) => pts.reduce((t, p) => t + (p[a] || 0), 0) / pts.length;
      nodes.push({ id: "you", kind: "you", x: c("x"), y: c("y"), z: c("z") });
      best.forEach(([, i]) => links.push({ source: "you", target: `j${i}`, kind: "you" }));
      me = best;
    }
    G.graphData({ nodes, links });
    light();
    matchLabels();
    $("#me-result").hidden = false;
    if (!best.length) {
      $("#me-result").innerHTML = `<p class="muted small">No jobs match yet. Try another category, fewer filters or other skills.</p>`;
      return;
    }
    $("#me-result").innerHTML = `<p class="kicker">Your 5 closest jobs</p><ol class="me-list">${best.map(([, i, pct]) => {
      const j = D.jobs[i];
      return `<li><a href="job.html?id=${encodeURIComponent(j[0])}"><b>${esc(j[3])}</b><span>${esc(D.companies[j[4]][0])}${j[5] ? ` · ${esc(j[5])}` : ""}</span></a>
        <em style="--c:${GERMAN[j[6]][1]}">${pct}%</em></li>`; }).join("")}</ol>
      <p class="tiny muted">% = how much of your profile the job matches (skills, category, level).</p>`;
    if (fly) {
      $("#map-side").classList.remove("open");
      // once the physics pulled you in: look at you and your 5 jobs, from far enough to see them all
      setTimeout(() => frame([node("you"), ...best.map(([, i]) => nodes[i])]), 900);
    }
  }
})();
