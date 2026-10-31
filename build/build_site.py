"""Static site builder: blog, weekly job-market report, SEO landing pages,
resources page, sitemap. Runs daily in GitHub Actions so the site keeps
updating itself.

    python build/build_site.py                          # live data from Supabase
    python build/build_site.py --jobs-file tests/fixtures/sample_jobs.json   # offline preview

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
import math
import os
import re
import statistics
import sys
import unicodedata
import zlib
from collections import Counter
from pathlib import Path

import markdown
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))
import geo  # noqa: E402  (cached city coordinates for the companies map)
from enrich import in_germany, normalize_city  # noqa: E402
from covers import ICONS, cover_svg  # noqa: E402
import how_it_works  # noqa: E402
import coats_of_arms  # noqa: E402
import germany_map  # noqa: E402
import skill_check  # noqa: E402
WEB = ROOT / "web"
CONTENT = ROOT / "content"
# Skill check: on locally, off in production until it is redesigned (GitHub repository variable SKILL_CHECK=1 turns it on).
SKILL_CHECK = os.environ.get("SKILL_CHECK", "1") == "1"
SITE = json.loads((ROOT / "content" / "site.json").read_text(encoding="utf-8"))
SITE_URL = os.environ.get("SITE_URL", SITE["site_url"]).rstrip("/")
import zoneinfo  # noqa: E402
BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")
NOW = dt.datetime.now(BERLIN)  # dates on the site are German time
TODAY = NOW.date()
e = html.escape
# Cookieless visitor counts (GoatCounter); empty in content/site.json = no analytics on generated pages.
ANALYTICS = (f'<script data-goatcounter="{html.escape(SITE["goatcounter"])}" async src="https://gc.zgo.at/count.js"></script>'
             if SITE.get("goatcounter") else "")


# ---------------------------------------------------------------- data
def load_jobs(jobs_file: str | None) -> list[dict]:
    if jobs_file:
        return json.loads(Path(jobs_file).read_text(encoding="utf-8"))
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/jobs"
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    cols = ("id,url,title,company,city,remote_type,german_level,visa_sponsorship,relocation,"
            "salary_min,salary_max,seniority,is_agency,tags,posted_at,first_seen_at,repost_count,source,"
            "ai_summary:insights->ai->>summary")
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
# Discord and Telegram cards, fixed in the bottom-right corner (same markup in web/index.html). Each has its own ×,
# remembered per browser (ejg.dcHidden / ejg.tgHidden).
TG_FLOAT = """<div class="float-stack">
<div class="tg-float dc-float" data-hide="dcHidden">
  <a class="tg-float-card" href="{dc}" target="_blank" rel="noopener" data-goatcounter-click="discord-float" aria-label="Join the Stellenly community on Discord">
    <svg class="tg-logo" viewBox="0 0 24 24" width="40" height="40" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#5865F2"/><path fill="#fff" transform="translate(5.5 5.5) scale(.54)" d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.865-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.74 19.74 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.1 13.1 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
    <span class="tg-float-text"><b>Join our Discord</b><small>Report bugs, share ideas, get news</small></span>
  </a>
  <button type="button" class="tg-float-close" aria-label="Hide the Discord card">×</button>
</div>
<div class="tg-float" id="tg-float" data-hide="tgHidden">
  <a class="tg-float-card" href="{tg}" target="_blank" rel="noopener" data-goatcounter-click="telegram-float" aria-label="Join the Stellenly Jobs channel on Telegram">
    <svg class="tg-logo" viewBox="0 0 24 24" width="40" height="40" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#229ED9"/><path fill="#fff" d="M5.4 11.8l11.6-4.5c.5-.2 1 .1.8.9l-2 9.3c-.1.6-.5.8-1.1.5l-3-2.2-1.4 1.4c-.2.2-.3.3-.6.3l.2-3.1 5.6-5.1c.2-.2 0-.3-.4-.1l-6.9 4.4-3-.9c-.6-.2-.6-.6.2-.9z"/></svg>
    <span class="tg-float-text"><b>Join us on Telegram</b><small>New English-speaking jobs every day</small></span>
  </a>
  <button type="button" class="tg-float-close" aria-label="Hide the Telegram card">×</button>
</div>
</div>
<script>document.querySelectorAll(".tg-float").forEach(function(w){{var k="ejg."+w.dataset.hide;try{{if(localStorage.getItem(k))w.hidden=true;}}catch(e){{}}
w.querySelector(".tg-float-close").addEventListener("click",function(){{w.hidden=true;try{{localStorage.setItem(k,"1");}}catch(e){{}}}});}});</script>
""".format(tg=html.escape(SITE["telegram_url"]), dc=html.escape(SITE["discord_url"]))


def page(title: str, description: str, body: str, path: str, depth: int, extra_head: str = "",
         affiliate_note: bool = False, main_class: str = "content-page") -> str:
    up = "../" * depth
    skill_link = f'<a href="{up}skill-check.html">Skill check</a>' if SKILL_CHECK else ""
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
<meta property="og:image" content="{SITE_URL}/img/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" title="Guides" href="{up}blog/feed.xml">
<link rel="icon" href="{up}img/logo.svg" type="image/svg+xml">
<link rel="icon" href="{up}favicon-48.png" sizes="48x48" type="image/png">
<link rel="apple-touch-icon" href="{up}apple-touch-icon.png">
<link rel="manifest" href="{up}manifest.webmanifest">
<meta name="theme-color" content="#0a2463">
<link rel="stylesheet" href="{up}css/style.css">
{ANALYTICS}
<script>try{{var t=localStorage.getItem("ejg.theme");if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
{extra_head}
</head>
<body>
<header class="site-header"><div class="wrap header-row">
  <a class="brand" href="{up}index.html"><img class="brand-logo" src="{up}img/logo.svg" alt="" width="32" height="32"><span>{e(SITE['site_name'])}</span></a>
  <nav class="header-actions" aria-label="Main">
    <a class="btn ghost nav-link" href="{up}index.html">Jobs</a>
    <a class="btn ghost nav-link" href="{up}companies.html">Companies</a>
    <a class="btn ghost nav-link" href="{up}jobs/index.html">Cities</a>
    <a class="btn ghost nav-link" href="{up}blog/index.html">Guides</a>
    <details class="nav-more"><summary class="btn ghost">More</summary><div class="nav-menu">
      <a class="m-only" href="{up}index.html">Jobs</a><a class="m-only" href="{up}companies.html">Companies</a>
      <a class="m-only" href="{up}jobs/index.html">Cities</a><a class="m-only" href="{up}blog/index.html">Guides</a>
      <a href="{up}how-it-works.html">How it works</a>{skill_link}<a href="{up}resources.html">Resources</a>
      <a class="m-only" href="{e(SITE['instagram_url'])}" target="_blank" rel="noopener">Instagram</a><a class="m-only" href="{e(SITE['facebook_url'])}" target="_blank" rel="noopener">Facebook</a></div></details>
  </nav>
  <div class="header-end"><a class="btn ghost icon social ig" href="{e(SITE['instagram_url'])}" target="_blank" rel="noopener" aria-label="Stellenly on Instagram" title="Instagram"><svg class="footer-logo ig" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1.3" fill="currentColor"/></svg></a><a class="btn ghost icon social fb" href="{e(SITE['facebook_url'])}" target="_blank" rel="noopener" aria-label="Stellenly on Facebook" title="Facebook"><svg class="footer-logo fb" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M13.5 21v-7.5h2.6l.4-3h-3V8.7c0-.9.3-1.5 1.6-1.5h1.6V4.5c-.3 0-1.2-.1-2.3-.1-2.3 0-3.8 1.4-3.8 3.9v2.2H8v3h2.6V21z"/></svg></a>
    <button type="button" class="btn ghost icon" id="theme-toggle" aria-label="Toggle dark mode" title="Light / dark">🌓</button>
    <a class="btn support" href="{e(SITE['kofi_url'])}" target="_blank" rel="noopener">Support us</a></div>
</div></header>
<main class="wrap {main_class}">
{body}
{note}
</main>
<footer class="site-footer"><div class="wrap footer-row">
  <span>Updated {TODAY.isoformat()} · Jobs from public job APIs and company career pages.</span>
  <nav><a class="footer-discord" href="{e(SITE['discord_url'])}" target="_blank" rel="noopener"><svg class="footer-logo" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.865-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.74 19.74 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.1 13.1 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>Discord</a><a class="footer-discord" href="{e(SITE['instagram_url'])}" target="_blank" rel="noopener"><svg class="footer-logo ig" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1.3" fill="currentColor"/></svg>Instagram</a><a class="footer-discord" href="{e(SITE['facebook_url'])}" target="_blank" rel="noopener"><svg class="footer-logo fb" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M13.5 21v-7.5h2.6l.4-3h-3V8.7c0-.9.3-1.5 1.6-1.5h1.6V4.5c-.3 0-1.2-.1-2.3-.1-2.3 0-3.8 1.4-3.8 3.9v2.2H8v3h2.6V21z"/></svg>Facebook</a><a href="{e(SITE['telegram_url'])}" target="_blank" rel="noopener">Telegram</a><a href="{up}jobs/index.html">Jobs by location</a><a href="{up}impressum.html">Impressum</a><a href="{up}privacy.html">Privacy</a><a href="{up}resources.html">Resources</a></nav>
</div></footer>
{TG_FLOAT}
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
  <h3 class="job-title"><a href="{up}job/{e(j['id'])}.html">{e(j['title'])}</a></h3>
  <div class="job-meta"><span class="company">{e(j['company'])}</span> · {e(j.get('city') or 'Germany')} · {parse_ts(j.get('posted_at')).date().isoformat()}</div>
  <div class="badges"><span class="badge {cls}">{label}</span>{sal}{visa}</div>
</li>""")
    return f'<ol class="results static">{"".join(rows)}</ol>'


