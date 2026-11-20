"""News page data (content/news.json): English news for internationals in Germany (visa, Chancenkarte, housing,
moving and living, jobs) plus the news and press releases of the Bundesagentur für Arbeit, translated to English.

Runs in "Deploy website" before build_site.py, which turns content/news.json into news.html and the news line on
the main page. The deploy commits content/news.json, so every story is read and translated only once and the page
keeps its history (MAX_AGE_DAYS). Never fails the deploy: a source or the LLM that fails is retried on the next run.

  - English feeds and topics: data/news_page.json. Each story gets the first topic whose keywords match, and a photo:
    the feed's image, else the article's preview image (og:image). Google News links can't be read: no photo, the
    page shows the topic's illustration instead.
  - Bundesagentur für Arbeit: the tiles on /presse and /news (no RSS feed). New items: the article is read and the LLM
    writes an English headline and a 2-3 sentence summary (prompts.md "news_translation"), with a link to the German
    page. Items the LLM marks as not relevant (press photos, website notices) are remembered and left out.

    LLM_API_KEY=... python build/news_collect.py [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "ingest"))
import news_post  # noqa: E402  (feed date parsing, plain text, dedup key, user agent)

CONFIG = json.loads((ROOT / "data" / "news_page.json").read_text(encoding="utf-8"))
STORE = ROOT / "content" / "news.json"
BA = "https://www.arbeitsagentur.de"
BA_PAGES = ("/presse", "/news")
BA_SOURCE = "Bundesagentur für Arbeit"
MAX_AGE_DAYS, MAX_ITEMS = 60, 300
FEED_MAX_AGE_DAYS = 14   # a feed story older than this is not added any more
MAX_TRANSLATIONS = 8     # per run; the rest waits for the next deploy (free LLM quota is shared with "Job insights")
MAX_PHOTO_LOOKUPS = 40   # article pages read per run for a preview image
NOW = news_post.NOW
UA = news_post.UA


def _rx(words: list[str]) -> re.Pattern | None:
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + ")", re.I) if words else None


TOPICS = [(t["id"], _rx(t["keywords"])) for t in CONFIG["topics"] if t["keywords"]]
GERMANY, EXCLUDE = _rx(CONFIG["must_mention"]), _rx(CONFIG["exclude"])


def load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": [], "skipped": []}


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def topic_of(text: str) -> str | None:
    return next((tid for tid, rx in TOPICS if rx.search(text)), None)


def _photo_ok(url: str | None) -> str | None:
    """Real photos only: no logos, icons or placeholder images."""
    if not url or not url.startswith("https://") or re.search(r"logo|icon|placeholder|default|favicon", url, re.I):
        return None
    return url


def read_feed(feed: dict) -> list[dict]:
    """RSS 2.0, RSS 1.0 (DW) and Atom items as {title, link, summary, source, date, image}."""
    r = requests.get(feed["url"], headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for el in ET.fromstring(r.content).iter():
        if news_post._local(el.tag) not in ("item", "entry"):
            continue
        f, image = {}, None
        for c in el:
            tag = news_post._local(c.tag)
            f.setdefault(tag, (c.text or "").strip() or c.get("href", ""))
            if tag in ("content", "thumbnail", "enclosure") and c.get("url") and (c.get("medium") == "image"
                                                                                  or "image" in (c.get("type") or "image")):
                image = image or c.get("url")
        raw = f.get("encoded") or f.get("description") or f.get("summary", "")
        if not image and (m := re.search(r'<img[^>]+src="(https://[^"]+)"', raw)):
            image = m[1]
        title, source = news_post.plain(f.get("title", "")), feed["name"]
        if feed["name"] == "Google News" and " - " in title:  # "Headline - Publisher"
            title, source = title.rsplit(" - ", 1)
            if source not in CONFIG["sources"]:
                continue
        summary = news_post.plain(raw)
        if summary.startswith(title):  # Google News: the summary only repeats the headline
            summary = ""
        date = news_post._date(f.get("pubDate") or f.get("date") or f.get("published") or f.get("updated") or "")
        if title and f.get("link") and date:
            out.append({"title": title, "link": f["link"], "summary": summary[:600], "source": source, "date": date,
                        "image": _photo_ok(image), "germany_only": feed.get("germany_only", False)})
    return out


def og_image(url: str) -> str | None:
    if "news.google.com" in url:  # a redirect page: the article itself can't be read
        return None
    try:
        page = requests.get(url, headers=UA, timeout=15).text[:200_000]
    except requests.RequestException:
        return None
    m = (re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
         or re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', page))
    return _photo_ok(html.unescape(m[1])) if m else None


def ba_list() -> list[dict]:
    """The tiles on the BA press and news pages: {link, title_de, date}. Tiles without a date are hub pages."""
    out, seen = [], set()
    for path in BA_PAGES:
        page = requests.get(BA + path, headers=UA, timeout=30).text
        for tile in re.findall(r'<section class="ba-tile ba-link-tile">(.*?)</section>', page, re.S):
            href = re.search(r'href="(/(?:presse|news)/[^"#?]+)"', tile)
            title = re.search(r'<h3 class="ba-heading"[^>]*>(.*?)</h3>', tile, re.S)
            day = re.search(r"\b(\d{2})\.(\d{2})\.(20\d{2})\b", tile)
            if href and title and day and href[1] not in seen:
                seen.add(href[1])
                out.append({"link": BA + href[1], "title_de": _text(title[1]),
                            "date": dt.datetime(int(day[3]), int(day[2]), int(day[1]), 12, tzinfo=dt.timezone.utc)})
    return out


def ba_article(url: str) -> str:
    """The article text: <main> without navigation, buttons and the image credits at the end."""
    page = requests.get(url, headers=UA, timeout=30).text
    m = re.search(r"<main\b.*?</main>", page, re.S)
    body = re.sub(r"<(script|style|nav|svg|button|form|aside)\b.*?</\1>", " ", m[0] if m else page, flags=re.S)
    body = re.sub(r"</(p|h\d|li|div|section)>", "\n", body)
    text = re.sub(r"[ \t\xa0]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text.split("\n Bildnachweis")[0]


def translate(item: dict) -> dict | None:
    """{"title", "summary", "relevant"} from the LLM, or None when the LLM is off or busy (retried next run)."""
    import llm_client
    import prompts
    try:
        ans = llm_client.chat_json(prompts.get("news_translation", title=item["title_de"], text=ba_article(item["link"])[:5000]))
    except (llm_client.LLMUnavailable, llm_client.LLMConfigError, requests.RequestException) as err:
        print(f"News page: translation of {item['link']} failed ({type(err).__name__}), retrying next run")
        return None
    title, summary = str(ans.get("title") or "").strip()[:140], str(ans.get("summary") or "").strip()[:600]
    return {"title": title, "summary": summary, "relevant": ans.get("relevant") is not False} if title else None


def collect_feeds(items: dict) -> int:
    keys = {news_post.key(x) for x in items.values()}
    added, lookups = 0, 0
    for feed in CONFIG["feeds"]:
        if feed["name"] == "Google News":
            time.sleep(3)  # Google News answers with an error page to quick series of requests
        try:
            found = read_feed(feed)
        except (requests.RequestException, ET.ParseError) as err:
            print(f"News page: {feed['name']} failed ({err}), skipping it this time")
            continue
        for it in found:
            text = f"{it['title']} {it['summary']}"
            topic = topic_of(text) or feed.get("topic")
            if (it["link"] in items or news_post.key(it) in keys or not topic
                    or it["date"] < NOW - dt.timedelta(days=FEED_MAX_AGE_DAYS)
                    or (EXCLUDE and EXCLUDE.search(text)) or not (it["germany_only"] or GERMANY.search(text))):
                continue
            if not it["image"] and lookups < MAX_PHOTO_LOOKUPS:
                it["image"], lookups = og_image(it["link"]), lookups + 1
            items[it["link"]] = {"title": it["title"], "summary": it["summary"], "source": it["source"], "link": it["link"],
                                 "date": it["date"].isoformat(), "topic": topic, "image": it["image"]}
            keys.add(news_post.key(it))
            added += 1
    return added


def collect_ba(items: dict, skipped: set) -> int:
    todo = [b for b in ba_list() if b["link"] not in items and b["link"] not in skipped
            and b["date"] >= NOW - dt.timedelta(days=MAX_AGE_DAYS)]
    todo.sort(key=lambda b: b["date"], reverse=True)
    if todo and not os.environ.get("LLM_API_KEY"):
        print(f"News page: {len(todo)} BA items wait for a translation (no LLM_API_KEY)")
        return 0
    done = 0
    for b in todo[:MAX_TRANSLATIONS]:
        t = translate(b)
        if t is None:
            break  # LLM busy or out of quota: the rest waits for the next run
        if not t["relevant"]:
            skipped.add(b["link"])
            print(f"News page: not relevant for job seekers: {b['title_de']}")
            continue
        items[b["link"]] = {"title": t["title"], "summary": t["summary"], "source": BA_SOURCE, "link": b["link"],
                            "date": b["date"].isoformat(), "topic": "ba", "image": None, "title_de": b["title_de"],
                            "translated": True}
        done += 1
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print what would be added, don't write content/news.json")
    args = ap.parse_args()
    store = load()
    items = {it["link"]: it for it in store["items"]}
    skipped = set(store.get("skipped", []))
    added = translated = 0
    try:
        added = collect_feeds(items)
    except Exception as err:  # noqa: BLE001  (never fail the deploy over news)
        print(f"News page: English feeds failed ({err})")
    try:
        translated = collect_ba(items, skipped)
    except Exception as err:  # noqa: BLE001
        print(f"News page: Bundesagentur für Arbeit failed ({err})")

    keep = sorted((it for it in items.values() if news_post._date(it["date"]) > NOW - dt.timedelta(days=MAX_AGE_DAYS)),
                  key=lambda it: it["date"], reverse=True)[:MAX_ITEMS]
    print(f"News page: {added} new English stories, {translated} BA items translated, {len(keep)} stories kept")
    if args.dry_run:
        for it in keep[:60]:
            print(f"- {it['date'][:10]} [{it['topic']:7}] {'📷' if it.get('image') else '  '} [{it['source']}] {it['title'][:90]}")
        return
    STORE.write_text(json.dumps({"items": keep, "skipped": sorted(skipped)}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
