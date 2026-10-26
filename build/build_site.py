"""Static site builder: blog, weekly job-market report, SEO landing pages,
resources page, sitemap. Runs daily in GitHub Actions so the site keeps
updating itself.

    python build/build_site.py                          # live data from Supabase
    python build/build_site.py --jobs-file build/sample_jobs.json   # offline preview

Env: SUPABASE_URL, SUPABASE_ANON_KEY (public key is enough), SITE_URL.

Shortcodes you can use inside blog posts (content/blog/*.md):
    {{resources:banking}}                 resource cards of one category
    {{jobs:tag=no-german,limit=5}}        latest matching jobs (refreshed daily)
    {{jobs:city=Berlin,limit=5}}
    {{stat:active}} {{stat:no_german_pct}} {{stat:salary_pct}} {{stat:new_7d}}
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import statistics
from collections import Counter
from pathlib import Path

import markdown
import requests

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
CONTENT = ROOT / "content"
SITE = json.loads((Path(__file__).parent / "site.json").read_text())
SITE_URL = os.environ.get("SITE_URL", SITE["site_url"]).rstrip("/")
NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date()
e = html.escape


# ---------------------------------------------------------------- data
def load_jobs(jobs_file: str | None) -> list[dict]:
    if jobs_file:
        return json.loads(Path(jobs_file).read_text())
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/jobs"
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    cols = ("id,url,title,company,city,remote_type,german_level,visa_sponsorship,relocation,"
            "salary_min,salary_max,seniority,is_agency,tags,posted_at,first_seen_at")
    out, start, step = [], 0, 1000
    while True:
        r = requests.get(url, params={"select": cols, "is_active": "eq.true", "order": "posted_at.desc"},
                         headers={"apikey": key, "Authorization": f"Bearer {key}",
                                  "Range": f"{start}-{start + step - 1}"}, timeout=60)
        r.raise_for_status()
        batch = r.json()
        out += batch
        if len(batch) < step:
            return out
        start += step


def parse_ts(s: str | None) -> dt.datetime:
    if not s:
        return NOW
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


META_TAGS = {"intern", "junior", "mid", "senior", "lead", "no-german", "visa-sponsorship", "remote", "relocation"}


def compute_stats(jobs: list[dict]) -> dict:
    n = len(jobs) or 1
    german = Counter(j["german_level"] for j in jobs)
    with_salary = [j for j in jobs if j.get("salary_min")]
    mid = lambda j: (j["salary_min"] + (j.get("salary_max") or j["salary_min"])) / 2  # noqa: E731
    by_tag: dict[str, list[float]] = {}
    for j in with_salary:
        for t in j.get("tags") or []:
            if t in META_TAGS:
                continue
            by_tag.setdefault(t, []).append(mid(j))
    week_ago = NOW - dt.timedelta(days=7)
    return {
        "active": len(jobs),
        "new_7d": sum(parse_ts(j.get("first_seen_at")) >= week_ago for j in jobs),
        "no_german_pct": round(100 * (german["not_required"] + german["nice_to_have"]) / n),
        "german_required_pct": round(100 * german["required"] / n),
        "german": dict(german),
        "salary_pct": round(100 * len(with_salary) / n),
        "median_salary": int(statistics.median(mid(j) for j in with_salary)) if with_salary else None,
        "salary_by_tag": sorted(((t, int(statistics.median(v)), len(v)) for t, v in by_tag.items() if len(v) >= 5),
                                key=lambda x: -x[1])[:12],
        "visa": sum(bool(j.get("visa_sponsorship")) for j in jobs),
        "remote_pct": round(100 * sum(j["remote_type"] in ("remote_de", "remote_eu") for j in jobs) / n),
        "cities": Counter(j["city"] for j in jobs if j.get("city") and j["city"] != "Remote").most_common(15),
        "tags": Counter(t for j in jobs for t in (j.get("tags") or [])).most_common(40),
        "companies": Counter(j["company"] for j in jobs if not j.get("is_agency")).most_common(10),
    }


# ---------------------------------------------------------------- html helpers
def page(title: str, description: str, body: str, path: str, depth: int, extra_head: str = "",
         affiliate_note: bool = False) -> str:
    up = "../" * depth
    canonical = f"{SITE_URL}/{path}".replace("/index.html", "/")
    note = ('<p class="affiliate-note">Some links on this page are partner links: if you sign up, we may earn a small '
            'commission at no extra cost to you. It keeps this site free. We only list services we would recommend anyway.</p>'
            if affiliate_note else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} — {e(SITE['site_name'])}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="website">
<link rel="alternate" type="application/rss+xml" title="Guides" href="{up}blog/feed.xml">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🇩🇪</text></svg>">
<link rel="stylesheet" href="{up}style.css">
<script>try{{var t=localStorage.getItem("ejg.theme");if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
{extra_head}
</head>
<body>
<header class="site-header"><div class="wrap header-row">
  <a class="brand" href="{up}index.html">{e(SITE['site_name'])}</a>
  <nav class="header-actions">
    <a class="btn ghost" href="{up}index.html">Search jobs</a>
    <a class="btn ghost" href="{up}resources.html">Resources</a>
    <a class="btn ghost" href="{up}blog/index.html">Guides</a>
    <a class="btn support" href="{e(SITE['kofi_url'])}" target="_blank" rel="noopener">☕ Support</a>
  </nav>
</div></header>
<main class="wrap content-page">
{body}
{note}
</main>
<footer class="site-footer"><div class="wrap footer-row">
  <span>Updated {TODAY.isoformat()} · Jobs from public job APIs and company career pages.</span>
  <nav><a href="{up}impressum.html">Impressum</a><a href="{up}privacy.html">Privacy</a><a href="{up}resources.html">Resources</a></nav>
</div></footer>
</body>
</html>
"""