def mono_html(name: str, cls: str = "logo-sm") -> str:
    """Coloured initials when we have no logo (same look as in app.js)."""
    words = re.sub(r"\(.*?\)", "", name).split() or ["?"]
    initials = (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1:2])).upper()
    hue = sum(ord(ch) * 31 ** i for i, ch in enumerate(name)) % 360
    return f'<span class="logo mono {cls}" style="--h:{hue}" aria-hidden="true">{e(initials)}</span>'


def resource_cards(cat: dict, up: str = "") -> tuple[str, bool]:
    cards, has_aff = [], False
    for it in cat["items"]:
        aff = bool(it.get("affiliate_url"))
        has_aff |= aff
        href = it["affiliate_url"] or it["url"]
        rel = "sponsored noopener" if aff else "noopener"
        badge = ('<span class="badge info">Partner link</span>' if aff
                 else '<span class="badge ok">Official</span>' if "official" in (it.get("program") or "") else "")
        logo = fetch_logo(f"res-{slugify(it['name'])}", it["url"])
        logo_html = f'<img class="logo logo-sm" src="{up}{logo}" alt="" loading="lazy">' if logo else mono_html(it["name"])
        domain = re.sub(r"^https?://(www\.)?", "", it["url"]).split("/")[0]
        cards.append(f"""<a class="resource" href="{e(href)}" target="_blank" rel="{rel}" data-goatcounter-click="resource-{slugify(it['name'])}" data-goatcounter-title="{e(it['name'])}">
  <span class="res-top">{logo_html}<span class="res-name"><b>{e(it['name'])}</b><small>{e(domain)}</small></span></span>
  <span class="res-desc">{e(it['desc'])}</span><span class="res-foot"><span class="res-go">Visit site ↗</span>{badge}</span></a>""")
    return f'<div class="resource-grid">{"".join(cards)}</div>', has_aff


# ---------------------------------------------------------------- guides: sections, covers, dates
SECTIONS = {s["id"]: s for s in json.loads((CONTENT / "sections.json").read_text(encoding="utf-8"))["sections"]}
OTHER_SECTION = {"id": "guides", "title": "Guides", "hue": 222, "icon": "book", "resources": [], "intro": ""}


def section_of(meta: dict) -> dict:
    return SECTIONS.get(meta.get("section", ""), OTHER_SECTION)


def fmt_date(iso: str | None) -> str:
    try:
        return dt.date.fromisoformat((iso or "")[:10]).strftime("%-d %b %Y" if os.name != "nt" else "%#d %b %Y")
    except ValueError:
        return iso or ""


def write_cover(name: str, sec: dict, banner: bool = False) -> str:
    """Writes web/blog/img/<name>.svg and returns its path relative to web/blog/. Banners are extra wide."""
    (WEB / "blog" / "img").mkdir(parents=True, exist_ok=True)
    svg = cover_svg(sec["hue"], sec["icon"], name, *((2400, 520) if banner else ()))
    (WEB / "blog" / "img" / f"{name}.svg").write_text(svg, encoding="utf-8")
    return f"img/{name}.svg"


def post_card(p: dict, up: str = "", featured: bool = False) -> str:
    sec = section_of(p)
    when = f"Updated {fmt_date(p['updated'])}" if p.get("live") else fmt_date(p.get("date"))
    return f"""<a class="post-card{' featured' if featured else ''}" href="{up}{e(p['href'])}">
  <img class="post-card-img" src="{up}{e(p['cover'])}" alt="" loading="lazy" width="1200" height="560">
  <span class="post-card-body">
    <span class="post-sec" style="--h:{sec['hue']}">{e(sec['title'])}</span>
    <span class="post-card-title">{e(p['title'])}</span>
    <span class="post-card-desc">{e(p.get('description', ''))}</span>
    <span class="post-card-meta">{when} · {p['minutes']} min read</span>
  </span>
</a>"""


# ---------------------------------------------------------------- builders
def build_resources(resources: dict, posts: list[dict]) -> None:
    parts, any_aff = [], False
    by_cat = {cid: s for s in SECTIONS.values() for cid in s["resources"]}
    looks = {"visa": (248, "passport"), "banking": (205, "bank"), "insurance": (168, "shield"), "german": (330, "chat"),
             "salary": (152, "euro"), "housing": (18, "home"), "jobs": (225, "briefcase")}
    nav = "".join(f'<a class="tag" href="#{c["id"]}">{e(c["title"])}</a>' for c in resources["categories"])
    for c in resources["categories"]:
        cards, aff = resource_cards(c)
        any_aff |= aff
        sec = by_cat.get(c["id"], OTHER_SECTION)
        hue, icon = looks.get(c["id"], (sec["hue"], sec["icon"]))
        guides = [p for p in posts if section_of(p)["id"] == sec["id"]][:3]
        related = ("<p class='res-guides'><b>Guides on this topic:</b> "
                   + " · ".join(f'<a href="blog/{e(p["href"])}">{e(p["title"])}</a>' for p in guides) + "</p>") if guides else ""
        parts.append(f"""<section class="res-section" id="{c['id']}">
  <header class="res-head" style="--h:{hue}">
    <span class="res-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
      stroke-linecap="round" stroke-linejoin="round">{ICONS[icon]}</svg></span>
    <div><h2>{e(c['title'])}</h2><p>{e(c['intro'])}</p></div>
  </header>
  {cards}{related}
</section>""")
    body = f"""<section class="page-hero">
  <p class="eyebrow">Resources</p>
  <h1>Everything you need to move to and work in Germany</h1>
  <p class="lead">Hand-picked, English-friendly services and the official sources we trust — checked {fmt_date(TODAY.isoformat())}.</p>
  <nav class="tag-cloud res-nav" aria-label="Resource categories">{nav}</nav>
</section>
{"".join(parts)}"""
    (WEB / "resources.html").write_text(page(
        "Resources for working in Germany", "Visa, Blue Card, bank account, health insurance, learning German, "
        "salary and housing: the English-friendly services and official sources internationals need.",
        body, "resources.html", 0, affiliate_note=any_aff), encoding="utf-8")


def render_shortcodes(md: str, jobs: list[dict], stats: dict, resources: dict, up: str) -> tuple[str, bool]:
    used_aff = False
    cats = {c["id"]: c for c in resources["categories"]}

    def res(m):
        nonlocal used_aff
        c = cats.get(m.group(1).strip())
        if not c:
            return ""
        cards, aff = resource_cards(c, up)
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
    text = path.read_text(encoding="utf-8")
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


def reading_minutes(md: str) -> int:
    words = len(re.sub(r"\{\{[^}]*\}\}|[#*|`>_-]", " ", md).split())
    return max(2, math.ceil(words / 200))


def add_months(iso: str, months: int) -> dt.date:
    d = dt.date.fromisoformat(iso[:10])
    y, m = divmod(d.month - 1 + months, 12)
    return dt.date(d.year + y, m + 1, min(d.day, 28))


def article_html(meta: dict, body_html: str, toc: list[dict], related: list[dict], sources: str = "") -> str:
    """Article page: cover, breadcrumb, dates, table of contents, body, sources, review note, related guides."""
    sec = section_of(meta)
    sec_link = f'<a href="{e(sec["href"])}">{e(sec["title"])}</a>' if sec.get("href") else e(sec["title"])
    published = f'<span>Published <time datetime="{e(meta.get("date", ""))}">{fmt_date(meta.get("date"))}</time></span>'
    if meta.get("live"):
        updated = (f'<span class="live">Updated <time datetime="{NOW.isoformat(timespec="minutes")}">'
                   f'{fmt_date(TODAY.isoformat())}, {NOW:%H:%M} {NOW:%Z}</time> · live data</span>')
    elif meta.get("reviewed"):
        updated = f'<span>Fact-checked <time datetime="{e(meta["reviewed"])}">{fmt_date(meta["reviewed"])}</time></span>'
    else:
        updated = ""
    review = ""
    if meta.get("reviewed") and meta.get("review_months"):
        due = add_months(meta["reviewed"], int(meta["review_months"]))
        review = (f'<p class="review-note">We re-check this guide every {e(meta["review_months"])} months against official '
                  f'sources. Last check: {fmt_date(meta["reviewed"])} · next: {due:%B %Y}.</p>')
    toc_html = ("<nav class='post-toc' aria-label='On this page'><p>On this page</p><ol>"
                + "".join(f'<li><a href="#{e(t["id"])}">{e(t["name"])}</a></li>' for t in toc) + "</ol></nav>") if len(toc) >= 3 else ""
    initials = "".join(w[0] for w in SITE["author"].split()[:2]).upper()
    rel = (f'<section class="related"><h2>More in {e(sec["title"])}</h2><div class="post-grid">'
           + "".join(post_card(p) for p in related) + "</div></section>") if related else ""
    return f"""<div class="post-cover" style="--h:{sec['hue']}"><img src="{e(meta['cover'])}" alt="" width="1200" height="560"></div>
<div class="post-layout">
  <article class="post">
    <nav class="crumbs"><a href="index.html">Guides</a> › {sec_link}</nav>
    <h1>{e(meta['title'])}</h1>
    {f'<p class="post-lead">{e(meta["description"])}</p>' if meta.get("description") else ""}
    <div class="post-meta"><span class="author"><span class="avatar">{e(initials)}</span>{e(SITE['author'])}</span>
      {published}{updated}<span>{meta['minutes']} min read</span></div>
    <div class="article post-body">{body_html}</div>
    {f'<aside class="post-sources"><h2>Official sources &amp; tools</h2>{sources}</aside>' if sources else ""}
    {review}
    <aside class="cta"><b>Looking for an English-speaking job?</b>
      <a class="btn primary" href="../index.html">Search jobs with German level &amp; salary up front →</a></aside>
  </article>
  {toc_html}
</div>
{rel}"""


