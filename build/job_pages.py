"""One page per open job at web/job/<id>.html, with schema.org JobPosting data for Google's job search.

Runs at deploy time (deploy-pages.yml), not in the daily build: ~2,000 pages change every day and
committing them would bloat the repository. Pages of jobs that closed simply aren't generated again,
so their URL returns 404, which is what Google asks for expired jobs.

    python build/job_pages.py                 # needs SUPABASE_URL + SUPABASE_ANON_KEY
    python build/job_pages.py --indexnow      # after deploying: tell Bing/Yandex/... about new job pages

Writes web/job/*.html and web/job-sitemap.xml (listed in robots.txt next to sitemap.xml).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from build_site import GERMAN_LABEL, NOW, SITE_URL, WEB, co_key, e, euro, page, parse_ts  # noqa: E402

OUT = WEB / "job"
VALID_DAYS = 45  # same as expire_jobs(): a job is retired 45 days after it was posted
INDEXNOW_KEY = "b6f1c2e94d7a4f3e8c5a0d2b9e7f6a31"  # public by design; served at /<key>.txt
COLS = ("id,url,title,company,city,location,remote_type,german_level,visa_sponsorship,relocation,salary_min,salary_max,"
        "seniority,is_agency,job_types,tags,description,posted_at,first_seen_at,source,insights")
REMOTE = {"remote_de": "Remote (Germany)", "remote_eu": "Remote (EU)", "hybrid": "Hybrid", "onsite": "On-site"}


def load_jobs() -> list[dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/jobs"
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    out, start, step = [], 0, 200  # descriptions + insights: 500 rows hit the 3 s anon timeout
    while True:
        r = requests.get(url, params={"select": COLS, "is_active": "eq.true", "order": "posted_at.desc"},
                         headers={"apikey": key, "Authorization": f"Bearer {key}", "Range": f"{start}-{start + step - 1}"},
                         timeout=120)
        r.raise_for_status()
        out += r.json()
        if len(r.json()) < step:
            return out
        start += step


def employment_type(j: dict) -> list[str]:
    blob = " ".join(j.get("job_types") or []).lower()
    types = set()
    if j.get("seniority") == "intern" or re.search(r"intern|praktik|werkstudent|student", blob):
        types.add("INTERN")
    if re.search(r"full[\s_-]?time|vollzeit|permanent", blob):
        types.add("FULL_TIME")
    if re.search(r"part[\s_-]?time|teilzeit", blob):
        types.add("PART_TIME")
    if re.search(r"contract|freelance|befristet", blob):
        types.add("CONTRACTOR")
    return sorted(types)


def description_html(text: str) -> str:
    """Plain text from enrich.html_to_text() -> paragraphs, bullet lists and short headings."""
    out, items = [], []

    def flush():
        if items:
            out.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^[•\-*–·]\s*(.+)", line)
        if m:
            items.append(m.group(1))
            continue
        flush()
        if len(line) <= 60 and not re.search(r"[.!?]$", line):
            out.append(f"<h3>{e(line.rstrip(':'))}</h3>")
        else:
            out.append(f"<p>{e(line)}</p>")
    flush()
    return "\n".join(out)


def job_posting(j: dict, desc_html: str, co: dict) -> dict:
    posted = parse_ts(j.get("posted_at") or j.get("first_seen_at"))
    ld = {
        "@context": "https://schema.org/", "@type": "JobPosting",
        "title": j["title"], "description": desc_html,
        "identifier": {"@type": "PropertyValue", "name": j["company"], "value": j["id"]},
        "datePosted": posted.date().isoformat(),
        "validThrough": (posted + dt.timedelta(days=VALID_DAYS)).isoformat(timespec="seconds"),
        "hiringOrganization": {"@type": "Organization", "name": j["company"],
                               **({"sameAs": co["w"]} if co.get("w") else {}),
                               **({"logo": f"{SITE_URL}/{co['l']}"} if co.get("l") else {})},
        "directApply": False,
        "url": f"{SITE_URL}/job/{j['id']}.html",
    }
    if types := employment_type(j):
        ld["employmentType"] = types
    if j.get("remote_type") in ("remote_de", "remote_eu"):
        ld["jobLocationType"] = "TELECOMMUTE"
        ld["applicantLocationRequirements"] = (
            [{"@type": "Country", "name": c} for c in ("Germany", "Austria", "Netherlands", "France", "Spain", "Italy", "Poland")]
            if j["remote_type"] == "remote_eu" else {"@type": "Country", "name": "Germany"})
    city = j.get("city") if j.get("city") not in (None, "", "Remote") else None
    if city or "jobLocationType" not in ld:
        ld["jobLocation"] = {"@type": "Place", "address": {"@type": "PostalAddress", "addressCountry": "DE",
                                                           **({"addressLocality": city} if city else {})}}
    if j.get("salary_min"):
        ld["baseSalary"] = {"@type": "MonetaryAmount", "currency": "EUR", "value": {
            "@type": "QuantitativeValue", "minValue": j["salary_min"], "maxValue": j.get("salary_max") or j["salary_min"],
            "unitText": "YEAR"}}
    return ld


def job_html(j: dict, co: dict, by_id: dict) -> str:
    cls, label = GERMAN_LABEL.get(j["german_level"], GERMAN_LABEL["not_mentioned"])
    badges = [f'<span class="badge {cls}">{label}</span>']
    if j.get("salary_min"):
        hi = j.get("salary_max")
        badges.append(f'<span class="badge ok">💶 {euro(j["salary_min"])}{"–" + euro(hi)[1:] if hi and hi != j["salary_min"] else ""} / year</span>')
    if j.get("visa_sponsorship"):
        badges.append('<span class="badge ok">🛂 Visa sponsorship</span>')
    if j.get("relocation"):
        badges.append('<span class="badge ok">📦 Relocation help</span>')
    if j.get("remote_type") in REMOTE:
        badges.append(f'<span class="badge">{REMOTE[j["remote_type"]]}</span>')
    if j.get("seniority") not in (None, "unspecified"):
        badges.append(f'<span class="badge">{e(j["seniority"].title())}</span>')
    if j.get("is_agency"):
        badges.append('<span class="badge warn">Recruiting agency</span>')
    ins = j.get("insights") or {}
    hints = "".join(f'<li class="hint {e(h.get("l", "info"))}"><b>{e(h.get("s", ""))}</b> {e(h.get("t", ""))}</li>'
                    for h in ins.get("hints") or [])
    similar = [by_id[i] for i in ins.get("similar") or [] if i in by_id][:6]
    sim_html = "".join(f'<li><a href="{s["id"]}.html">{e(s["title"])}</a> <span class="muted">· {e(s["company"])}'
                       f'{" · " + e(s["city"]) if s.get("city") else ""}</span></li>' for s in similar)
    company = (f'<a href="../{e(co["u"])}">{e(j["company"])}</a>' if co.get("u") else e(j["company"]))
    sc = co.get("sc")
    score = (f' <a class="score-chip inline" href="../{e(co["u"])}" title="Stellenly Hiring Score {sc["t"]}/100">★ {sc["t"] / 20:.1f}</a>'
             if sc and co.get("u") else "")
    place = j.get("city") or j.get("location") or "Germany"
    posted = parse_ts(j.get("posted_at") or j.get("first_seen_at")).date()
    desc = description_html(j.get("description") or "")
    ld = json.dumps(job_posting(j, desc, co), ensure_ascii=False).replace("</", "<\\/")
    body = f"""<nav class="crumbs"><a href="../index.html">Jobs</a> › {company}</nav>