def slugify(s: str) -> str:
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def euro(n: int | float | None) -> str:
    return f"€{round(n / 1000)}k" if n else "—"


GERMAN_LABEL = {"not_required": ("ok", "No German needed"), "nice_to_have": ("info", "German nice to have"),
                "required": ("bad", "German required"), "not_mentioned": ("", "German not mentioned")}


def job_list_html(jobs: list[dict], up: str) -> str:
    if not jobs:
        return '<p class="muted">No matching jobs right now — check back tomorrow.</p>'
    rows = []
    for j in jobs:
        cls, label = GERMAN_LABEL.get(j["german_level"], GERMAN_LABEL["not_mentioned"])
        sal = (f'<span class="badge ok">💶 {euro(j["salary_min"])}'
               f'{"–" + euro(j["salary_max"])[1:] if j.get("salary_max") and j["salary_max"] != j["salary_min"] else ""}</span>'
               if j.get("salary_min") else "")
        visa = '<span class="badge ok">🛂 Visa sponsorship</span>' if j.get("visa_sponsorship") else ""
        rows.append(f"""<li class="job">
  <h3 class="job-title"><a href="{e(j['url'])}" target="_blank" rel="noopener nofollow">{e(j['title'])}</a></h3>
  <div class="job-meta"><span class="company">{e(j['company'])}</span> · {e(j.get('city') or 'Germany')} · {parse_ts(j.get('posted_at')).date().isoformat()}</div>
  <div class="badges"><span class="badge {cls}">{label}</span>{sal}{visa}</div>
</li>""")
    return f'<ol class="results static">{"".join(rows)}</ol>'


def resource_cards(cat: dict) -> tuple[str, bool]:
    cards, has_aff = [], False
    for it in cat["items"]:
        aff = bool(it.get("affiliate_url"))
        has_aff |= aff
        href = it["affiliate_url"] or it["url"]
        rel = "sponsored noopener" if aff else "noopener"
        badge = '<span class="badge info">Partner link</span>' if aff else ""
        cards.append(f"""<a class="resource" href="{e(href)}" target="_blank" rel="{rel}">
  <b>{e(it['name'])} ↗</b> {badge}<span>{e(it['desc'])}</span></a>""")
    return f'<div class="resource-grid">{"".join(cards)}</div>', has_aff


# ---------------------------------------------------------------- builders
def build_resources(resources: dict) -> None:
    parts, any_aff = [], False
    toc = " · ".join(f'<a href="#{c["id"]}">{e(c["title"])}</a>' for c in resources["categories"])
    for c in resources["categories"]:
        cards, aff = resource_cards(c)
        any_aff |= aff
        parts.append(f'<section id="{c["id"]}"><h2>{e(c["title"])}</h2><p class="muted">{e(c["intro"])}</p>{cards}</section>')
    body = (f'<h1>Resources for moving to and working in Germany</h1>'
            f'<p class="lead">Hand-picked, English-friendly services and the official sources we trust. {toc}</p>'
            + "".join(parts))
    (WEB / "resources.html").write_text(page(
        "Resources for working in Germany", "Visa, Blue Card, bank account, health insurance, learning German, "
        "salary and housing: the English-friendly services and official sources internationals need.",
        body, "resources.html", 0, affiliate_note=any_aff))


