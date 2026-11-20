"""News page data (content/news.json): English news for internationals in Germany, plus the news and press releases
of the Bundesagentur für Arbeit, translated to English by the LLM.

Runs in "Deploy website" before build_site.py, which turns content/news.json into news.html and the news line on
the main page. The deploy commits content/news.json, so every story is translated only once and the page keeps its
history (MAX_AGE_DAYS). Never fails the deploy: a source or the LLM that fails is retried on the next run.

  - English feeds: the same feeds and keywords as the Discord / Telegram news (build/news_post.py, data/news_feeds.json)
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
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "ingest"))
import news_post  # noqa: E402  (English feeds, keywords, dedup key)

STORE = ROOT / "content" / "news.json"
BA = "https://www.arbeitsagentur.de"
BA_PAGES = ("/presse", "/news")
BA_SOURCE = "Bundesagentur für Arbeit"
MAX_AGE_DAYS, MAX_ITEMS = 90, 200
MAX_TRANSLATIONS = 8    # per run; the rest waits for the next deploy (free LLM quota is shared with "Job insights")
NOW = news_post.NOW


def load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": [], "skipped": []}


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def ba_list() -> list[dict]:
    """The tiles on the BA press and news pages: {link, title_de, date}. Tiles without a date are hub pages."""
    out, seen = [], set()
    for path in BA_PAGES:
        page = requests.get(BA + path, headers=news_post.UA, timeout=30).text
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
    page = requests.get(url, headers=news_post.UA, timeout=30).text
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print what would be added, don't write content/news.json")
    args = ap.parse_args()
    store = load()
    items = {it["link"]: it for it in store["items"]}
    skipped = set(store.get("skipped", []))

    added = 0
    try:  # English feeds: already English, stored as they come
        for it in news_post.collect():
            if it["link"] not in items and news_post.key(it) not in {news_post.key(x) for x in items.values()}:
                items[it["link"]] = {"title": it["title"], "summary": it["summary"][:600], "source": it["source"],
                                     "link": it["link"], "date": it["date"].isoformat()}
                added += 1
    except Exception as err:  # noqa: BLE001  (never fail the deploy over news)
        print(f"News page: English feeds failed ({err})")

    translated = 0
    try:
        since = NOW - dt.timedelta(days=MAX_AGE_DAYS)
        todo = [b for b in ba_list() if b["link"] not in items and b["link"] not in skipped and b["date"] >= since]
        todo.sort(key=lambda b: b["date"], reverse=True)
        if todo and not os.environ.get("LLM_API_KEY"):
            print(f"News page: {len(todo)} BA items wait for a translation (no LLM_API_KEY)")
            todo = []
        for b in todo[:MAX_TRANSLATIONS]:
            t = translate(b)
            if t is None:
                break  # LLM busy or out of quota: the rest waits for the next run
            if not t["relevant"]:
                skipped.add(b["link"])
                print(f"News page: not relevant for job seekers: {b['title_de']}")
                continue
            items[b["link"]] = {"title": t["title"], "summary": t["summary"], "source": BA_SOURCE, "link": b["link"],
                                "date": b["date"].isoformat(), "title_de": b["title_de"], "translated": True}
            translated += 1
    except Exception as err:  # noqa: BLE001
        print(f"News page: Bundesagentur für Arbeit failed ({err})")

    keep = sorted((it for it in items.values() if news_post._date(it["date"]) > NOW - dt.timedelta(days=MAX_AGE_DAYS)),
                  key=lambda it: it["date"], reverse=True)[:MAX_ITEMS]
    print(f"News page: {added} new English stories, {translated} BA items translated, {len(keep)} stories kept")
    if args.dry_run:
        for it in keep[:15]:
            print(f"- {it['date'][:10]} [{it['source']}] {it['title']}\n    {it['summary'][:160]}")
        return
    STORE.write_text(json.dumps({"items": keep, "skipped": sorted(skipped)}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
