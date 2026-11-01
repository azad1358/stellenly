// Header counter on every page: all jobs collected since launch (site_stats.total) on number drums that roll up
// from 0. Needs js/config.js first; without it, or if the request fails, the counter just stays hidden.
(() => {
  "use strict";
  const C = window.SITE_CONFIG;
  const box = document.getElementById("job-counter");
  if (!box || !C || !C.SUPABASE_URL) return;

  fetch(`${C.SUPABASE_URL.replace(/\/$/, "")}/rest/v1/rpc/site_stats`, {
    method: "POST",
    headers: { apikey: C.SUPABASE_ANON_KEY, Authorization: `Bearer ${C.SUPABASE_ANON_KEY}`, "Content-Type": "application/json" },
    body: "{}",
  }).then((r) => (r.ok ? r.json() : null)).then((s) => { if (s && s.total) render(s.total); }).catch(() => {});

  function render(total) {
    const digits = String(total).padStart(6, "0").split("");
    box.title = `${total.toLocaleString("en")} jobs collected since launch`;
    box.setAttribute("aria-label", box.title);
    const strip = "01234567890123456789".split("").map((d) => `<span>${d}</span>`).join(""); // two turns of the drum
    box.querySelector(".odo-window").innerHTML = digits.map(() => `<span class="odo-digit"><span class="odo-strip">${strip}</span></span>`).join("");
    box.hidden = false;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      box.querySelectorAll(".odo-strip").forEach((s, i) => {
        s.style.transitionDelay = `${i * 90}ms`;
        s.style.transform = `translateY(-${(10 + Number(digits[i])) * 5}%)`; // one full turn, then the digit (20 rows = 5% each)
      });
    }));
  }
})();