def render_shortcodes(md: str, jobs: list[dict], stats: dict, resources: dict, up: str) -> tuple[str, bool]:
    used_aff = False
    cats = {c["id"]: c for c in resources["categories"]}

    def res(m):
        nonlocal used_aff
        c = cats.get(m.group(1).strip())
        if not c:
            return ""
        cards, aff = resource_cards(c)
        used_aff |= aff
        return f"\n\n<div markdown=\"0\">{cards}</div>\n\n"

    def job_sc(m):
        args = dict(kv.split("=", 1) for kv in m.group(1).split(",") if "=" in kv)
        sel = jobs
        if "tag" in args:
            sel = [j for j in sel if args["tag"] in (j.get("tags") or [])]
        if "city" in args:
            sel = [j for j in sel if j.get("city") == args["city"]]
        if args.get("salary") == "1":
            sel = [j for j in sel if j.get("salary_min")]
        sel = sorted(sel, key=lambda j: j.get("posted_at") or "", reverse=True)[: int(args.get("limit", 5))]
        q = "&".join(f"{'tags' if k == 'tag' else k}={v}" for k, v in args.items() if k in ("tag", "city"))
        more = f'<p><a class="btn" href="{up}index.html?{e(q)}">See all matching jobs →</a></p>'
        return f"\n\n<div markdown=\"0\">{job_list_html(sel, up)}{more}<p class=\"muted small\">List updated {TODAY.isoformat()}.</p></div>\n\n"

    def stat(m):
        v = stats.get(m.group(1).strip())
        return f"{v:,}" if isinstance(v, int) else str(v if v is not None else "—")

    md = re.sub(r"\{\{resources:([^}]+)\}\}", res, md)
    md = re.sub(r"\{\{jobs:([^}]*)\}\}", job_sc, md)
    md = re.sub(r"\{\{stat:([^}]+)\}\}", stat, md)
    return md, used_aff


def read_post(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        body = m.group(2)
    meta.setdefault("slug", path.stem)
    return meta, body


def article_html(meta: dict, body_html: str, extra: str = "") -> str:
    reviewed = f' · Last reviewed {e(meta["reviewed"])}' if meta.get("reviewed") else ""
    return (f'<article class="article"><p class="muted small"><a href="index.html">← All guides</a></p>'
            f'<h1>{e(meta["title"])}</h1><p class="muted small">Published {e(meta.get("date", ""))}{reviewed}</p>'
            f'{body_html}{extra}'
            f'<aside class="cta"><b>Looking for an English-speaking job?</b> '
            f'<a class="btn primary" href="../index.html">Search jobs with German level &amp; salary up front →</a></aside>'
            f'</article>')


def build_blog(jobs: list[dict], stats: dict, resources: dict) -> list[dict]:
    out_dir = WEB / "blog"
    out_dir.mkdir(exist_ok=True)
    posts = []
    for p in sorted((CONTENT / "blog").glob("*.md")):
        meta, body = read_post(p)
        if meta.get("draft") == "true":
            continue
        body, aff = render_shortcodes(body, jobs, stats, resources, "../")
        body_html = markdown.markdown(body, extensions=["tables", "fenced_code", "md_in_html"])
        ld = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": meta["title"],
                         "datePublished": meta.get("date"), "dateModified": meta.get("reviewed") or meta.get("date"),
                         "author": {"@type": "Person", "name": SITE["author"]}})
        (out_dir / f"{meta['slug']}.html").write_text(page(
            meta["title"], meta.get("description", ""), article_html(meta, body_html),
            f"blog/{meta['slug']}.html", 1, f'<script type="application/ld+json">{ld}</script>', affiliate_note=aff))
        posts.append({**meta, "path": f"blog/{meta['slug']}.html"})
    return posts


