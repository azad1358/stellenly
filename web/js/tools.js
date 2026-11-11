/* Tools page: gross-to-net salary calculator (2026 German income tax, solidarity surcharge, church tax and the
   employee's share of social insurance). An estimate in the browser; nothing is sent anywhere.
   City medians come from the page (#tool-cities, built daily from the salaries listed in our jobs). */
(function () {
  "use strict";

  // 2026 figures
  const TAX_FREE = 12348;                          // Grundfreibetrag
  const WK = 1230, SA = 36, SINGLE_PARENT = 4260;  // Arbeitnehmer-Pauschbetrag, Sonderausgaben-Pauschbetrag, Entlastungsbetrag (class II)
  const SOLI_FREE = 20350;                         // income tax up to this pays no solidarity surcharge (class III: double)
  const BBG_RV = 101400, BBG_KV = 69750;           // contribution ceilings per year: pension/unemployment, health/care
  const RV = 0.093, AV = 0.013;                    // pension 18.6 %, unemployment 2.6 %: half each
  const KV = 0.0875;                               // health 14.6 % + average extra 2.9 %: half
  const KV_VSP = 0.0845;                           // health as the payroll-tax allowance counts it (reduced 14 % rate + half the extra)
  const PV = 0.018, PV_CHILDLESS = 0.006, PV_SAXONY = 0.005;  // care 3.6 %: half; +0.6 % without children; Saxony employees +0.5 %
  const W1 = 14071, W2 = 34939, W3 = 222260;       // class V/VI thresholds

  // §32a EStG, 2026: income tax on a taxable income x (whole euros)
  function tariff(x) {
    x = Math.floor(x);
    if (x <= TAX_FREE) return 0;
    if (x <= 17799) { const y = (x - TAX_FREE) / 10000; return Math.floor((914.51 * y + 1400) * y); }
    if (x <= 69878) { const z = (x - 17799) / 10000; return Math.floor((173.10 * z + 2397) * z + 1034.87); }
    if (x <= 277825) return Math.floor(0.42 * x - 11135.63);
    return Math.floor(0.45 * x - 19470.38);
  }

  // Classes V and VI (payroll-tax program, MST5_6)
  function tariff56(zx) {
    const up = (v) => Math.max(Math.floor((tariff(v * 1.25) - tariff(v * 0.75)) * 2), Math.floor(v * 0.14));
    if (zx > W2) {
      const st = up(W2);
      return zx > W3 ? Math.floor(st + (W3 - W2) * 0.42 + (zx - W3) * 0.45) : Math.floor(st + (zx - W2) * 0.42);
    }
    const st = up(zx);
    if (zx > W1) return Math.min(st, Math.floor(up(W1) + (zx - W1) * 0.42));
    return st;
  }

  /* gross: per year. taxClass: 1-6. church: false or the rate (0.08 Bavaria/Baden-Württemberg, else 0.09).
     children: true = no childless care surcharge. saxony: Saxony's higher employee share of care insurance. */
  function netSalary({ gross, taxClass, church, children, saxony }) {
    const rvBase = Math.min(gross, BBG_RV), kvBase = Math.min(gross, BBG_KV);
    const pvRate = PV + (children ? 0 : PV_CHILDLESS) + (saxony ? PV_SAXONY : 0);
    const social = { pension: rvBase * RV, unemployment: rvBase * AV, health: kvBase * KV, care: kvBase * pvRate };
    const allowance = rvBase * (RV + AV) + kvBase * (KV_VSP + pvRate);  // Vorsorgepauschale
    const taxable = Math.max(0, Math.floor(gross - allowance - (taxClass === 6 ? 0 : WK + SA)
                                           - (taxClass === 2 ? SINGLE_PARENT : 0)));
    const incomeTax = taxClass === 3 ? 2 * tariff(taxable / 2) : taxClass >= 5 ? tariff56(taxable) : tariff(taxable);
    const free = taxClass === 3 ? 2 * SOLI_FREE : SOLI_FREE;
    const soli = incomeTax > free ? Math.min(incomeTax * 0.055, (incomeTax - free) * 0.119) : 0;
    const churchTax = church ? incomeTax * church : 0;
    const deductions = incomeTax + soli + churchTax + social.pension + social.unemployment + social.health + social.care;
    return { gross, incomeTax, soli, churchTax, ...social, net: gross - deductions };
  }

  if (typeof module !== "undefined") { module.exports = { netSalary, tariff, tariff56 }; return; }

  // ---------- page ----------
  const $ = (s) => document.querySelector(s);
  const form = $("#salary-form");
  if (!form) return;
  const data = JSON.parse($("#tool-cities").textContent);
  const cities = Object.fromEntries(data.cities.map((c) => [c.city, c]));
  const eur = (n) => (Math.round(n) < 0 ? "−€" : "€") + Math.abs(Math.round(n)).toLocaleString("en-US");
  const CHURCH_8 = ["DE-BY", "DE-BW"];

  // The city list shows only the cities of the chosen state; picking a city sets its state.
  const cityOpts = [...$("#sal-city").options].slice(1);  // without "Other city"
  function filterCities() {
    const state = $("#sal-state").value, sel = $("#sal-city");
    const keep = cityOpts.filter((o) => !state || o.dataset.state === state);
    const city = keep.some((o) => o.value === sel.value) ? sel.value : "";
    sel.replaceChildren(sel.options[0], ...keep);
    sel.value = city;
  }
  $("#sal-state").addEventListener("change", () => { filterCities(); render(); });
  $("#sal-city").addEventListener("change", () => {
    const c = cities[$("#sal-city").value];
    if (c && c.state) { $("#sal-state").value = c.state; filterCities(); }
    if (c && !$("#sal-gross").value) $("#sal-gross").value = c.median;
    render();
  });
  form.addEventListener("input", (ev) => { if (ev.target.tagName !== "SELECT") render(); });

  // From a job card: tools.html?gross=65000&city=Munich#salary
  const q = new URLSearchParams(location.search);
  if (+q.get("gross") > 0) $("#sal-gross").value = Math.round(+q.get("gross"));
  if (cities[q.get("city")]) {
    $("#sal-city").value = q.get("city");
    $("#sal-city").dispatchEvent(new Event("change"));
  }
  form.addEventListener("submit", (ev) => { ev.preventDefault(); render(); });

  function opts(gross) {
    const state = $("#sal-state").value;
    return { gross, taxClass: +$("#sal-class").value, children: $("#sal-children").checked, saxony: state === "DE-SN",
             church: $("#sal-church").checked ? (CHURCH_8.includes(state) ? 0.08 : 0.09) : false };
  }

  function render() {
    const gross = +$("#sal-gross").value;
    const out = $("#sal-result");
    if (!(gross > 0)) { out.hidden = true; return; }
    const r = netSalary(opts(gross));
    const row = (label, v, cls = "") => `<tr class="${cls}"><th scope="row">${label}</th><td>${eur(v / 12)}</td><td>${eur(v)}</td></tr>`;
    let html = `<div class="sal-net"><span>Your net pay</span><b>${eur(r.net / 12)}</b><small>per month · ${eur(r.net)} a year
      (${Math.round(100 * r.net / gross)}% of gross)</small></div>
    <table class="data sal-table"><thead><tr><th></th><th>Month</th><th>Year</th></tr></thead><tbody>
      ${row("Gross salary", gross, "sal-gross")}
      ${row("Income tax", -r.incomeTax)}${r.soli ? row("Solidarity surcharge", -r.soli) : ""}${r.churchTax ? row("Church tax", -r.churchTax) : ""}
      ${row("Pension insurance", -r.pension)}${row("Unemployment insurance", -r.unemployment)}
      ${row("Health insurance", -r.health)}${row("Care insurance", -r.care)}
      ${row("Net pay", r.net, "sal-total")}</tbody></table>`;
    const c = cities[$("#sal-city").value];
    if (c) {
      const m = netSalary(opts(c.median));
      const diff = Math.round(100 * (gross - c.median) / c.median);
      html += `<div class="sal-city"><h3>${c.city}: the typical salary</h3>
        <p>The median salary listed in ${c.n.toLocaleString("en-US")} English-speaking jobs in ${c.city} on Stellenly is
        <b>${eur(c.median)}</b> gross a year, about <b>${eur(m.net / 12)}</b> net a month with your settings.
        ${diff === 0 ? "Your salary is right at the median." : `Your salary is <b>${Math.abs(diff)}% ${diff > 0 ? "above" : "below"}</b> it.`}</p></div>`;
    }
    out.innerHTML = html;
    out.hidden = false;
  }
  render();
})();