<article class="job-page">
  <header class="job-page-head">
    {f'<img class="logo-md" src="../{e(co["l"])}" alt="" width="48" height="48">' if co.get("l") else ""}
    <div><h1>{e(j['title'])}</h1>
      <p class="job-meta"><span class="company">{company}</span>{score} · {e(place)} · posted {posted:%d %b %Y}</p></div>
  </header>
  <div class="badges">{"".join(badges)}</div>
  <p class="job-page-cta"><a class="btn primary big" href="{e(j['url'])}" target="_blank" rel="noopener nofollow"
     data-goatcounter-click="apply" data-goatcounter-title="{e(j['company'])}">Apply on the employer's site ↗</a>
     <a class="btn" href="../index.html?q={e(requests.utils.quote(j['company']))}">More jobs at {e(j['company'])}</a></p>
  {f'<ul class="job-hints">{hints}</ul>' if hints else ""}
  <div class="article job-desc">{desc}</div>
  <p class="muted small">We show this posting as published by the employer. Always check the details on the original posting
  before you apply. <a href="../how-it-works.html">How we read job postings</a>.</p>
  {f'<section class="jd-card similar"><h2>Similar jobs</h2><ul class="link-list">{sim_html}</ul></section>' if sim_html else ""}
</article>"""
    desc_meta = (f"{j['company']} is hiring in {place}. {label}"
                 + (f", {euro(j['salary_min'])}+ a year" if j.get("salary_min") else "") + ". Apply in English.")
    return page(f"{j['title']} at {j['company']}", desc_meta, body, f"job/{j['id']}.html", 1,
                extra_head=f'<script type="application/ld+json">{ld}</script>', main_class="content-page")


def indexnow(urls: list[str]) -> None:
    host = re.sub(r"^https?://", "", SITE_URL).split("/")[0]
    for i in range(0, len(urls), 10000):
        r = requests.post("https://api.indexnow.org/indexnow", timeout=60, json={
            "host": host, "key": INDEXNOW_KEY, "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt", "urlList": urls[i:i + 10000]})
        print(f"IndexNow: {len(urls[i:i + 10000])} URLs -> HTTP {r.status_code}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexnow", action="store_true",
                    help="only ping IndexNow with job pages first seen in the last 2 days (run after the deploy)")
    args = ap.parse_args()

    jobs = load_jobs()
    if args.indexnow:
        recent = NOW - dt.timedelta(days=2)
        new = [f"{SITE_URL}/job/{j['id']}.html" for j in jobs if parse_ts(j.get("first_seen_at")) >= recent]
        try:
            indexnow([f"{SITE_URL}/", f"{SITE_URL}/job-sitemap.xml"] + new)
        except requests.RequestException as err:  # never fail the deploy over a ping
            print(f"! IndexNow failed: {err}")
        return

    index = json.loads((WEB / "data" / "companies-index.json").read_text(encoding="utf-8"))
    by_id = {j["id"]: j for j in jobs}
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.html"):
        old.unlink()
    for j in jobs:
        (OUT / f"{j['id']}.html").write_text(job_html(j, index.get(co_key(j["company"]), {}), by_id), encoding="utf-8")
    (WEB / f"{INDEXNOW_KEY}.txt").write_text(INDEXNOW_KEY, encoding="utf-8")
    urls = "".join(f"<url><loc>{SITE_URL}/job/{j['id']}.html</loc>"
                   f"<lastmod>{parse_ts(j.get('first_seen_at') or j.get('posted_at')).date().isoformat()}</lastmod></url>"
                   for j in jobs)
    (WEB / "job-sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n'
                                         f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n',
                                         encoding="utf-8")
    print(f"Wrote {len(jobs)} job pages")


if __name__ == "__main__":
    main()
