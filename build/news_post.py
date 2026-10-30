"""Post English news about immigration, visas, jobs and the labour market in Germany to the
#news channel of the Stellenly Discord.

Runs every 3 hours (news.yml). Reads the RSS feeds in data/news_feeds.json, keeps stories from the
last MAX_AGE_DAYS whose title or summary matches a keyword, drops the same story from a second
source, and posts the newest MAX_POSTS as cards (title, short summary, source, link) in one
message. Remembers posted stories in a small state file kept in the GitHub Actions cache, so a
story is never posted twice; the first run posts only FIRST_RUN stories. Skips quietly without
DISCORD_NEWS_WEBHOOK_URL.

    DISCORD_NEWS_WEBHOOK_URL=https://discord.com/api/webhooks/... python build/news_post.py
    python build/news_post.py --dry-run    # print what would be posted
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "data" / "news_feeds.json").read_text(encoding="utf-8"))
STATE = Path(os.environ.get("NEWS_STATE", Path(__file__).parent / ".news_state.json"))
SITE_URL = os.environ.get("SITE_URL") or "https://www.stellenly.com"
MAX_AGE_DAYS, MAX_POSTS, FIRST_RUN = 3, 5, 3
NOW = dt.datetime.now(dt.timezone.utc)
UA = {"User-Agent": "Mozilla/5.0 (compatible; Stellenly news; +https://www.stellenly.com)"}

WORDS = re.compile(r"\b(" + "|".join(re.escape(k) for k in CONFIG["keywords"]) + ")", re.I)
GERMANY = re.compile(r"\b(" + "|".join(re.escape(k) for k in CONFIG["must_mention"]) + ")", re.I)
EXCLUDE = re.compile(r"\b(" + "|".join(re.escape(k) for k in CONFIG["exclude"]) + r")\b", re.I) if CONFIG["exclude"] else None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _date(s: str) -> dt.datetime | None:
    try:
        d = parsedate_to_datetime(s) if re.match(r"^[A-Z][a-z]{2},", s) else dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def read_feed(name: str, url: str, sources: list[str] | None = None) -> list[dict]:
    """RSS 2.0, RSS 1.0 (RDF, DW) and Atom items as {title, link, summary, source, date}; with `sources`,
    only items from those publishers (Google News names the publisher after the title)."""
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for el in ET.fromstring(r.content).iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        f = {_local(c.tag): (c.text or "").strip() or c.get("href", "") for c in el}
        title, source = plain(f.get("title", "")), name
        if name == "Google News" and " - " in title:  # "Headline - Publisher"
            title, source = title.rsplit(" - ", 1)
        date = _date(f.get("pubDate") or f.get("date") or f.get("published") or f.get("updated") or "")
        if sources and source not in sources:
            continue
        summary = plain(f.get("description") or f.get("summary", ""))
        if summary.startswith(title):  # Google News: the summary only repeats the headline
            summary = ""
        if title and f.get("link") and date:
            out.append({"title": title, "link": f["link"], "summary": summary, "source": source, "date": date})
    return out


def relevant(item: dict) -> bool:
    text = f"{item['title']} {item['summary']}"
    return bool(WORDS.search(text) and GERMANY.search(text)) and not (EXCLUDE and EXCLUDE.search(text))


def key(item: dict) -> str:
    """The same story from two sources gets the same key (Google News repeats DW and The Local)."""
    return re.sub(r"[^a-z0-9]+", " ", item["title"].lower()).strip()[:70]


def collect() -> list[dict]:
    items, seen = [], set()
    for feed in CONFIG["feeds"]:
        try:
            found = read_feed(feed["name"], feed["url"], feed.get("sources"))
        except (requests.RequestException, ET.ParseError) as err:
            print(f"News: {feed['name']} failed ({err}), skipping it this time")
            continue
        for it in found:
            if it["date"] > NOW - dt.timedelta(days=MAX_AGE_DAYS) and relevant(it) and key(it) not in seen:
                seen.add(key(it))
                items.append(it)
    return sorted(items, key=lambda it: it["date"], reverse=True)


def payload(items: list[dict]) -> dict:
    return {
        "username": "Stellenly News",
        "content": f"📰 **News for internationals in Germany** · English-speaking jobs: <{SITE_URL}>",
        "embeds": [{"title": it["title"][:250], "url": it["link"], "description": it["summary"][:300],
                    "footer": {"text": it["source"]}, "timestamp": it["date"].isoformat(), "color": 0x4F46E5}
                   for it in items],
        "allowed_mentions": {"parse": []},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the stories instead of posting them")
    args = ap.parse_args()
    hook = os.environ.get("DISCORD_NEWS_WEBHOOK_URL")
    if not hook and not args.dry_run:
        print("News: DISCORD_NEWS_WEBHOOK_URL not set, skipping")
        return

    first = not STATE.exists()
    posted = {} if first else json.loads(STATE.read_text(encoding="utf-8"))
    posted = {k: t for k, t in posted.items() if _date(t) > NOW - dt.timedelta(days=14)}  # keep it small
    fresh = [it for it in collect() if key(it) not in posted]
    picked = fresh[:FIRST_RUN if first else MAX_POSTS]
    if not picked:
        print("News: nothing new")
    elif args.dry_run:
        for it in picked:
            print(f"- {it['title']} ({it['source']}, {it['date']:%Y-%m-%d %H:%M})\n  {it['summary'][:120]}\n  {it['link'][:90]}")
    else:
        requests.post(hook, json=payload(picked), timeout=30).raise_for_status()
        print(f"News: posted {len(picked)} stories ({len(fresh) - len(picked)} older ones skipped)")
    if not args.dry_run:
        # Everything found now counts as seen: the next run only posts stories that appear after this one.
        STATE.write_text(json.dumps({**posted, **{key(it): NOW.isoformat() for it in fresh}}), encoding="utf-8")


if __name__ == "__main__":
    main()