def build_blog(jobs: list[dict], stats: dict, resources: dict) -> list[dict]:
    """Reads content/blog/*.md (two passes: metadata first, so every article can list related ones)."""
    out_dir = WEB / "blog"
    out_dir.mkdir(exist_ok=True)
    for sec in SECTIONS.values():
        sec["href"] = f"section-{sec['id']}.html"
    cats = {c["id"]: c for c in resources["categories"]}
    posts = []
    for p in sorted((CONTENT / "blog").glob("*.md")):
        meta, body = read_post(p)
        if meta.get("draft") == "true":
            continue
        meta.update(body=body, live=bool(re.search(r"\{\{(jobs|stat):", body)), minutes=reading_minutes(body),
                    cover=write_cover(meta["slug"], section_of(meta)), href=f"{meta['slug']}.html",
                    path=f"blog/{meta['slug']}.html")
        meta["updated"] = TODAY.isoformat() if meta["live"] else max(meta.get("reviewed", ""), meta.get("date", ""))
        posts.append(meta)
    posts.sort(key=lambda p: p.get("date", ""), reverse=True)

    for meta in posts:
        sec = section_of(meta)
        body, aff = render_shortcodes(meta["body"], jobs, stats, resources, "../")
        md = markdown.Markdown(extensions=["tables", "fenced_code", "md_in_html", "toc"])
        body_html = md.convert(body)
        toc = [t for t in md.toc_tokens if t["level"] == 2]
        embedded = set(re.findall(r"\{\{resources:([^}]+)\}\}", meta["body"]))
        sources, src_aff = "", False
        for cid in sec["resources"]:
            if cid not in embedded and cid in cats:
                cards, a = resource_cards(cats[cid], "../")
                sources += cards
                src_aff |= a
        related = [p for p in posts if p is not meta and section_of(p)["id"] == sec["id"]][:3]
        related += [p for p in posts if p is not meta and p not in related][:3 - len(related)]
        ld = json.dumps({"@context": "https://schema.org", "@type": "Article", "headline": meta["title"],
                         "description": meta.get("description"), "image": f"{SITE_URL}/blog/{meta['cover']}",
                         "datePublished": meta.get("date"), "dateModified": meta["updated"],
                         "articleSection": sec["title"], "author": {"@type": "Person", "name": SITE["author"]},
                         "publisher": {"@type": "Organization", "name": SITE["site_name"], "url": SITE_URL}})
        (out_dir / f"{meta['slug']}.html").write_text(page(
            meta["title"], meta.get("description", ""), article_html(meta, body_html, toc, related, sources),
            f"blog/{meta['slug']}.html", 1, f'<script type="application/ld+json">{ld}</script>',
            affiliate_note=aff or src_aff, main_class="post-page"), encoding="utf-8")
    for meta in posts:
        meta.pop("body", None)
    return posts


def build_report(jobs: list[dict], stats: dict) -> dict:
    """Weekly job-market report. Rebuilt every day during the ISO week, frozen after."""
    year, week, _ = TODAY.isocalendar()
    slug = f"job-market-{year}-w{week:02d}"
    hist_path = CONTENT / "reports" / "history.json"
    hist_path.parent.mkdir(exist_ok=True)
    history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else {}
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
            "date": TODAY.isoformat(), "slug": slug, "section": "reports", "live": True,
            "updated": TODAY.isoformat(), "minutes": 3, "href": f"{slug}.html", "path": f"blog/{slug}.html"}
    meta["cover"] = write_cover(slug, section_of(meta))
    SECTIONS["reports"]["href"] = "section-reports.html"
    (WEB / "blog" / f"{slug}.html").write_text(page(
        meta["title"], meta["description"], article_html(meta, body, [], []), f"blog/{slug}.html", 1,
        main_class="post-page"), encoding="utf-8")
    return {**meta, "report": True}


# German states by their ISO code (ingest/geo.py stores each city's code), English names.
STATES = {"DE-BW": "Baden-Württemberg", "DE-BY": "Bavaria", "DE-BE": "Berlin", "DE-BB": "Brandenburg", "DE-HB": "Bremen",
          "DE-HH": "Hamburg", "DE-HE": "Hesse", "DE-MV": "Mecklenburg-Western Pomerania", "DE-NI": "Lower Saxony",
          "DE-NW": "North Rhine-Westphalia", "DE-RP": "Rhineland-Palatinate", "DE-SL": "Saarland", "DE-SN": "Saxony",
          "DE-ST": "Saxony-Anhalt", "DE-SH": "Schleswig-Holstein", "DE-TH": "Thuringia"}
MIN_JOBS = 5  # a state, city or field gets its own page from this many open jobs


def logo_html(name: str, src: str | None, up: str, cls: str = "") -> str:
    """A company logo or a place's coat of arms; without an image the coloured initials, like logoHtml() in app.js."""
    if src:
        return f'<img class="logo {cls}" src="{up}{e(src)}" alt="" loading="lazy">'
    words = re.sub(r"\(.*?\)", "", name or "?").split() or ["?"]
    initials = (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1:2])).upper()
    h = 0
    for ch in name or "":
        h = (h * 31 + ord(ch)) % 360
    return f'<span class="logo mono {cls}" style="--h:{h}" aria-hidden="true">{e(initials)}</span>'


def job_cards_html(jobs: list[dict], up: str, logos: dict[str, str]) -> str:
    """The job cards of the main search page (app.js jobHtml) as static HTML, plus the first line of the AI summary.
    Every card opens our own job page."""
    if not jobs:
        return '<p class="muted">No matching jobs right now — check back tomorrow.</p>'
    cards = []
    for j in jobs:
        cls, label = GERMAN_LABEL.get(j["german_level"], GERMAN_LABEL["not_mentioned"])
        title_only = j.get("source") == "amazon"  # title and link only (ingest/sources.py amazon())
        if title_only and j["german_level"] == "not_mentioned":
            label = "German: see posting"
        badges = [f'<span class="badge {cls}">{label}</span>']
        if j.get("visa_sponsorship"):
            badges.append('<span class="badge ok">Visa sponsorship</span>')
        if j.get("relocation"):
            badges.append('<span class="badge ok">Relocation support</span>')
        if j.get("is_agency"):
            badges.append('<span class="badge warn">Recruiting agency</span>')
        sal = (f'{euro(j["salary_min"])}{"–" + euro(j["salary_max"])[1:] if j.get("salary_max") and j["salary_max"] != j["salary_min"] else ""}'
               if j.get("salary_min") else "")
        summary = ("We can't show more information for this job right now. The full posting is on Amazon's site."
                   if title_only else j.get("ai_summary") or "")
        day = parse_ts(j.get("posted_at"))
        cards.append(f"""<li class="job" data-id="{e(j['id'])}" data-job="{e(j['id'])}">
  {logo_html(j["company"], logos.get(co_key(j["company"])), up, "job-logo")}
  <div class="job-main">
    <h3 class="job-title"><a href="{up}job/{e(j['id'])}.html" data-job="{e(j['id'])}">{e(j['title'])}</a></h3>
    <div class="job-meta"><span class="company">{e(j['company'])}</span><span>{e(j.get('city') or 'Germany')}</span><span>{day.day} {day:%b}</span></div>
    {f'<p class="job-sum">{e(summary)}</p>' if summary else ""}
    <div class="badges">{"".join(badges)}</div>
  </div>
  <div class="job-side">{f'<div class="job-salary">{sal}<small>/ year</small></div>' if sal else '<div class="job-salary none">Salary not listed</div>'}</div>
</li>""")
    return f'<ol class="results static-cards">{"".join(cards)}</ol>'


# The job popup of the home page (app.js openJob), on the location and field pages: a card opens it in place.
CARD_SCRIPTS = """<script src="../js/config.js"></script>
<script src="../js/app.js"></script>"""


def place_tiles_html(items: list[tuple[int, str | None, str, str | None]], up: str, total: int) -> str:
    """[(jobs, coat of arms or None, name, link or None)] as tiles: coat of arms, name, "1,097 jobs" and a bar for the
    share of `total`. The page's own place is a tile without a link."""
    tiles = []
    for n, img, name, href in items:
        inner = (f'{logo_html(name, img, up, "logo-sm coa")}<span class="pt-text"><b>{e(name)}</b>'
                 f'<small>{n:,} job{"s" if n != 1 else ""}</small></span>'
                 f'<span class="pt-bar" style="--w:{max(3, round(100 * n / max(total, 1)))}%"></span>')
        tiles.append(f'<li><a class="place-tile" href="{e(href)}">{inner}</a></li>' if href
                     else f'<li><span class="place-tile here" aria-current="page">{inner}</span></li>')
    return f'<ul class="place-tiles">{"".join(tiles)}</ul>'