def build_report(jobs: list[dict], stats: dict) -> dict:
    """Weekly job-market report. Rebuilt every day during the ISO week, frozen after."""
    year, week, _ = TODAY.isocalendar()
    slug = f"job-market-{year}-w{week:02d}"
    hist_path = CONTENT / "reports" / "history.json"
    hist_path.parent.mkdir(exist_ok=True)
    history = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    snap = {k: stats[k] for k in ("active", "new_7d", "no_german_pct", "salary_pct", "median_salary", "visa", "remote_pct")}
    history[f"{year}-W{week:02d}"] = snap
    hist_path.write_text(json.dumps(history, indent=1, sort_keys=True))
    prev_key = sorted(k for k in history if k < f"{year}-W{week:02d}")
    prev = history[prev_key[-1]] if prev_key else None

    def delta(k, fmt="{:+,}"):
        if not prev or prev.get(k) is None or snap.get(k) is None:
            return ""
        d = snap[k] - prev[k]
        return f' <span class="muted small">({fmt.format(d)} vs last week)</span>' if d else ""

    rows_city = "".join(f"<tr><td>{e(c)}</td><td>{n}</td></tr>" for c, n in stats["cities"][:10])
    rows_sal = "".join(f"<tr><td>#{e(t)}</td><td>{euro(m)}</td><td>{n}</td></tr>" for t, m, n in stats["salary_by_tag"])
    rows_co = "".join(f"<tr><td>{e(c)}</td><td>{n}</td></tr>" for c, n in stats["companies"])
    g = stats["german"]
    total = stats["active"] or 1
    body = f"""
<h2>Key numbers</h2>
<div class="kpis">
  <div><b>{stats['active']:,}</b><span>English-friendly jobs open{delta('active')}</span></div>
  <div><b>{stats['new_7d']:,}</b><span>new in the last 7 days{delta('new_7d')}</span></div>
  <div><b>{stats['no_german_pct']}%</b><span>don't require German{delta('no_german_pct', '{:+} pts')}</span></div>
  <div><b>{stats['salary_pct']}%</b><span>show a salary{delta('salary_pct', '{:+} pts')}</span></div>
  <div><b>{euro(stats['median_salary'])}</b><span>median listed salary</span></div>
  <div><b>{stats['visa']:,}</b><span>mention visa sponsorship</span></div>
</div>
<h2>How much German do employers ask for?</h2>
<table class="data"><tbody>
<tr><td>Not required (explicitly)</td><td>{round(100 * g.get('not_required', 0) / total)}%</td></tr>
<tr><td>Nice to have</td><td>{round(100 * g.get('nice_to_have', 0) / total)}%</td></tr>
<tr><td>Not mentioned</td><td>{round(100 * g.get('not_mentioned', 0) / total)}%</td></tr>
<tr><td>Required</td><td>{round(100 * g.get('required', 0) / total)}%</td></tr>
</tbody></table>
<p class="muted small">Based on the wording of each English-language posting. "Not mentioned" often still means German helps, so ask in the interview.</p>
<h2>Where the jobs are</h2>
<table class="data"><thead><tr><th>City</th><th>Open jobs</th></tr></thead><tbody>{rows_city}</tbody></table>
{f'<h2>Median listed salary by field</h2><table class="data"><thead><tr><th>Tag</th><th>Median</th><th>Jobs with salary</th></tr></thead><tbody>{rows_sal}</tbody></table><p class="muted small">Only fields with at least 5 salaries listed. Midpoint of each listed range, gross per year.</p>' if rows_sal else ''}
<h2>Companies hiring the most (direct employers)</h2>
<table class="data"><thead><tr><th>Company</th><th>Open jobs</th></tr></thead><tbody>{rows_co}</tbody></table>
<h2>Fresh jobs that don't need German</h2>
{job_list_html(sorted([j for j in jobs if j['german_level'] in ('not_required', 'nice_to_have')], key=lambda j: j.get('posted_at') or '', reverse=True)[:8], '../')}
"""
    meta = {"title": f"English-speaking job market in Germany — week {week}, {year}",
            "description": f"Weekly numbers: {stats['active']:,} English-friendly jobs, {stats['no_german_pct']}% without German, "
                           f"median listed salary {euro(stats['median_salary'])}, top cities and companies hiring.",
            "date": TODAY.isoformat(), "slug": slug}
    (WEB / "blog" / f"{slug}.html").write_text(page(
        meta["title"], meta["description"], article_html(meta, body), f"blog/{slug}.html", 1))
    return {**meta, "path": f"blog/{slug}.html", "report": True}


