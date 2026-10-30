"""Weekly social media posts made from the site's own data: images (1080x1350 JPEG, rendered from HTML in the site's
style by build/social/render.mjs) and a caption. The "Social posts" workflow previews them in Discord, waits for the
owner's approval and then posts them (build/instagram_post.py).

    Monday     visa  : "5 English-speaking jobs that sponsor your visa" (cover + 5 job cards + call to action)
    Wednesday  city  : a city spotlight, a different city each week (numbers + top employers + call to action)
    Friday     fact  : alternating weeks, "How many jobs need German?" or "EU Blue Card salary <year>"

    python build/social_posts.py [visa|city|fact] --out out/social       (default: the post for today's weekday)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "ingest"))
import build_site as b  # noqa: E402
import coats_of_arms  # noqa: E402

e = html.escape
TODAY = dt.date.today()
WEEK = TODAY.isocalendar().week
SITE = "stellenly.com"
BLUE_CARD = {k: int(v) if v.isdigit() else v for k, v in
             re.findall(r"(\w+): (\d+)", re.search(r"BLUE_CARD: \{([^}]*)\}", (WEB / "js" / "config.js").read_text(encoding="utf-8")).group(1))}
TAGS = "#jobsingermany #workingermany #movetogermany #englishjobs #expatsingermany #jobsearch #germany"

CSS = """
@font-face { font-family: "Inter"; font-weight: 100 900; src: url("{web}/fonts/inter-latin.woff2") format("woff2"); }
@font-face { font-family: "Inter"; font-weight: 100 900; src: url("{web}/fonts/inter-latin-ext.woff2") format("woff2");
  unicode-range: U+0100-024F, U+1E00-1EFF; }