def faq_html(items: list[tuple[str, str]], title: str = "Frequently asked questions", intro: str = "") -> str:
    """[(question, answer HTML)] as numbered foldable questions, plus schema.org FAQPage data so Google can show the
    answers. With `intro` (home page) the title and intro sit in a column next to the questions."""
    plain = lambda h: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", h))).strip()  # noqa: E731
    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": plain(a)}} for q, a in items]}
    qa = "".join(f'<details><summary><span class="faq-n">{i:02d}</span><span>{e(q)}</span></summary><div class="faq-a">{a}</div></details>'
                 for i, (q, a) in enumerate(items, 1))
    head = f'<div class="faq-intro"><p class="kicker accent">FAQ</p><h2 id="faq-h">{e(title)}</h2>{intro}</div>' if intro \
        else f'<h2 id="faq-h">{e(title)}</h2>'
    return (f'<section class="faq{" faq-split" if intro else ""}" aria-labelledby="faq-h">{head}<div class="faq-list">{qa}</div></section>'
            f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")}</script>')


def required_pct(jobs: list[dict]) -> int:
    """Share of jobs that require German ("not mentioned" doesn't count: most such teams work in English)."""
    return round(100 * sum(j["german_level"] == "required" for j in jobs) / max(len(jobs), 1))


def blue_card() -> dict:
    """{year, standard, reduced} from web/js/config.js, the site's one place for the Blue Card minimums."""
    return {k: int(v) for k, v in re.findall(
        r"(\w+): (\d+)", re.search(r"BLUE_CARD: \{([^}]*)\}", (WEB / "js" / "config.js").read_text(encoding="utf-8")).group(1))}


def agent_facts(jobs: list[dict], stats: dict, by_city: dict[str, list[dict]], cities: list[str], index: dict) -> list[str]:
    """Short reports from today's jobs for Stelli's speech bubble on the home page (app.js stelliLines): cities,
    fields, salaries, remote, entry level, Blue Card, agencies, employers. Each one only when the numbers carry it."""
    n = len(jobs) or 1
    pct = lambda part, whole: round(100 * part / max(whole, 1))  # noqa: E731
    mid = lambda j: (j["salary_min"] + (j.get("salary_max") or j["salary_min"])) / 2  # noqa: E731
    name = lambda c: index.get(co_key(c), {}).get("n") or c  # noqa: E731
    paid = lambda sel: [mid(j) for j in sel if j.get("salary_min") and j["salary_min"] <= 300000]  # noqa: E731
    out = []
    for city in cities[:6]:
        sel = by_city[city]
        k = len(sel)
        visa = sum(bool(j.get("visa_sponsorship")) for j in sel)
        out.append(f"📍 {city}: {k:,} open jobs. Only {pct(sum(j['german_level'] == 'required' for j in sel), k)}% require German"
                   + (f", and {visa} mention visa sponsorship." if visa else "."))
        top = Counter(name(j["company"]) for j in sel if not j.get("is_agency")).most_common(1)
        if top and top[0][1] >= 0.8 * k:
            out.append(f"🏢 {'All' if top[0][1] == k else f'{top[0][1]} of the'} {k} jobs in {city} are at {top[0][0]}.")
        elif top and top[0][1] >= 5:
            out.append(f"🏢 The busiest English-speaking employer in {city} right now: {top[0][0]}, with {top[0][1]} open jobs.")
        sal = paid(sel)
        if len(sal) >= 8:
            out.append(f"💶 Median listed salary in {city}: {euro(statistics.median(sal))} a year, from {len(sal)} jobs that show one.")
        remote = pct(sum(j["remote_type"] in ("remote_de", "remote_eu", "hybrid") for j in sel), k)
        if k >= 50 and remote >= 20:
            out.append(f"🏠 {remote}% of the jobs in {city} are remote or hybrid.")
    fields = [(t, c) for t, c in stats["tags"] if t not in META_TAGS][:3]
    if len(fields) == 3:
        out.append("🧭 Biggest fields today: " + ", ".join(f"{t} ({c:,})" for t, c in fields) + ".")
    for t, m, c in [x for x in stats["salary_by_tag"] if x[2] >= 10][:3]:  # 10+ salaries, not a lucky handful
        out.append(f"💶 #{t} jobs pay a median of {euro(m)} a year ({c} jobs list a salary).")
    if stats["new_7d"] < n * 0.4:  # right after a full re-import every job is "new"
        out.append(f"🆕 {stats['new_7d']:,} new English-speaking jobs came in during the last 7 days.")
    out.append(f"🌍 {stats['remote_pct']}% of all jobs are fully remote, in Germany or anywhere in the EU.")
    entry = sum(j.get("seniority") in ("intern", "junior") for j in jobs)
    if entry:
        out.append(f"🎓 {entry:,} jobs are entry level (intern, working student or junior). Tick “Entry level” to see them.")
    bc = blue_card()
    over = sum(bool(j.get("salary_min")) and j["salary_min"] >= bc["standard"] for j in jobs)
    if over:
        out.append(f"🪪 {over:,} jobs list a salary above the {bc['year']} Blue Card minimum of {euro(bc['standard'])}.")
    agency = pct(sum(bool(j.get("is_agency")) for j in jobs), n)
    if agency >= 5:
        out.append(f"🔎 {agency}% of the jobs come from recruiting agencies. Tick “Direct employers only” to hide them.")
    top = [(name(c), k) for c, k in stats["companies"][:3]]
    if len(top) == 3:
        out.append("🏢 Most open jobs right now: " + ", ".join(f"{c} ({k})" for c, k in top) + ".")
    return out


def write_home_faq(jobs: list[dict], stats: dict, cities: list[tuple[str, int, str]]) -> None:
    """The FAQ on the hand-written home page, with today's numbers, between <!-- faq:start --> and <!-- faq:end -->."""
    req, visa, n = required_pct(jobs), stats["visa"], len(jobs)
    plus = round(100 * (stats["german"].get("not_required", 0) + stats["german"].get("nice_to_have", 0)) / max(n, 1))
    bc = blue_card()
    city_links = ", ".join(f'<a href="{e(u)}">{e(c)}</a> ({k:,})' for c, k, u in cities[:5])
    items = [
        ("Can I get a job in Germany without speaking German?",
         f"Yes. Only {req}% of the {n:,} English-speaking jobs on Stellenly require German; {plus}% say it's not needed "
         f"or just a plus, and most of the rest don't mention it, which usually means the team works in English. "
         f'Tick <b>No German needed</b> above to see only those jobs.'),
        ("How do you know whether a job needs German?",
         "We read every posting and show its German level on the card: not required, nice to have, not mentioned or "
         "required, with the exact sentence from the posting in the job details. We don't hide jobs that need German, so "
         'you can decide yourself. <a href="how-it-works.html">How we read job postings</a>.'),
        ("Which jobs offer visa sponsorship?",
         f"Right now {visa:,} jobs mention visa sponsorship or work-permit support. Tick <b>Visa sponsorship</b> above. "
         f"Most non-EU candidates need a work permit, usually the EU Blue Card."),
        (f"How much do I need to earn for an EU Blue Card in {bc['year']}?",
         f"At least {euro(bc['standard'])} gross a year, or {euro(bc['reduced'])} for IT and other shortage jobs, health "
         f"care and recent graduates. Jobs whose listed salary reaches it are marked <b>Blue Card ✓</b>. "
         f'<a href="blog/eu-blue-card-salary-{bc["year"]}.html">Read the Blue Card guide</a>.'),
        ("Which German cities have the most English-speaking jobs?",
         f'{city_links}. <a href="jobs/index.html">All states and cities</a>.'),
        ("Is Stellenly free? Do I need an account?",
         "It's free, and there is no sign-up: we store no personal data and set no cookies. Saved jobs stay in your "
         "browser. You apply directly on the employer's site."),
        ("Where do the jobs come from, and how fresh are they?",
         "From company career pages and public job APIs, updated every 6 hours. Jobs that disappear from their source "
         "are removed automatically, and visitors can report a closed job with 🚩."),
        ("Can I get new jobs sent to me?",
         'Yes, without an email address: follow our <a href="https://t.me/StellenlyJobs" rel="noopener">Telegram channel</a> '
         'for new jobs every day, or join the community on <a href="https://discord.gg/wMqjvq6dw" rel="noopener">Discord</a>.'),
    ]
    home = WEB / "index.html"
    text = home.read_text(encoding="utf-8")
    start, end = "<!-- faq:start", "<!-- faq:end -->"
    if start in text and end in text:
        a = text.index("-->", text.index(start)) + 3
        intro = (f'<p class="faq-lead">The answers use today\'s numbers from {n:,} open jobs and update every day.</p>'
                 '<div class="faq-ask"><b>Still have a question?</b><span>Ask the community or write to us.</span>'
                 f'<span class="faq-links"><a href="{e(SITE["discord_url"])}" rel="noopener">Ask on Discord →</a>'
                 '<a href="mailto:info@stellenly.com">info@stellenly.com</a></span></div>')
        text = text[:a] + "\n  " + faq_html(items, "Questions, answered with live numbers", intro) + "\n  " + text[text.index(end):]
        home.write_text(text, encoding="utf-8", newline="\n")


def build_landing_pages(jobs: list[dict], stats: dict) -> list[str]:
    """jobs/state-*.html, jobs/city-*.html, jobs/tag-*.html and jobs/index.html, built from the site's own parts:
    KPI tiles, the job cards of the search page, place tiles with the coat of arms, and beside the list a map of
    Germany (germany_map.py) with the state highlighted. Also web/data/locations.json for the home page."""
    out = WEB / "jobs"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.html"):  # cities/tags that no longer qualify must not linger
        old.unlink()
    index = json.loads((WEB / "data" / "companies-index.json").read_text(encoding="utf-8"))
    logos = {k: v["l"] for k, v in index.items() if v.get("l")}
    by_city: dict[str, list[dict]] = {}
    for j in jobs:
        # Jobs stored before the city cleanup may still say "All" or "DEU": only real city names get a place.
        if j.get("city") and j["city"] != "Remote" and normalize_city(j["city"]) == j["city"]:
            by_city.setdefault(j["city"], []).append(j)
    by_state: dict[str, list[str]] = {}
    for c in by_city:
        if geo.city_state(c) in STATES:
            by_state.setdefault(geo.city_state(c), []).append(c)
    city_pages = {c for c, js in by_city.items() if len(js) >= MIN_JOBS}
    state_jobs = {s: [j for c in cs for j in by_city[c]] for s, cs in by_state.items()}
    state_pages = {s for s, js in state_jobs.items() if len(js) >= MIN_JOBS}
    url = lambda kind, val: f"{kind}-{slugify(STATES[val] if kind == 'state' else val)}.html"  # noqa: E731
    city_url = lambda c: url("city", c) if c in city_pages else f"../index.html?city={requests.utils.quote(c)}"  # noqa: E731
    state_urls = {st: url("state", st) for st in state_pages}
    coa = lambda kind, key: coats_of_arms.image(f"{kind}:{key}")  # noqa: E731

    def kpis(s: dict) -> str:
        items = [(f"{s['active']:,}", "open jobs"), (f"{s['no_german_pct']}%", "don't require German"),
                 (f"{s['visa']:,}", "offer visa sponsorship")]
        if s["median_salary"]:
            items.append((euro(s["median_salary"]), f"median listed salary ({s['salary_pct']}% list one)"))
        return '<div class="kpis loc-kpis">' + "".join(f"<div><b>{v}</b><span>{k}</span></div>" for v, k in items) + "</div>"

    def place_faq(name: str, sel: list[dict], s: dict) -> str:
        top = Counter(index.get(co_key(j["company"]), {}).get("n") or j["company"] for j in sel if not j.get("is_agency"))
        req = required_pct(sel)
        return faq_html([
            (f"Do I need German for a job in {name}?",
             f"Only {req}% of the {len(sel):,} English-speaking jobs in {e(name)} require German. Each job shows its German "
             f"level, with the exact sentence from the posting."),
            (f"Which companies hire English speakers in {name}?",
             f"Right now the most open English-speaking jobs are at {e(', '.join(c for c, _ in top.most_common(5)))}."),
            (f"Are there jobs with visa sponsorship in {name}?",
             f"{s['visa']:,} of them mention visa sponsorship or work-permit support"
             + (f", and the median listed salary is {euro(s['median_salary'])} a year." if s["median_salary"] else ".")),
        ], f"English-speaking jobs in {name}: questions")

    def location(kind: str, val: str, sel: list[dict], state: str | None) -> str:
        name = STATES[val] if kind == "state" else val
        sel = sorted(sel, key=lambda j: j.get("posted_at") or "", reverse=True)
        s = compute_stats(sel)
        cities = sorted(by_state.get(state, []), key=lambda c: -len(by_city[c]))
        region = STATES.get(state, name)
        de_name = germany_map.GERMAN_NAMES.get(state, region)  # "Bayern" next to "Bavaria"
        crumbs = ['<a href="index.html">Jobs by location</a>']
        if kind == "city" and state in state_pages:
            crumbs.append(f'<a href="{url("state", state)}">{e(STATES[state])}</a>')
        dots = [{"n": c, "lat": xy[0], "lon": xy[1], "k": len(by_city[c]), "u": city_url(c), "h": c == val}
                for c in cities if (xy := geo.city_coords(c))]
        search = (f'<a class="btn primary" href="../index.html?city={e(requests.utils.quote(val))}">'
                  f"Filter by German level, salary &amp; visa →</a>" if kind == "city" else "")
        more = (f'<p class="muted small">The 30 newest of {len(sel):,} jobs.'
                f'{" The search shows all of them." if kind == "city" else ""}</p>' if len(sel) > 30 else "")
        body = f"""<nav class="crumbs">{" › ".join(crumbs)}</nav>
<header class="loc-head">
  {logo_html(name, coa(kind, val), "../", "logo-lg coa")}
  <div><h1>English-speaking jobs in {e(name)}</h1>
  <p class="muted">{"State" if kind == "state" else "City"}{f" in {e(STATES[state])}" if kind == "city" and state in STATES else ""}{f" · {e(de_name)}" if kind == "state" and de_name != name else ""} · updated every 6 hours</p></div>
  {search}
</header>
{kpis(s)}
<div class="loc-layout">
  <div class="loc-list"><h2>Latest jobs</h2>{job_cards_html(sel[:30], '../', logos)}{more}</div>
  <aside class="loc-side">
    <section class="jd-card loc-map-card"><h3>{e(region)} on the map</h3>
      {germany_map.svg(state, state_urls, STATES, dots)}
      <p class="muted small">Circles: cities with jobs, by size. Click a city or another state.</p></section>
    <section class="jd-card"><h3>Cities in {e(region)}</h3>
      {place_tiles_html([(len(by_city[c]), coa("city", c), c, city_url(c) if c != val else None) for c in cities], "../", len(state_jobs.get(state, sel)))}</section>
  </aside>
</div>
{place_faq(name, sel, s)}
<p class="muted small">Always apply on the original posting.</p>
{CARD_SCRIPTS}"""
        title = f"{s['active']:,} English-speaking jobs in {name}"
        (out / url(kind, val)).write_text(page(title, f"{title}: German requirement, salary and visa sponsorship shown for every job.",
                                               body, f"jobs/{url(kind, val)}", 1, main_class="content-page loc-page"), encoding="utf-8")
        return f"jobs/{url(kind, val)}"

    paths = [location("state", st, state_jobs[st], st) for st in sorted(state_pages)]
    paths += [location("city", c, by_city[c], geo.city_state(c)) for c in sorted(city_pages)]

    tag_chips = []
    for t, n in stats["tags"]:
        if n < MIN_JOBS:
            continue
        sel = sorted((j for j in jobs if t in (j.get("tags") or [])), key=lambda j: j.get("posted_at") or "", reverse=True)
        s = compute_stats(sel)
        label = "AI / ML" if t == "ai-ml" else t.replace("-", " ")
        title = f"{s['active']:,} English-speaking {label} jobs in Germany"
        body = f"""<nav class="crumbs"><a href="index.html">Jobs by location and field</a></nav>
<header class="loc-head"><div><h1>English-speaking {e(label)} jobs in Germany</h1><p class="muted">Updated every 6 hours</p></div>
  <a class="btn primary" href="../index.html?tags={e(t)}">Filter by German level, salary &amp; visa →</a></header>
{kpis(s)}
<div class="loc-list"><h2>Latest jobs</h2>{job_cards_html(sel[:30], '../', logos)}</div>
<p class="muted small">Always apply on the original posting.</p>
{CARD_SCRIPTS}"""
        (out / f"tag-{slugify(t)}.html").write_text(page(title, f"{title}: German requirement, salary and visa sponsorship "
                                                          f"shown for every job.", body, f"jobs/tag-{slugify(t)}.html", 1,
                                                          main_class="content-page loc-page"), encoding="utf-8")
        paths.append(f"jobs/tag-{slugify(t)}.html")
        tag_chips.append(f'<a class="tag" href="tag-{slugify(t)}.html">#{e(t)}<span class="n">{n:,}</span></a>')

    states_sorted = sorted(state_pages, key=lambda x: -len(state_jobs[x]))
    cities_sorted = sorted(city_pages, key=lambda x: -len(by_city[x]))
    (out / "index.html").write_text(page(
        "English-speaking jobs in Germany by state, city and field",
        f"{len(jobs):,} English-speaking jobs in Germany, by state, city and field.",
        f"""<header class="loc-head"><div><h1>English-speaking jobs by location</h1>
<p class="muted">{len(jobs):,} open jobs in {len(state_pages)} states and {len(city_pages)} cities · updated every 6 hours</p></div></header>
<div class="loc-index">
  <section class="jd-card loc-map-card"><h3>Germany</h3>
    {germany_map.svg(None, state_urls, STATES, [{"n": c, "lat": xy[0], "lon": xy[1], "k": len(by_city[c]), "u": url("city", c)}
                                                for c in cities_sorted if (xy := geo.city_coords(c))])}
    <p class="muted small">Click a state or a city.</p></section>
  <section><h2>States</h2>{place_tiles_html([(len(state_jobs[st]), coa("state", st), STATES[st], url("state", st)) for st in states_sorted], "../", len(jobs))}</section>
</div>
<h2>Cities</h2>{place_tiles_html([(len(by_city[c]), coa("city", c), c, url("city", c)) for c in cities_sorted], "../", len(jobs))}
<h2 id="fields">Fields</h2><div class="tag-cloud loc-tags">{"".join(tag_chips)}</div>""", "jobs/index.html", 1,
        main_class="content-page loc-page"), encoding="utf-8")

    # Home page "Browse by location" row (app.js): the biggest states, then the biggest other cities.
    top = [{"n": STATES[st], "k": len(state_jobs[st]), "u": f"jobs/{url('state', st)}", "i": coa("state", st)}
           for st in states_sorted[:4]]
    top += [{"n": c, "k": len(by_city[c]), "u": f"jobs/{url('city', c)}", "i": coa("city", c)}
            for c in cities_sorted if c not in {t["n"] for t in top}][:6]
    # Seniority, remote, visa etc. are filters, not fields.
    fields = [{"n": t, "k": n, "u": f"jobs/tag-{slugify(t)}.html"} for t, n in stats["tags"] if n >= MIN_JOBS and t not in META_TAGS][:8]
    kpi = {"req": stats["german_required_pct"], "visa": stats["visa"], "median": stats["median_salary"],
           "salary_pct": stats["salary_pct"]}
    facts = agent_facts(jobs, stats, by_city, cities_sorted, index)
    (WEB / "data" / "locations.json").write_text(json.dumps({"places": top, "fields": fields, "kpi": kpi, "facts": facts},
                                                            ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_home_faq(jobs, stats, [(c, len(by_city[c]), f"jobs/{url('city', c)}") for c in cities_sorted])
    return paths + ["jobs/index.html"]


# ---------------------------------------------------------------- companies directory + map
_LEGAL = {"gmbh", "ag", "se", "kg", "kgaa", "co", "inc", "ltd", "llc", "plc", "bv", "nv", "sa", "sas", "oy",
          "ab", "ug", "haftungsbeschrankt", "mbh", "group", "holding", "the"}
NO_CITY, REMOTE = "Elsewhere in Germany", "Remote in Germany"


def co_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return "".join(t for t in re.split(r"[^a-z0-9]+", s) if t and t not in _LEGAL)


def place(j: dict) -> str | None:
    """German city for the directory, or None for a job outside Germany (rows stored before the country check)."""
    if "_place" not in j:
        raw = j.get("city")
        c = normalize_city(raw)
        j["_place"] = (REMOTE if c == "Remote"
                       else (NO_CITY if not raw or in_germany(raw) else None) if not c
                       else c if in_germany(c) or geo.cached_country(c) == "de" or geo.city_coords(c) else None)
    return j["_place"]


def load_companies(jobs: list[dict]) -> list[dict]:
    """Curated companies (content/companies.json) + every company with 2+ open jobs. Recruiting agencies are in
    too (Hiring Score badge on their jobs), labelled "Recruiting agency" on their company page and in the directory."""
    meta = json.loads((CONTENT / "companies.json").read_text(encoding="utf-8"))["companies"]
    by_key = {co_key(n): m for m in meta for n in [m["name"], *m.get("aliases", [])]}
    groups: dict[str, dict] = {co_key(m["name"]): {"meta": m, "names": Counter(), "jobs": []} for m in meta}
    for j in jobs:
        if place(j) is None:
            continue
        m = by_key.get(co_key(j["company"]))
        g = groups.setdefault(co_key(m["name"]) if m else co_key(j["company"]),
                              {"meta": m, "names": Counter(), "jobs": []})
        g["names"][j["company"]] += 1
        g["jobs"].append(j)

    out, slugs = [], set()
    for g in groups.values():
        m, js = g["meta"], sorted(g["jobs"], key=lambda j: j.get("posted_at") or "", reverse=True)
        if not m and len(js) < 2:
            continue
        name = m["name"] if m else g["names"].most_common(1)[0][0]
        slug = slugify(name) or "company"
        while slug in slugs:
            slug += "-2"
        slugs.add(slug)
        hq_de = bool(m and in_germany(m["hq"]))
        out.append({"name": name, "slug": slug, "meta": m, "jobs": js, "cities": Counter(place(j) for j in js),
                    "hq_city": normalize_city(m["hq"]) if hq_de else None, "hq_de": hq_de,
                    "page": bool(m) or len(js) >= 3, "names": list(g["names"]), "score": hiring_score(js),
                    "agency": all(j.get("is_agency") for j in js) if js else False})
    return sorted(out, key=lambda c: (c["meta"] is None, -len(c["jobs"]), c["name"].lower()))


def co_badges(c: dict) -> str:
    m = c["meta"] or {}
    b = '<span class="badge warn">Recruiting agency</span>' if c.get("agency") else ""
    b += '<span class="badge new">Startup</span>' if m.get("startup") else ""
    b += '<span class="badge info">German HQ</span>' if c["hq_de"] else ""
    return b + (f'<span class="badge">{e(m["industry"])}</span>' if m.get("industry") else "")


def co_facts(c: dict) -> str:
    m = c["meta"] or {}
    rows = [("Founded", m.get("founded")), ("Employees", m.get("size")), ("HQ", m.get("hq"))]
    return "".join(f"<div><dt>{k}</dt><dd>{e(str(v))}</dd></div>" for k, v in rows if v)


def jobs_word(n: int) -> str:
    return f"{n} open job{'s' if n != 1 else ''}" if n else "No open jobs right now"


# ---------------------------------------------------------------- Stellenly Hiring Score
# Based only on a company's job postings on Stellenly — not on employee reviews. Each factor gives
# 0–100 points; the total is the weighted average (shown as 0–5 stars). Keep in sync with app.js.
SCORE_WEIGHTS = {"salary": 20, "language": 25, "visa": 15, "activity": 15, "freshness": 10, "reposts": 15}
SCORE_MIN_JOBS = 3


def hiring_score(js: list[dict]) -> dict | None:
    n = len(js)
    if n < SCORE_MIN_JOBS:
        return None
    share = lambda pred: sum(1 for j in js if pred(j)) / n  # noqa: E731
    sal = share(lambda j: j.get("salary_min"))
    no_german = share(lambda j: j["german_level"] in ("not_required", "nice_to_have"))
    unmentioned = share(lambda j: j["german_level"] == "not_mentioned")
    visa = share(lambda j: j.get("visa_sponsorship") or j.get("relocation"))
    new30 = sum(1 for j in js if parse_ts(j.get("first_seen_at")) >= NOW - dt.timedelta(days=30))
    ages = sorted(max(0, (NOW - parse_ts(j.get("posted_at"))).days) for j in js)
    median_age = ages[n // 2]
    reposted = share(lambda j: (j.get("repost_count") or 0) > 0)
    clamp = lambda x: max(0, min(100, round(x)))  # noqa: E731
    factors = [
        ("salary", "Salary transparency", clamp(sal / 0.6 * 100), f"{round(sal * 100)}% of jobs show a salary"),
        ("language", "English-friendly", clamp((no_german + 0.6 * unmentioned) * 100),
         f"{round(no_german * 100)}% say German isn't needed, {round(unmentioned * 100)}% don't mention it"),
        ("visa", "Visa & relocation", clamp(visa / 0.5 * 100), f"{round(visa * 100)}% mention visa sponsorship or relocation"),
        ("activity", "Hiring activity", clamp(new30 / 5 * 100), f"{new30} new job{'s' if new30 != 1 else ''} in the last 30 days"),
        ("freshness", "Fresh postings", clamp((90 - median_age) / 76 * 100), f"open jobs are {median_age} days old (median)"),
        ("reposts", "Stable postings", clamp((1 - min(1, reposted / 0.5)) * 100), f"{round(reposted * 100)}% of jobs were reposted"),
    ]
    total = round(sum(p * SCORE_WEIGHTS[k] for k, _, p, _ in factors) / sum(SCORE_WEIGHTS.values()))
    return {"t": total, "n": n, "f": [list(f) for f in factors]}


def score_grade(points: int) -> str:
    return ("Excellent" if points >= 85 else "Very good" if points >= 70 else "Good" if points >= 55
            else "Fair" if points >= 40 else "Limited")


def stars_html(points: int, cls: str = "") -> str:
    """Five stars filled to points/100 (half-star precision), as text so it stays crisp."""
    pct = round(points / 10) * 10
    return (f'<span class="stars {cls}" role="img" aria-label="{points / 20:.1f} out of 5 stars">'
            f'<span class="stars-fill" style="width:{pct}%">★★★★★</span>★★★★★</span>')


def score_card_html(sc: dict | None, company: str, sid: str) -> str:
    if not sc:
        return ""
    rows = "".join(f"""<li><div class="sc-row"><span>{e(label)}</span>{stars_html(p, 'sm')}<b>{p}</b></div>
      <p>{e(text)}</p></li>""" for _, label, p, text in sc["f"])
    weights = "".join(f"<li><b>{e(label)}</b> — {SCORE_WEIGHTS[k]}%</li>" for k, label, _, _ in sc["f"])
    return f"""<section class="score-card">
  <div class="sc-top">
    <div><p class="sc-kicker">Stellenly Hiring Score</p>
      <div class="sc-total"><b>{sc['t'] / 20:.1f}</b>{stars_html(sc['t'])}</div>
      <p class="sc-grade">{score_grade(sc['t'])} · {sc['t']}/100 points · based on {sc['n']} open jobs</p></div>
    <button type="button" class="sc-help" popovertarget="{sid}">ⓘ How we calculate this</button>
  </div>
  <ul class="sc-list">{rows}</ul>
  <div popover id="{sid}" class="sc-pop">
    <h4>How the Hiring Score works</h4>
    <p>It rates how {e(company)} hires — based only on its current job postings on Stellenly, <b>not on employee
    reviews</b>. Each factor gives 0–100 points; the total is their weighted average (100 points = 5 stars):</p>
    <ul>{weights}</ul>
    <p class="muted small">Salary: full points when 60%+ of jobs show a salary · English: German not needed counts fully,
    "not mentioned" 60% · Visa: full points at 50%+ · Activity: full points at 5+ new jobs in 30 days · Freshness: full
    points when jobs are under 2 weeks old · Stable: fewer reposts score higher. Needs at least {SCORE_MIN_JOBS} open jobs;
    updated daily.</p>
  </div>
</section>"""


def fetch_logo(slug: str, website: str | None) -> str | None:
    """Company logo, downloaded once and served from our own site (no third party sees visitors)."""
    path = WEB / "logos" / f"{slug}.png"
    if path.exists():
        return f"logos/{slug}.png"
    host = re.sub(r"^https?://(www\.)?", "", website or "").split("/")[0]
    if not host:
        return None
    try:
        r = requests.get("https://www.google.com/s2/favicons", params={"domain": host, "sz": 128}, timeout=15)
        png = r.content
        # Unknown sites get a 404 with a 16×16 generic globe; real logos come back at the requested size.
        if r.status_code != 200 or not png.startswith(b"\x89PNG") or int.from_bytes(png[16:20], "big") < 32:
            return None
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(r.content)
        return f"logos/{slug}.png"
    except requests.RequestException:
        return None


def write_company_index(cos: list[dict]) -> None:
    """web/data/companies-index.json: what the job popup shows about a company (keyed like co_key() in app.js)."""
    index = {}
    for c in cos:
        m = c["meta"] or {}
        if not (m or c["page"]):
            continue
        entry = {"n": c["name"], "u": f"companies/{c['slug']}.html" if c["page"] else None, "sc": c.get("score")}
        if m:
            entry.update({"l": fetch_logo(c["slug"], m.get("website")), "i": m.get("industry"), "f": m.get("founded"),
                          "z": m.get("size"), "h": m.get("hq"), "st": int(bool(m.get("startup"))),
                          "d": m.get("description"), "w": m.get("website")})
        for name in {c["name"], *c["names"], *(m.get("aliases") or [])}:
            index[co_key(name)] = {k: v for k, v in entry.items() if v is not None}
    (WEB / "data" / "companies-index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")),
                                              encoding="utf-8")


def build_companies(jobs: list[dict]) -> list[str]:
    cos = load_companies(jobs)
    write_company_index(cos)
    out = WEB / "companies"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.html"):
        old.unlink()

    # --- one page per company (good for "<company> jobs in English" searches)
    for c in (c for c in cos if c["page"]):
        m = c["meta"] or {}
        where = ", ".join(f"{k} ({n})" for k, n in c["cities"].most_common(6))
        ld = {"@context": "https://schema.org", "@type": "Organization", "name": c["name"],
              **({"url": m["website"]} if m.get("website") else {}),
              **({"foundingDate": str(m["founded"])} if m.get("founded") else {}),
              **({"description": m["description"]} if m.get("description") else {})}
        links = (f'<a class="btn" href="{e(m["website"])}" target="_blank" rel="noopener">Company website ↗</a>'
                 if m.get("website") else "")
        body = f"""<p class="crumbs"><a href="../companies.html">Companies</a> › {e(c['name'])}</p>
<h1>{e(c['name'])}</h1>
<div class="badges">{co_badges(c)}</div>
{f'<p class="lead">{e(m["description"])}</p>' if m.get("description") else ""}
<dl class="facts">{co_facts(c)}<div><dt>Open jobs</dt><dd>{len(c['jobs'])}</dd></div></dl>
{score_card_html(c.get('score'), c['name'], 'score-help')}
<p class="co-links">{links}<a class="btn primary" href="../index.html?q={e(requests.utils.quote(c['name']))}">Filter these jobs by German level &amp; salary →</a></p>
<h2>{jobs_word(len(c['jobs']))} in English{f" · {e(where)}" if where else ""}</h2>
{job_list_html(c['jobs'][:60], '../')}
<p class="muted small">Updated daily from the company's own job board and public job APIs. Company facts are approximate.</p>"""
        desc = (m.get("description") or f"English-speaking jobs at {c['name']} in Germany.")
        (out / f"{c['slug']}.html").write_text(page(
            f"{c['name']} jobs in Germany (English)", f"{jobs_word(len(c['jobs']))} at {c['name']}. {desc}"[:300],
            body, f"companies/{c['slug']}.html", 1,
            extra_head=f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'),
            encoding="utf-8")

    # --- directory, grouped by city
    by_city: dict[str, list[tuple[dict, int]]] = {}
    for c in cos:
        cities = dict(c["cities"])
        if c["hq_city"] and c["hq_city"] not in cities:
            cities[c["hq_city"]] = 0
        if not cities:
            continue
        for city, n in cities.items():
            by_city.setdefault(city, []).append((c, n))
    order = sorted(by_city, key=lambda k: (k in (REMOTE, NO_CITY), -len(by_city[k]), k))

    def card(c: dict, city: str, n: int) -> str:
        m = c["meta"]
        href = f"companies/{c['slug']}.html" if c["page"] else f"index.html?q={e(requests.utils.quote(c['name']))}"
        search = e(f"{c['name']} {(m or {}).get('industry', '')} {city}".lower())
        if not m:
            agency = ' <span class="badge warn">Recruiting agency</span>' if c.get("agency") else ""
            return (f'<li class="co-mini" data-search="{search}" data-startup="0"><a href="{href}">{e(c["name"])}</a>{agency}'
                    f' <span class="muted">{jobs_word(n)}</span></li>')
        roles = "".join(f'<li><a href="{e(j["url"])}" target="_blank" rel="noopener nofollow" data-goatcounter-click="apply" data-goatcounter-title="{e(c["name"])}">{e(j["title"])}</a></li>'
                        for j in [j for j in c["jobs"] if place(j) == city][:3])
        hq = ' <span class="badge">HQ</span>' if c["hq_city"] == city else ""
        return f"""<li class="co-card" data-search="{search}" data-startup="{int(bool(m.get('startup')))}">
  <div class="co-head"><h3><a href="{href}">{e(c['name'])}</a>{hq}</h3><span class="co-count">{jobs_word(n)}</span></div>
  {f'<p class="score-chip" title="Stellenly Hiring Score: {c["score"]["t"]}/100">★ {c["score"]["t"] / 20:.1f} <span>Hiring Score</span></p>' if c.get("score") else ""}
  <div class="badges">{co_badges(c)}</div>
  <p class="co-desc">{e(m['description'])}</p>
  <dl class="co-facts">{co_facts(c)}</dl>
  {f'<ul class="co-roles">{roles}</ul>' if roles else ""}
</li>"""

    sections = []
    for city in order:
        items = sorted(by_city[city], key=lambda t: (t[0]["meta"] is None, -t[1], t[0]["name"].lower()))
        cards = "".join(card(c, city, n) for c, n in items if c["meta"])
        minis = "".join(card(c, city, n) for c, n in items if not c["meta"])
        total = sum(n for _, n in items)
        sections.append(f"""<section class="co-city" id="city-{slugify(city)}" data-city="{e(city)}">
  <h2>{e(city)} <span class="muted">· {len(items)} compan{'ies' if len(items) != 1 else 'y'} · {total} job{'s' if total != 1 else ''}</span></h2>
  {f'<ul class="co-grid">{cards}</ul>' if cards else ""}
  {f'<details class="co-more"{" open" if not cards else ""}><summary>More employers hiring in {e(city)} ({minis.count("<li")})</summary><ul class="co-minis">{minis}</ul></details>' if minis else ""}
</section>""")
    chips = "".join(f'<a class="tag" href="#city-{slugify(c)}" data-city="{e(c)}">{e(c)} <span class="n">{len(by_city[c])}</span></a>'
                    for c in order[:16])

    # --- map markers: one per company and city, jittered around the city centre
    markers = []
    for city in order:
        center = geo.city_coords(city) if city not in (REMOTE, NO_CITY) else None
        if not center:
            continue
        for c, n in by_city[city]:
            m = c["meta"] or {}
            h = zlib.crc32(f"{c['name']}|{city}".encode())
            ang, rad = math.radians(h % 360), 0.004 + (h >> 9) % 100 / 100 * 0.018
            markers.append({"n": c["name"], "c": city, "y": round(center[0] + rad * 0.62 * math.sin(ang), 5),
                            "x": round(center[1] + rad * math.cos(ang), 5), "k": n,
                            "u": f"companies/{c['slug']}.html" if c["page"] else None, "s": int(bool(m.get("startup"))),
                            "i": m.get("industry"), "f": m.get("founded"), "z": m.get("size"),
                            "r": [[j["title"][:90], j["url"]] for j in c["jobs"] if place(j) == city][:5]})
    (WEB / "data" / "companies-map.json").write_text(json.dumps(markers, ensure_ascii=False, separators=(",", ":")),
                                            encoding="utf-8")
    # City dropdown on the search page: only the city values of jobs that really are in Germany.
    german_cities = sorted({j["city"] for j in jobs if j.get("city") and place(j) not in (None, REMOTE, NO_CITY)})
    (WEB / "data" / "german-cities.json").write_text(json.dumps(german_cities, ensure_ascii=False), encoding="utf-8")

    n_jobs = sum(len(c["jobs"]) for c in cos)
    n_cities = len([c for c in order if c not in (REMOTE, NO_CITY)])
    body = f"""<h1>Companies hiring in English across Germany</h1>
<p class="lead">{len(cos):,} employers · {n_jobs:,} open English-speaking jobs · {n_cities} cities.
Hover a pin on the map to see who is hiring and for what.</p>
<div class="co-toolbar">
  <input id="co-search" type="search" placeholder="Filter by company, industry or city — e.g. fintech, Munich" aria-label="Filter companies">
  <label class="chip"><input type="checkbox" id="co-startups"> 🚀 Startups only</label>
</div>
<div class="tag-cloud co-chips">{chips}</div>
<div id="co-map" class="co-map" aria-label="Map of companies">
  <div class="map-consent">
    <p class="map-consent-title">Interactive company map</p>
    <p class="muted">See where each company is hiring. Hover a pin for its open positions.</p>
    <button type="button" class="btn primary" id="map-load">Show map</button>
    <p class="muted small">The map loads tiles from OpenStreetMap, which receives your IP address.
      <label><input type="checkbox" id="map-remember" checked> Remember my choice</label> · <a href="privacy.html#map">Privacy</a></p>
  </div>
</div>
<p id="co-empty" class="empty" hidden>No company matches your filter.</p>
{"".join(sections)}
<p class="muted small">Company facts (founding year, size, HQ) are approximate. <b>Startup</b> = independent, venture-backed,
founded 2009 or later, fewer than 5,000 people. Missing a company? It appears here automatically once it has open jobs on our sources.</p>"""
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Companies hiring in English across Germany",
          "url": f"{SITE_URL}/companies.html"}
    (WEB / "companies.html").write_text(page(
        "Companies hiring in English in Germany", f"{len(cos):,} employers in {n_cities} German cities with English-speaking "
        "jobs — startups and global companies, with size, founding year and open positions on a map.", body,
        "companies.html", 0, extra_head=f'<script type="application/ld+json">{json.dumps(ld)}</script>'
                                         '<script src="js/companies.js" defer></script>'), encoding="utf-8")
    return ["companies.html"] + [f"companies/{c['slug']}.html" for c in cos if c["page"]]


def section_banner(sec: dict, n: int, tag: str = "h2", link: bool = True) -> str:
    cover = write_cover(f"section-{sec['id']}", sec, banner=True)
    inner = f"""<img src="{e(cover)}" alt="" loading="lazy" width="1200" height="560">
  <span class="sec-banner-text"><{tag}>{e(sec['title'])}</{tag}><span>{e(sec['intro'])}</span>
  <small>{n} article{'s' if n != 1 else ''}{' · updated daily' if sec['id'] == 'reports' else ''}</small></span>"""
    return (f'<a class="sec-banner" href="{e(sec["href"])}" style="--h:{sec["hue"]}">{inner}</a>' if link
            else f'<div class="sec-banner big" style="--h:{sec["hue"]}">{inner}</div>')


def report_posts(report: dict) -> list[dict]:
    """The current weekly report plus earlier weeks (their pages are kept, frozen after their week)."""
    out = [report]
    for f in sorted((WEB / "blog").glob("job-market-*.html"), reverse=True):
        if f.stem == report["slug"]:
            continue
        m = re.match(r"job-market-(\d{4})-w(\d{2})", f.stem)
        if not m:
            continue
        monday = dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        out.append({"title": f"English-speaking job market in Germany — week {int(m.group(2))}, {m.group(1)}",
                    "description": "Weekly numbers on English-speaking jobs in Germany.", "section": "reports",
                    "date": monday.isoformat(), "updated": (monday + dt.timedelta(days=6)).isoformat(),
                    "minutes": 3, "href": f.name, "cover": write_cover(f.stem, SECTIONS["reports"])})
    return out[:12]


def build_section_pages(posts: list[dict], report: dict, resources: dict) -> list[str]:
    cats = {c["id"]: c for c in resources["categories"]}
    paths = []
    for sec in SECTIONS.values():
        items = report_posts(report) if sec["id"] == "reports" else [p for p in posts if section_of(p)["id"] == sec["id"]]
        sources = "".join(resource_cards(cats[c], "../")[0] for c in sec["resources"] if c in cats)
        others = "".join(f'<a class="tag" href="{e(s["href"])}">{e(s["title"])}</a>' for s in SECTIONS.values() if s is not sec)
        body = f"""<p class="crumbs"><a href="index.html">Guides</a> › {e(sec['title'])}</p>
{section_banner(sec, len(items), tag="h1", link=False)}
<div class="post-grid">{"".join(post_card(p) for p in items) or '<p class="muted">New articles are on the way.</p>'}</div>
{f'<section class="post-sources"><h2>Official sources &amp; tools</h2>{sources}</section>' if sources else ""}
<nav class="other-sections"><p><b>More topics</b></p><div class="tag-cloud">{others}</div></nav>"""
        (WEB / "blog" / sec["href"]).write_text(page(
            f"{sec['title']} — guides for working in Germany", sec["intro"], body, f"blog/{sec['href']}", 1,
            main_class="guides-page"), encoding="utf-8")
        paths.append(f"blog/{sec['href']}")
    return paths


def build_blog_index(posts: list[dict], report: dict) -> None:
    guides = sorted(posts, key=lambda p: p.get("date", ""), reverse=True)
    featured = guides[0] if guides else None
    blocks = []
    for sec in SECTIONS.values():
        items = report_posts(report) if sec["id"] == "reports" else [p for p in guides if section_of(p)["id"] == sec["id"]]
        if not items:
            continue
        more = (f'<a class="sec-more" href="{e(sec["href"])}">All {len(items)} in {e(sec["title"])} →</a>'
                if len(items) > 3 else "")
        blocks.append(f"""<section class="sec-block">
  {section_banner(sec, len(items))}
  <div class="post-grid">{"".join(post_card(p) for p in items[:3])}</div>{more}
</section>""")
    chips = "".join(f'<a class="tag" href="{e(s["href"])}">{e(s["title"])}</a>' for s in SECTIONS.values())
    body = f"""<section class="page-hero">
  <p class="eyebrow">Guides · updated {fmt_date(TODAY.isoformat())}</p>
  <h1>Guides for working in Germany</h1>
  <p class="lead">Practical, fact-checked guides for internationals — visas, contracts, salary and settling in — plus a
  job-market report that updates every day.</p>
  <nav class="tag-cloud" aria-label="Topics">{chips}</nav>
</section>
{f'<div class="featured-wrap"><p class="kicker">Latest</p>{post_card(featured, featured=True)}</div>' if featured else ""}
<aside class="cta"><b>This week's numbers:</b> <a href="{e(report['href'])}">{e(report['title'])}</a></aside>
{"".join(blocks)}"""
    (WEB / "blog" / "index.html").write_text(page("Guides & job-market reports", "Guides about the Blue Card, German "
                                                   "requirements, salaries and your first weeks in Germany.", body,
                                                   "blog/index.html", 1, main_class="guides-page"), encoding="utf-8")

    items = "".join(f"""<item><title>{e(p['title'])}</title><link>{SITE_URL}/{p['path']}</link>
<guid>{SITE_URL}/{p['path']}</guid><pubDate>{dt.datetime.fromisoformat(p.get('date') or TODAY.isoformat()).strftime('%a, %d %b %Y 00:00:00 +0000')}</pubDate>
<description>{e(p.get('description', ''))}</description></item>""" for p in [report] + guides)
    (WEB / "blog" / "feed.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{e(SITE['site_name'])} — Guides</title><link>{SITE_URL}/blog/</link>
<description>Guides and weekly job-market reports</description>{items}</channel></rss>""")


def write_title_suggestions(jobs: list[dict]) -> None:
    """web/data/job-titles.json: [[title, open jobs with that title], ...] for the search box autocomplete
    (most common first; the page shows only the titles).
    Titles without seniority, gender tags or team suffix ("Senior Data Scientist (m/w/d) – NLP" -> "Data Scientist")."""
    forms: dict[str, Counter] = {}
    for j in jobs:
        t = skill_check.role_name(j["title"])
        if len(t) >= 3:
            forms.setdefault(t.lower(), Counter())[t] += 1
    titles = sorted(((f.most_common(1)[0][0], f.total()) for f in forms.values()), key=lambda x: (-x[1], x[0]))
    (WEB / "data" / "job-titles.json").write_text(json.dumps(titles[:1000], ensure_ascii=False, separators=(",", ":")),
                                                  encoding="utf-8")


def build_how_it_works(jobs: list[dict]) -> str:
    index = json.loads((WEB / "data" / "companies-index.json").read_text(encoding="utf-8"))
    body = how_it_works.body(how_it_works.numbers(jobs, index), SCORE_WEIGHTS, fmt_date(TODAY.isoformat()))
    (WEB / "how-it-works.html").write_text(page(
        "How it works", "How Stellenly collects, cleans, AI-checks and scores English-speaking jobs in Germany: "
        "every rule we use to filter out noise.", body, "how-it-works.html", 0, main_class="post-page wiki-page"),
        encoding="utf-8")
    return "how-it-works.html"


def load_role_rows(rows_file: str | None) -> list[dict]:
    """Title + skills of every job in the database (also closed ones) — for the Skill check."""
    if rows_file:
        return json.loads(Path(rows_file).read_text(encoding="utf-8"))
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/role_skill_rows"
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    r = requests.post(url, json={}, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def build_skill_check(rows: list[dict]) -> str:
    roles = skill_check.roles(rows)
    (WEB / "data" / "skill-roles.json").write_text(json.dumps({"updated": TODAY.isoformat(), "roles": roles},
                                                     ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (WEB / "skill-check.html").write_text(page(
        "Skill check", "Pick a role, see the priority of the 10 skills its job postings ask for most and get a free AI report: "
        "what to learn first and how you compare with other candidates.", skill_check.body(roles, len(rows)),
        "skill-check.html", 0, extra_head='<script src="js/config.js" defer></script><script src="js/skill-check.js" defer></script>',
        main_class="post-page skill-page"), encoding="utf-8")
    return "skill-check.html"


def build_sitemap(paths: list[str]) -> None:
    urls = "".join(f"<url><loc>{SITE_URL}/{p.replace('index.html', '')}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>"
                   for p in sorted(set(paths)))
    (WEB / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n'
                                     f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    (WEB / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
                                    f"Sitemap: {SITE_URL}/job-sitemap.xml\n")  # job pages: build/job_pages.py


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs-file")
    ap.add_argument("--role-rows-file")  # offline: [{"title", "skills"}] instead of the role_skill_rows() RPC
    args = ap.parse_args()

    jobs = load_jobs(args.jobs_file)
    stats = compute_stats(jobs)
    resources = json.loads((CONTENT / "resources.json").read_text(encoding="utf-8"))

    posts = build_blog(jobs, stats, resources)
    report = build_report(jobs, stats)
    sections = build_section_pages(posts, report, resources)
    build_blog_index(posts, report)
    build_resources(resources, posts)
    companies = build_companies(jobs)  # writes companies-index.json (logos), which the landing pages use
    landing = build_landing_pages(jobs, stats)
    wiki = build_how_it_works(jobs)
    write_title_suggestions(jobs)
    skills_page = [build_skill_check(load_role_rows(args.role_rows_file))] if SKILL_CHECK else []
    reports = [f"blog/{p.name}" for p in (WEB / "blog").glob("job-market-*.html")]
    build_sitemap(["index.html", "resources.html", "blog/index.html"] + [p["path"] for p in posts] + reports
                  + sections + landing + companies + [wiki] + skills_page)
    print(f"Built: {len(posts)} guides, report {report['slug']}, {len(landing)} landing pages, "
          f"{len(companies) - 1} company pages, "
          f"{stats['active']} jobs ({stats['no_german_pct']}% no German)")


if __name__ == "__main__":
    main()
