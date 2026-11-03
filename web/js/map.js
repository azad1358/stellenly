// The job map (map.html): every open job as a dot, placed by meaning (UMAP of its embedding, computed in
// ingest/insights.py), every company as a node in the middle of its jobs. WebGL via sigma.js + graphology
// (MIT, js/vendor/). Hovering a job shows its requirements and lights up its company and its most similar jobs;
// "Show me on the map" places you among the jobs that match your field, level and skills. Nothing leaves the
// browser: the profile is matched here and kept in localStorage.
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
  const k = (n) => `€${Math.round(n / 1000)}k`;

  const tt = $("#theme-toggle");
  if (tt) tt.addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("ejg.theme", root.dataset.theme); } catch { /* ignore */ }
  });

  let D, graph, renderer, hovered = null, me = null;
  const shown = new Set([0, 1, 2, 3]);           // German levels visible
  const lit = new Set();                         // nodes highlighted by hover or by "you"

  fetch("data/job-map.json").then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then(start)
    .catch(() => { $("#map-loading").textContent = "The map isn't ready yet. It is built every day; please try again later."; });

  function start(data) {
    D = data;
    const G = window.graphology;
    graph = new (G.Graph || G)({ multi: false, type: "undirected" });
    // companies: in the middle of their jobs, sized by how many they have
    const sums = D.companies.map(() => [0, 0, 0]);
    D.jobs.forEach((j) => { const s = sums[j[4]]; s[0] += j[1]; s[1] += j[2]; s[2] += 1; });
    D.companies.forEach(([name], i) => {
      const [sx, sy, n] = sums[i];
      if (n) graph.addNode(`c${i}`, { x: sx / n, y: -sy / n, size: 2.5 + Math.sqrt(n) * 0.9, label: name, color: "#c7d2fe", kind: "c", n });
    });
    D.jobs.forEach((j, i) => graph.addNode(`j${i}`, { x: j[1], y: -j[2], size: 3, label: "", color: GERMAN[j[6]][1], kind: "j" }));
    D.jobs.forEach((j, i) => {
      graph.addEdge(`j${i}`, `c${j[4]}`, { color: "rgba(230,233,245,.35)", size: 0.6 });
      j[11].forEach((s) => { if (!graph.hasEdge(`j${i}`, `j${s}`)) graph.addEdge(`j${i}`, `j${s}`, { color: "rgba(165,180,252,.8)", size: 1 }); });
    });
    renderer = new window.Sigma(graph, $("#map"), {
      renderEdgeLabels: false, labelColor: { color: "#e6e9f5" }, labelSize: 12, labelWeight: "600",
      labelDensity: 0.6, labelRenderedSizeThreshold: 9, defaultEdgeColor: "rgba(165,180,252,.6)",
      zIndex: true, nodeReducer, edgeReducer,
    });
    renderer.on("enterNode", ({ node, event }) => { hovered = node; light(); tip(node, event); });
    renderer.on("leaveNode", () => { hovered = null; light(); $("#map-tip").hidden = true; });
    renderer.on("clickNode", ({ node }) => {
      const a = graph.getNodeAttributes(node);
      if (a.kind === "j") location.href = `job.html?id=${encodeURIComponent(D.jobs[+node.slice(1)][0])}`;
      else if (a.kind === "c" && D.companies[+node.slice(1)][1]) location.href = D.companies[+node.slice(1)][1];
    });
    renderer.getMouseCaptor().on("mousemovebody", (e) => { if (hovered) place(e); });
    $("#map-loading").hidden = true;
    $("#map-note").textContent = `${D.jobs.length.toLocaleString("en")} jobs · ${graph.filterNodes((n, a) => a.kind === "c").length} companies · updated ${D.updated}. Click a dot to open the job.`;
    legend();
    form();
  }

  // ------------------------------------------------------------------ drawing rules
  function nodeReducer(node, a) {
    const r = { ...a };
    if (a.kind === "j" && !shown.has(D.jobs[+node.slice(1)][6])) return { ...r, hidden: true };
    if (a.kind === "you") return { ...r, zIndex: 3, forceLabel: true };
    if (lit.size) {
      if (lit.has(node)) return { ...r, zIndex: 2, size: a.kind === "j" ? 5 : a.size, forceLabel: a.kind === "c" };
      return { ...r, color: a.kind === "c" ? "#3a4266" : "#2a3050", label: a.kind === "c" ? "" : a.label, zIndex: 0 };
    }
    return r;
  }
  function edgeReducer(edge, a) {
    const [s, t] = graph.extremities(edge);
    const focus = hovered || (me && "you");
    return focus && (s === focus || t === focus) ? { ...a, zIndex: 1 } : { ...a, hidden: true };
  }
  function light() {
    lit.clear();
    const focus = hovered || (me && "you");
    if (focus) { lit.add(focus); graph.forEachNeighbor(focus, (n) => lit.add(n)); }
    renderer.refresh({ skipIndexation: true });
  }

  // ------------------------------------------------------------------ hover card
  function tip(node, event) {
    const a = graph.getNodeAttributes(node), el = $("#map-tip");
    if (a.kind === "you") { el.hidden = true; return; }
    if (a.kind === "c") {
      el.innerHTML = `<b>${esc(a.label)}</b><span class="muted">${a.n} open job${a.n === 1 ? "" : "s"} on the map</span>`;
    } else {
      const j = D.jobs[+node.slice(1)], [gl, gc] = GERMAN[j[6]];
      const skills = j[9].slice(0, 8).map(([s, w]) => `<li><span>${esc(D.skills[s])}</span><i style="width:${Math.max(8, w)}%"></i></li>`).join("");
      const sal = j[13] ? `${k(j[13])}${j[14] && j[14] !== j[13] ? `–${k(j[14]).slice(1)}` : ""}` : "";
      el.innerHTML = `<b>${esc(j[3])}</b><span class="muted">${esc(D.companies[j[4]][0])}${j[5] ? ` · ${esc(j[5])}` : ""}${j[7] ? " · Remote" : ""}</span>
        <span class="tip-tags"><em style="--c:${gc}">${gl}</em>${j[12] ? "<em>Visa sponsorship</em>" : ""}${sal ? `<em>${sal}</em>` : ""}${LEVEL[j[8]] ? `<em>${LEVEL[j[8]]}</em>` : ""}</span>
        ${skills ? `<p class="tip-h">What it asks for</p><ul class="tip-skills">${skills}</ul>` : ""}
        ${j[11].length ? `<p class="tiny muted">Lines: its company and its ${j[11].length === 1 ? "most similar job" : `${j[11].length} most similar jobs`}.</p>` : ""}`;
    }
    el.hidden = false;
    place(event);
  }
  function place(e) {
    const el = $("#map-tip"), box = $("#map").getBoundingClientRect();
    const x = Math.min(e.x + 16, box.width - el.offsetWidth - 8), y = Math.min(e.y + 16, box.height - el.offsetHeight - 8);
    el.style.transform = `translate(${Math.max(8, x)}px, ${Math.max(8, y)}px)`;
  }

  // ------------------------------------------------------------------ legend = German filter
  function legend() {
    const counts = [0, 0, 0, 0];
    D.jobs.forEach((j) => counts[j[6]]++);
    $("#map-legend").innerHTML = GERMAN.map(([label, c], i) => `<label class="lg"><input type="checkbox" data-g="${i}" checked>
      <span class="lg-dot" style="background:${c}"></span>${label}<b>${counts[i].toLocaleString("en")}</b></label>`).join("");
    $("#map-legend").addEventListener("change", (e) => {
      const g = Number(e.target.dataset.g);
      if (e.target.checked) shown.add(g); else shown.delete(g);
      renderer.refresh();
    });
  }

  // ------------------------------------------------------------------ "where do you fit?"
  function form() {
    const fieldCount = new Map(), skillCount = new Map();
    D.jobs.forEach((j) => { j[10].forEach((f) => fieldCount.set(f, (fieldCount.get(f) || 0) + 1)); j[9].forEach(([s]) => skillCount.set(s, (skillCount.get(s) || 0) + 1)); });
    $("#me-field").insertAdjacentHTML("beforeend", [...fieldCount].sort((a, b) => b[1] - a[1]).slice(0, 30)
      .map(([f, n]) => `<option value="${f}">${esc(D.fields[f])} (${n})</option>`).join(""));
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
    $("#map-fit").addEventListener("click", () => renderer.getCamera().animatedReset());
    $("#map-panel").addEventListener("click", () => $("#map-side").classList.toggle("open"));
    const saved = store.get("mapProfile", null);
    if (saved) {
      $("#me-field").value = saved.field || ""; $("#me-level").value = saved.level || ""; $("#me-remote").checked = !!saved.remote;
      skills = saved.skills || []; chips();
      if (skills.length || saved.field) locate(skills, false);
    }
  }

  // Score every job against the profile: skills it asks for (weighted by how important the posting makes them),
  // the field, the level and remote. You sit in the middle of your 12 best matches.
  function locate(skills, animate = true) {
    const field = $("#me-field").value, level = $("#me-level").value, remote = $("#me-remote").checked;
    store.set("mapProfile", { field, level, remote, skills });
    const want = skills.map((s) => s.toLowerCase());
    const max = want.length + (field ? 1 : 0) + (level ? 0.5 : 0);
    const scored = [];
    D.jobs.forEach((j, i) => {
      if (!shown.has(j[6]) || (remote && !j[7])) return;
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
    const best = scored.slice(0, 12);
    if (graph.hasNode("you")) graph.dropNode("you");
    me = null;
    if (!best.length) {
      $("#me-result").hidden = false;
      $("#me-result").innerHTML = `<p class="muted small">No jobs match yet. Try another field, fewer filters or other skills.</p>`;
      light();
      return;
    }
    const tw = best.reduce((t, [s]) => t + s, 0);
    const x = best.reduce((t, [s, i]) => t + s * D.jobs[i][1], 0) / tw, y = best.reduce((t, [s, i]) => t + s * D.jobs[i][2], 0) / tw;
    graph.addNode("you", { x, y: -y, size: 12, label: "You", color: "#ffffff", kind: "you" });
    best.forEach(([, i]) => graph.addEdge("you", `j${i}`, { color: "rgba(255,255,255,.75)", size: 1.2 }));
    me = best;
    light();
    $("#me-result").hidden = false;
    $("#me-result").innerHTML = `<p class="kicker">Your closest jobs</p><ol class="me-list">${best.map(([s, i]) => {
      const j = D.jobs[i];
      return `<li><a href="job.html?id=${encodeURIComponent(j[0])}"><b>${esc(j[3])}</b><span>${esc(D.companies[j[4]][0])}${j[5] ? ` · ${esc(j[5])}` : ""}</span></a>
        <em style="--c:${GERMAN[j[6]][1]}">${Math.min(99, Math.round((100 * s) / Math.max(max, 1)))}%</em></li>`; }).join("")}</ol>
      <p class="tiny muted">% = how much of your profile the job matches (skills, field, level).</p>`;
    if (animate) {
      const p = renderer.getNodeDisplayData("you");
      if (p) renderer.getCamera().animate({ x: p.x, y: p.y, ratio: 0.35 }, { duration: 700 });
      $("#map-side").classList.remove("open");
    }
  }
})();