* { box-sizing: border-box; margin: 0; }
html, body { width: 1080px; height: 1350px; }
body { font-family: "Inter", system-ui, sans-serif; color: #fff; overflow: hidden; display: flex; flex-direction: column;
  padding: 80px 80px 70px; background: radial-gradient(900px 620px at 92% -8%, rgba(91,99,241,.45), transparent 65%),
  radial-gradient(700px 520px at -10% 108%, rgba(17,167,168,.28), transparent 60%), #0c1630; }
.brand { display: flex; align-items: center; gap: 16px; font-size: 34px; font-weight: 800; letter-spacing: -.02em; }
.brand img { width: 64px; height: 64px; background: #fff; border-radius: 18px; padding: 8px; }
.brand .page { margin-left: auto; font-size: 26px; font-weight: 600; color: #8f9bb8; }
.kicker { margin-top: 70px; font-size: 30px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #a5b4fc; }
h1 { margin-top: 18px; font-size: 84px; line-height: 1.04; font-weight: 800; letter-spacing: -.035em; }
h1 em { font-style: normal; background: linear-gradient(90deg, #a5b4fc, #5eead4); -webkit-background-clip: text; color: transparent; }
.sub { margin-top: 28px; font-size: 34px; line-height: 1.4; color: #c7d0e6; }
.card { margin-top: 56px; background: #fff; color: #10172a; border-radius: 34px; padding: 48px; }
.card .logo { width: 120px; height: 120px; border-radius: 26px; border: 2px solid #e4e7ef; object-fit: contain; padding: 14px;
  display: grid; place-items: center; font-size: 44px; font-weight: 800; }
.card h2 { margin-top: 34px; font-size: 54px; line-height: 1.12; letter-spacing: -.02em; }
.card .meta { margin-top: 18px; font-size: 32px; color: #5b6478; }
.card .meta b { color: #10172a; }
.pills { margin-top: 30px; display: flex; flex-wrap: wrap; gap: 14px; }
.pill { font-size: 28px; font-weight: 700; padding: 10px 20px; border-radius: 999px; background: #eef0f6; color: #2b3245; }
.pill.ok { background: #dcf7e8; color: #0b6b3a; } .pill.info { background: #e3ecff; color: #1d4ed8; } .pill.bad { background: #fde3e1; color: #b42318; }
.salary { margin-top: 30px; font-size: 44px; font-weight: 800; color: #0b6b3a; }
.salary.none { font-size: 30px; font-weight: 500; color: #8a93a6; }
.stats { margin-top: 54px; display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
.stat { padding: 30px; border-radius: 26px; background: rgba(255,255,255,.07); border: 2px solid rgba(255,255,255,.12); }
.stat b { display: block; font-size: 64px; font-weight: 800; letter-spacing: -.02em; }
.stat span { font-size: 28px; color: #aab5d1; }
.rows { margin-top: 44px; display: grid; gap: 18px; }
.row { display: flex; align-items: center; gap: 24px; padding: 22px 28px; border-radius: 24px; background: rgba(255,255,255,.07);
  border: 2px solid rgba(255,255,255,.12); font-size: 36px; font-weight: 700; }
.row img, .row .logo { width: 76px; height: 76px; border-radius: 18px; background: #fff; object-fit: contain; padding: 8px;
  display: grid; place-items: center; color: #10172a; font-size: 30px; font-weight: 800; }
.row small { margin-left: auto; font-size: 30px; font-weight: 600; color: #a5b4fc; }
.bar { height: 22px; border-radius: 11px; background: rgba(255,255,255,.1); margin-top: 12px; overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 11px; background: linear-gradient(90deg, #818cf8, #5eead4); }
.coa { width: 150px; height: 150px; object-fit: contain; margin-top: 60px; }
.foot { margin-top: auto; display: flex; justify-content: space-between; align-items: center; font-size: 28px; color: #c7d0e6; }
.url { font-size: 38px; font-weight: 800; padding: 16px 28px; border-radius: 18px; background: #4f46e5; color: #fff; }
.swipe { font-size: 30px; color: #a5b4fc; font-weight: 600; }
"""


NAMES: dict[str, str] = {}  # co_key -> the company's display name (companies-index.json), filled by make()


def nice(company: str) -> str:
    return NAMES.get(b.co_key(company)) or company


def required_pct(jobs: list[dict]) -> int:
    """Share of jobs that require German ("not mentioned" doesn't count: most such jobs are fine in English)."""
    return round(100 * sum(j["german_level"] == "required" for j in jobs) / max(len(jobs), 1))


def page(body: str, n: int, total: int) -> str:
    style = CSS.replace("{web}", WEB.as_uri())
    num = f'<span class="page">{n}/{total}</span>' if total > 1 else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{style}</style></head><body>'
            f'<div class="brand"><img src="{(WEB / "img" / "logo.svg").as_uri()}" alt="">Stellenly{num}</div>{body}</body></html>')


def logo(name: str, path: str | None) -> str:
    if path and (WEB / path).exists():
        return f'<img class="logo" src="{(WEB / path).as_uri()}" alt="">'
    words = re.sub(r"\(.*?\)", "", name).split() or ["?"]
    return f'<span class="logo">{e((words[0][0] + (words[1][0] if len(words) > 1 else words[0][1:2])).upper())}</span>'


def german_pill(level: str) -> str:
    cls, label = {"not_required": ("ok", "No German needed"), "nice_to_have": ("info", "German: nice to have"),
                  "required": ("bad", "German required")}.get(level, ("", "German: not mentioned"))
    return f'<span class="pill {cls}">{label}</span>'


def salary(j: dict) -> str:
    if not j.get("salary_min"):
        return '<div class="salary none">Salary not listed</div>'
    hi = j.get("salary_max")
    return f'<div class="salary">{b.euro(j["salary_min"])}{"–" + b.euro(hi)[1:] if hi and hi != j["salary_min"] else ""} / year</div>'


def cta(text: str) -> str:
    return (f'<p class="kicker">Find yours</p><h1>{text}</h1><p class="sub">Every job shows up front: German level, salary, '
            f'visa sponsorship. Free, no sign-up, updated every 6 hours.</p>'
            f'<div class="foot"><span>🔗 Link in bio</span><span class="url">{SITE}</span></div>')


def post_visa(jobs: list[dict], logos: dict) -> tuple[list[str], str]:
    week_ago = (TODAY - dt.timedelta(days=7)).isoformat()
    pool = [j for j in jobs if j.get("visa_sponsorship") and not j.get("is_agency") and j.get("source") != "amazon"
            and (j.get("first_seen_at") or "") >= week_ago]
    # Known employers first (a logo and a clean name), then a real city, no German needed, a salary, the newest.
    pool.sort(key=lambda j: (bool(logos.get(b.co_key(j["company"]))), b.co_key(j["company"]) in NAMES, bool(j.get("city")),
                             j["german_level"] in ("not_required", "nice_to_have"), bool(j.get("salary_min")),
                             j.get("posted_at") or ""), reverse=True)
    picked, companies = [], set()
    for j in pool:
        if nice(j["company"]) not in companies:
            picked.append(j)
            companies.add(nice(j["company"]))
        if len(picked) == 5:
            break
    total = len(picked) + 2
    slides = [page(f'<p class="kicker">This week · {TODAY:%d %b}</p><h1>{len(picked)} English-speaking jobs that '
                   f'<em>sponsor your visa</em> 🛂</h1><p class="sub">Fresh from company career pages in Germany, '
                   f'with German level and salary shown up front.</p>'
                   f'<div class="foot"><span class="swipe">Swipe →</span><span class="url">{SITE}</span></div>', 1, total)]
    for i, j in enumerate(picked, 2):
        slides.append(page(f'<div class="card">{logo(j["company"], logos.get(b.co_key(j["company"])))}'
                           f'<h2>{e(j["title"][:90])}</h2><p class="meta"><b>{e(nice(j["company"]))}</b> · {e(j.get("city") or "Germany")}</p>'
                           f'<div class="pills">{german_pill(j["german_level"])}<span class="pill ok">🛂 Visa sponsorship</span>'
                           f'{"<span class=" + chr(34) + "pill ok" + chr(34) + ">✈️ Relocation</span>" if j.get("relocation") else ""}</div>'
                           f'{salary(j)}</div><div class="foot"><span>Search “{e(nice(j["company"]))}” on</span><span class="url">{SITE}</span></div>',
                           i, total))
    slides.append(page(cta("More jobs with <em>visa sponsorship</em>"), total, total))
    lines = "\n".join(f"{n}. {j['title']} at {nice(j['company'])} ({j.get('city') or 'Germany'})" for n, j in enumerate(picked, 1))
    caption = (f"🛂 {len(picked)} English-speaking jobs in Germany that sponsor your visa, posted this week:\n\n{lines}\n\n"
               f"Every job on Stellenly shows up front whether German is required, the salary and visa support. "
               f"Free, no sign-up.\n\n🔗 Link in bio: {SITE}\n\n#visasponsorship #bluecard {TAGS}")
    return slides, caption


def post_city(jobs: list[dict], logos: dict) -> tuple[list[str], str]:
    by_city = Counter(j["city"] for j in jobs if j.get("city") and j["city"] != "Remote" and b.normalize_city(j["city"]) == j["city"])
    cities = [c for c, n in by_city.most_common(8) if n >= 20]
    city = cities[WEEK % len(cities)]  # a different city each week
    sel = [j for j in jobs if j.get("city") == city]
    s = b.compute_stats(sel)
    counts = Counter(nice(j["company"]) for j in sel if not j.get("is_agency"))
    top = sorted(counts.items(), key=lambda x: (b.co_key(x[0]) in NAMES, x[1]), reverse=True)[:5]  # known employers first
    coat = coats_of_arms.image(f"city:{city}")
    coat_html = f'<img class="coa" src="{(WEB / coat).as_uri()}" alt="">' if coat else ""
    stats = [(f"{s['active']:,}", "English-speaking jobs"), (f"{100 - required_pct(sel)}%", "don't list German as a must"),
             (f"{s['visa']:,}", "offer visa sponsorship")]
    stats.append((b.euro(s["median_salary"]), "median listed salary") if s["median_salary"] else (f"{len(top)}+", "top employers"))
    slides = [
        page(f'{coat_html}<p class="kicker">City spotlight</p><h1>English-speaking jobs in <em>{e(city)}</em></h1>'
             f'<div class="stats">{"".join(f"<div class=stat><b>{v}</b><span>{k}</span></div>" for v, k in stats)}</div>'
             f'<div class="foot"><span class="swipe">Swipe →</span><span class="url">{SITE}</span></div>', 1, 3),
        page(f'<p class="kicker">Who is hiring in {e(city)}</p><h1>Top employers <em>right now</em></h1><div class="rows">'
             + "".join(f'<div class="row">{logo(c, logos.get(b.co_key(c)))}{e(c)}<small>{n} job{"s" if n != 1 else ""}</small></div>'
                       for c, n in top)
             + f'</div><div class="foot"><span>Open jobs, today</span><span class="url">{SITE}</span></div>', 2, 3),
        page(cta(f"All jobs in <em>{e(city)}</em>"), 3, 3),
    ]
    slug = re.sub(r"[^a-z]", "", city.lower())
    caption = (f"📍 City spotlight: {city}\n\n{s['active']:,} English-speaking jobs right now · {100 - required_pct(sel)}% "
               f"don't list German as a must · {s['visa']} offer visa sponsorship"
               + (f" · median listed salary {b.euro(s['median_salary'])}" if s["median_salary"] else "")
               + f".\n\nTop employers: {', '.join(c for c, _ in top)}.\n\nSee every job in {city}, with German level, "
               f"salary and visa support up front.\n\n🔗 Link in bio: {SITE}\n\n#{slug}jobs #{slug} {TAGS}")
    return slides, caption


def post_fact(jobs: list[dict], logos: dict) -> tuple[list[str], str]:
    s = b.compute_stats(jobs)
    if WEEK % 2 == 0:  # "How many jobs need German?"
        g, n, req = s["german"], max(len(jobs), 1), required_pct(jobs)
        rows = [("Not needed, or just a plus", g.get("not_required", 0) + g.get("nice_to_have", 0)),
                ("Not mentioned at all", g.get("not_mentioned", 0)), ("German required", g.get("required", 0))]
        slides = [
            page(f'<p class="kicker">Fact of the week</p><h1>Only <em>{req}%</em> of English-speaking jobs in Germany '
                 f'require German</h1><p class="sub">We read all {len(jobs):,} job ads on Stellenly. What they say about German:</p>'
                 f'<div class="rows">'
                 + "".join(f'<div class="row" style="display:block">{lbl}<small style="float:right">{round(100 * c / n)}%</small>'
                           f'<div class="bar"><i style="width:{max(2, round(100 * c / n))}%"></i></div></div>' for lbl, c in rows)
                 + f'</div><div class="foot"><span>German level on every job</span><span class="url">{SITE}</span></div>', 1, 2),
            page(cta("Find jobs that <em>don't need German</em>"), 2, 2),
        ]
        caption = (f"🗣️ Do you need German to work in Germany? Only {req}% of the {len(jobs):,} English-speaking job ads "
                   f"on Stellenly require it:\n\n"
                   + "\n".join(f"• {lbl}: {round(100 * c / n)}%" for lbl, c in rows)
                   + f"\n\n\"Not mentioned\" usually means the team works in English, but German still helps in daily life, "
                   f"so ask in the interview. Every job on Stellenly shows its German level, with the exact quote from the "
                   f"posting.\n\n🔗 Link in bio: {SITE}\n\n#learngerman #nogermanneeded {TAGS}")
        return slides, caption
    with_sal = [j for j in jobs if j.get("salary_min")]
    meets = sum((j.get("salary_max") or j["salary_min"]) >= BLUE_CARD["standard"] for j in with_sal)
    slides = [
        page(f'<p class="kicker">Guide · EU Blue Card {BLUE_CARD["year"]}</p><h1>The salary you need for a <em>Blue Card</em></h1>'
             f'<div class="stats"><div class="stat"><b>{b.euro(BLUE_CARD["standard"])}</b><span>standard minimum, gross per year</span></div>'
             f'<div class="stat"><b>{b.euro(BLUE_CARD["reduced"])}</b><span>reduced: IT/STEM, health, recent graduates</span></div></div>'
             f'<p class="sub" style="margin-top:44px">Of the jobs on Stellenly that list a salary, {round(100 * meets / max(len(with_sal), 1))}% '
             f'reach the standard minimum.</p><div class="foot"><span>Full guide on</span><span class="url">{SITE}</span></div>', 1, 2),
        page(cta("Jobs that <em>qualify</em> for a Blue Card"), 2, 2),
    ]
    caption = (f"💶 EU Blue Card {BLUE_CARD['year']}: the salary you need\n\n• Standard: {b.euro(BLUE_CARD['standard'])} gross a year\n"
               f"• Reduced ({b.euro(BLUE_CARD['reduced'])}): IT/STEM jobs, health care, recent graduates\n\n"
               f"Stellenly marks every job whose listed salary meets the Blue Card minimum. Read the full guide and find "
               f"matching jobs.\n\n🔗 Link in bio: {SITE}\n\n#bluecard #eubluecard #visa {TAGS}")
    return slides, caption


POSTS = {"visa": post_visa, "city": post_city, "fact": post_fact}
WEEKDAY = {0: "visa", 2: "city", 4: "fact"}  # Monday, Wednesday, Friday


def make(kind: str, out: Path) -> dict:
    """Writes out/slide-N.html, renders them to slide-N.jpg, and out/post.json (kind, caption, slide files)."""
    jobs = b.load_jobs(None)
    index = json.loads((WEB / "data" / "companies-index.json").read_text(encoding="utf-8"))
    logos = {k: v["l"] for k, v in index.items() if v.get("l")}
    NAMES.update({k: v["n"] for k, v in index.items() if v.get("n")})
    slides, caption = POSTS[kind](jobs, logos)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("slide-*"):
        old.unlink()
    for i, s in enumerate(slides, 1):
        (out / f"slide-{i:02d}.html").write_text(s, encoding="utf-8")
    subprocess.run(["node", str(ROOT / "build" / "social" / "render.mjs"), str(out)], check=True)
    post = {"kind": kind, "date": TODAY.isoformat(), "caption": caption,
            "slides": sorted(p.name for p in out.glob("slide-*.jpg"))}
    (out / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=1), encoding="utf-8")
    return post


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", nargs="?", choices=list(POSTS), help="default: the post for today's weekday")
    ap.add_argument("--out", default=str(ROOT / "out" / "social"))
    args = ap.parse_args()
    kind = args.kind or WEEKDAY.get(TODAY.weekday())
    if not kind:
        sys.exit(f"No post planned on {TODAY:%A}")
    post = make(kind, Path(args.out))
    print(f"{kind}: {len(post['slides'])} slides in {args.out}\n\n{post['caption']}")