def build_landing_pages(jobs: list[dict], stats: dict) -> list[str]:
    out = WEB / "jobs"
    out.mkdir(exist_ok=True)
    paths, links = [], []
    items = [("city", c, f"English-speaking jobs in {c}") for c, n in stats["cities"] if n >= 5]
    items += [("tag", t, f"English-speaking {t.replace('-', ' ')} jobs in Germany") for t, n in stats["tags"] if n >= 5]
    for kind, val, title in items:
        sel = [j for j in jobs if (j.get("city") == val if kind == "city" else val in (j.get("tags") or []))]
        sel.sort(key=lambda j: j.get("posted_at") or "", reverse=True)
        s = compute_stats(sel)
        slug = f"{kind}-{slugify(val)}"
        q = f"city={val}" if kind == "city" else f"tags={val}"
        body = f"""<h1>{e(title)}</h1>
<p class="lead">{s['active']:,} open jobs right now · {s['no_german_pct']}% don't require German ·
{s['salary_pct']}% show a salary{f" · median {euro(s['median_salary'])}" if s['median_salary'] else ""}.</p>
<p><a class="btn primary" href="../index.html?{e(q)}">Filter these jobs by German level, salary &amp; visa →</a></p>
<h2>Latest jobs</h2>
{job_list_html(sel[:30], '../')}
<p class="muted small">Updated daily. Always apply on the original posting.</p>"""
        (out / f"{slug}.html").write_text(page(title, f"{s['active']} English-speaking {('jobs in ' + val) if kind == 'city' else val + ' jobs in Germany'}: "
                                                      f"German requirement, salary and visa sponsorship shown for every job.",
                                                body, f"jobs/{slug}.html", 1))
        paths.append(f"jobs/{slug}.html")
        links.append(f'<li><a href="{slug}.html">{e(title)}</a> <span class="muted">({len(sel)})</span></li>')
    (out / "index.html").write_text(page("Browse English-speaking jobs in Germany", "By city and by field.",
                                         f"<h1>Browse jobs</h1><ul class=\"link-list\">{''.join(links)}</ul>", "jobs/index.html", 1))
    return paths + ["jobs/index.html"]


def build_blog_index(posts: list[dict], report: dict) -> None:
    guides = sorted([p for p in posts], key=lambda p: p.get("date", ""), reverse=True)
    reports = sorted((WEB / "blog").glob("job-market-*.html"), reverse=True)
    li = "".join(f'<li><a href="{p["slug"]}.html"><b>{e(p["title"])}</b></a><br><span class="muted">{e(p.get("description", ""))}</span></li>'
                 for p in guides)
    rep = "".join(f'<li><a href="{r.name}">{e(r.stem.replace("job-market-", "Job market ").replace("-w", " week "))}</a></li>'
                  for r in reports[:12])
    body = f"""<h1>Guides for working in Germany</h1>
<p class="lead">Practical, English-language guides for internationals — plus a job-market report that updates every day.</p>
<aside class="cta"><b>This week:</b> <a href="{report['slug']}.html">{e(report['title'])}</a></aside>
<ul class="post-list">{li}</ul>
<h2>Weekly job-market reports</h2><ul class="link-list">{rep}</ul>"""
    (WEB / "blog" / "index.html").write_text(page("Guides & job-market reports", "Guides about the Blue Card, German "
                                                   "requirements, salaries and your first weeks in Germany.", body, "blog/index.html", 1))

    items = "".join(f"""<item><title>{e(p['title'])}</title><link>{SITE_URL}/{p['path']}</link>
<guid>{SITE_URL}/{p['path']}</guid><pubDate>{dt.datetime.fromisoformat(p.get('date') or TODAY.isoformat()).strftime('%a, %d %b %Y 00:00:00 +0000')}</pubDate>
<description>{e(p.get('description', ''))}</description></item>""" for p in [report] + guides)
    (WEB / "blog" / "feed.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{e(SITE['site_name'])} — Guides</title><link>{SITE_URL}/blog/</link>
<description>Guides and weekly job-market reports</description>{items}</channel></rss>""")


def build_sitemap(paths: list[str]) -> None:
    urls = "".join(f"<url><loc>{SITE_URL}/{p.replace('index.html', '')}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>"
                   for p in sorted(set(paths)))
    (WEB / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n'
                                     f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    (WEB / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs-file")
    args = ap.parse_args()

    jobs = load_jobs(args.jobs_file)
    stats = compute_stats(jobs)
    resources = json.loads((CONTENT / "resources.json").read_text())

    build_resources(resources)
    posts = build_blog(jobs, stats, resources)
    report = build_report(jobs, stats)
    build_blog_index(posts, report)
    landing = build_landing_pages(jobs, stats)
    reports = [f"blog/{p.name}" for p in (WEB / "blog").glob("job-market-*.html")]
    build_sitemap(["index.html", "resources.html", "blog/index.html"] + [p["path"] for p in posts] + reports + landing)
    print(f"Built: {len(posts)} guides, report {report['slug']}, {len(landing)} landing pages, "
          f"{stats['active']} jobs ({stats['no_german_pct']}% no German)")


if __name__ == "__main__":
    main()
