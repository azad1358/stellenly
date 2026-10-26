// Companies page: filter the directory, and an opt-in map with hover cards.
// The map only loads after a click (tiles come from OpenStreetMap).
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const CONSENT = "ejg.mapConsent";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };

  // ------------------------------------------------------------ directory filter
  const search = $("#co-search"), startups = $("#co-startups");
  let markers = [], cluster = null, map = null;

  function matches(text, startup) {
    const q = (search.value || "").trim().toLowerCase();
    return (!startups.checked || startup) && (!q || q.split(/\s+/).every((w) => text.includes(w)));
  }

  function applyFilter() {
    let any = false;
    for (const sec of $$(".co-city")) {
      let shown = 0;
      for (const li of $$("[data-search]", sec)) {
        const ok = matches(li.dataset.search, li.dataset.startup === "1");
        li.hidden = !ok;
        shown += ok;
      }
      sec.hidden = !shown;
      const more = $(".co-more", sec);
      if (more) more.hidden = !$$(".co-minis li", sec).some((li) => !li.hidden);
      any ||= shown > 0;
    }
    $("#co-empty").hidden = any;
    if (cluster) {
      cluster.clearLayers();
      cluster.addLayers(markers.filter((m) => matches(m.options.search, m.options.data.s === 1)));
    }
  }
  search.addEventListener("input", applyFilter);
  startups.addEventListener("change", applyFilter);

  // City chips: jump to the section and, if the map is open, zoom to that city.
  for (const chip of $$(".co-chips [data-city]")) {
    chip.addEventListener("click", () => {
      if (!map) return;
      const pts = markers.filter((m) => m.options.data.c === chip.dataset.city).map((m) => m.getLatLng());
      if (pts.length) map.flyToBounds(L.latLngBounds(pts).pad(0.4), { maxZoom: 13, duration: 0.6 });
    });
  }

  // ------------------------------------------------------------ map
  const box = $("#co-map");
  const isDark = () => {
    const t = document.documentElement.dataset.theme;
    return t === "dark" || (t !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  };
  const loadCss = (href) => new Promise((res) => {
    const l = Object.assign(document.createElement("link"), { rel: "stylesheet", href, onload: res, onerror: res });
    document.head.appendChild(l);
  });
  const loadJs = (src) => new Promise((res, rej) => {
    const s = Object.assign(document.createElement("script"), { src, onload: res, onerror: rej });
    document.head.appendChild(s);
  });
  const short = (s) => (s.length > 16 ? s.slice(0, 15) + "…" : s);

  function card(d) {
    const facts = [d.i, d.f && `Founded ${d.f}`, d.z && `${d.z} people`].filter(Boolean).map(esc).join(" · ");
    const roles = d.r.map(([t, u]) => `<li><a href="${esc(u)}" target="_blank" rel="noopener nofollow">${esc(t)}</a></li>`).join("");
    return `<div class="pc">
      <div class="pc-head"><b>${esc(d.n)}</b>${d.s ? '<span class="badge new">Startup</span>' : ""}</div>
      ${facts ? `<div class="pc-meta">${facts}</div>` : ""}
      <div class="pc-count">${d.k ? `${d.k} open position${d.k === 1 ? "" : "s"} in ${esc(d.c)}` : `Headquarters in ${esc(d.c)} · no open jobs right now`}</div>
      ${roles ? `<ul class="pc-roles">${roles}</ul>` : ""}
      ${d.k > d.r.length ? `<div class="muted small">+ ${d.k - d.r.length} more</div>` : ""}
      ${d.u ? `<a class="pc-more" href="${esc(d.u)}">Company profile &amp; all jobs →</a>` : ""}
    </div>`;
  }

  async function startMap() {
    box.classList.add("loading");
    box.innerHTML = '<p class="muted map-wait">Loading map…</p>';
    try {
      await Promise.all([loadCss("vendor/leaflet/leaflet.css"), loadCss("vendor/leaflet/MarkerCluster.css")]);
      await loadJs("vendor/leaflet/leaflet.js");
      await loadJs("vendor/leaflet/markercluster.js");
      const data = await (await fetch("companies-map.json")).json();
      box.innerHTML = "";
      box.classList.remove("loading");
      box.classList.add("ready");

      map = L.map(box, { scrollWheelZoom: false, worldCopyJump: false, minZoom: 5 }).setView([51.2, 10.4], 6);
      map.on("focus click", () => map.scrollWheelZoom.enable());
      // OpenStreetMap tiles, toned down with a CSS filter (.co-map .leaflet-tile-pane) to match the site.
      box.classList.toggle("dark", isDark());
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);

      cluster = L.markerClusterGroup({
        showCoverageOnHover: false, maxClusterRadius: 52, spiderfyOnMaxZoom: true,
        iconCreateFunction(c) {
          const kids = c.getAllChildMarkers();
          const jobs = kids.reduce((a, m) => a + m.options.data.k, 0);
          return L.divIcon({ className: "pin-wrap", iconSize: [0, 0],
            html: `<span class="pin-cluster"><b>${kids.length}</b> companies<small>${jobs.toLocaleString()} jobs</small></span>` });
        },
      });

      let closeTimer = 0;
      const keepOpen = () => clearTimeout(closeTimer);
      const closeSoon = (m) => { keepOpen(); closeTimer = setTimeout(() => m.closePopup(), 260); };
      markers = data.map((d) => {
        const m = L.marker([d.y, d.x], {
          data: d, search: `${d.n} ${d.i || ""} ${d.c}`.toLowerCase(), title: d.n, riseOnHover: true,
          icon: L.divIcon({ className: "pin-wrap", iconSize: [0, 0],
            html: `<span class="pin${d.s ? " startup" : ""}${d.k ? "" : " quiet"}">${esc(short(d.n))}<b>${d.k}</b></span>` }),
        });
        m.bindPopup(() => card(d), { closeButton: false, className: "co-popup", maxWidth: 320, minWidth: 240, offset: [0, -34] });
        m.on("mouseover", () => { keepOpen(); m.openPopup(); });
        m.on("mouseout", () => closeSoon(m));
        m.on("popupopen", (ev) => {
          const el = ev.popup.getElement();
          el.addEventListener("mouseenter", keepOpen);
          el.addEventListener("mouseleave", () => closeSoon(m));
        });
        return m;
      });
      map.addLayer(cluster);
      applyFilter();
    } catch (err) {
      box.classList.remove("loading");
      box.innerHTML = '<p class="muted map-wait">The map could not be loaded. Please try again later.</p>';
    }
  }

  if (box) {
    if (store.get(CONSENT) === "1") startMap();
    else $("#map-load").addEventListener("click", () => {
      if ($("#map-remember").checked) store.set(CONSENT, "1");
      startMap();
    });
  }
})();
