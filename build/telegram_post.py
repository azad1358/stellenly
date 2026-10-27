"""Post new English-speaking jobs to the Stellenly Telegram channel.

Runs after each deploy (deploy-pages.yml), so the links to the job pages already work.
Posts one digest of up to MAX_JOBS new jobs (German not required first, then jobs with a
salary). Remembers posted jobs in a small state file kept in the GitHub Actions cache,
so a job is never posted twice. Skips quietly without TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.

    TELEGRAM_BOT_TOKEN=123:abc TELEGRAM_CHAT_ID=@stellenly_jobs python build/telegram_post.py [--dry-run]

Rules, so the channel stays readable:
  - only jobs first seen in the last 24 hours, German not "required", no agencies, not posted before;
  - at most 2 jobs per company in one digest;
  - a digest needs at least MIN_JOBS new jobs, or the last post was more than 20 hours ago;
  - at most one digest every 5 hours.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from html import escape as e
from pathlib import Path

import requests

STATE = Path(os.environ.get("TELEGRAM_STATE", Path(__file__).parent / ".telegram_state.json"))
SITE_URL = os.environ.get("SITE_URL") or "https://www.stellenly.com"
MAX_JOBS, MIN_JOBS = 10, 5
NOW = dt.datetime.now(dt.timezone.utc)
GERMAN = {"not_required": "🇬🇧 No German needed", "nice_to_have": "German a plus", "not_mentioned": ""}


def ts(s: str | None) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def load_new() -> list[dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/jobs"
    key = os.environ["SUPABASE_ANON_KEY"]
    since = (NOW - dt.timedelta(hours=24)).isoformat()
    r = requests.get(url, timeout=60, headers={"apikey": key, "Authorization": f"Bearer {key}"}, params={
        "select": "id,title,company,city,remote_type,german_level,salary_min,salary_max,visa_sponsorship,is_agency,first_seen_at",
        "is_active": "eq.true", "german_level": "neq.required", "first_seen_at": f"gte.{since}",
        "order": "first_seen_at.desc", "limit": 2000})
    r.raise_for_status()
    return r.json()


def k(n: int) -> str:
    return f"€{round(n / 1000)}k"


def line(j: dict) -> str:
    where = "Remote" if j.get("remote_type") in ("remote_de", "remote_eu") else (j.get("city") or "Germany")
    bits = [f"🏢 {e(j['company'])}", f"📍 {e(where)}"]
    if j.get("salary_min"):
        hi = j.get("salary_max")
        bits.append(f"💶 {k(j['salary_min'])}{'–' + k(hi)[1:] if hi and hi != j['salary_min'] else ''}")
    if GERMAN.get(j["german_level"]):
        bits.append(GERMAN[j["german_level"]])
    if j.get("visa_sponsorship"):
        bits.append("🛂 Visa")
    link = f"{SITE_URL}/job/{j['id']}.html?utm_source=telegram"
    return f'<b><a href="{e(link)}">{e(j["title"])}</a></b>\n' + " · ".join(bits)


def message(picked: list[dict], total: int) -> str:
    head = f"🆕 <b>{total} new English-speaking job{'s' if total != 1 else ''} in Germany</b>"
    more = (f"\n\n➕ {total - len(picked)} more" if total > len(picked) else "\n")
    foot = f'{more} · <a href="{SITE_URL}/?utm_source=telegram">Search all jobs on Stellenly →</a>'
    body, text = [], ""
    for j in picked:  # Telegram allows 4096 characters per message
        candidate = "\n\n".join(body + [line(j)])
        if len(head) + len(candidate) + len(foot) + 10 > 4000:
            break
        body.append(line(j))
        text = candidate
    return f"{head}\n\n{text}{foot}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the message instead of sending it")
    args = ap.parse_args()
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat) and not args.dry_run:
        print("Telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set, skipping")
        return

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"posted": {}, "last": None}
    posted = {i: t for i, t in state["posted"].items() if ts(t) > NOW - dt.timedelta(days=7)}  # keep it small
    last = ts(state.get("last"))
    if NOW - last < dt.timedelta(hours=5) and not args.dry_run:
        print(f"Telegram: last digest {last:%H:%M} UTC, less than 5 hours ago, skipping")
        return

    fresh = [j for j in load_new() if j["id"] not in posted and not j.get("is_agency")]
    if not fresh or (len(fresh) < MIN_JOBS and NOW - last < dt.timedelta(hours=20)):
        print(f"Telegram: {len(fresh)} new jobs, waiting for more")
        return
    fresh.sort(key=lambda j: (j["german_level"] != "not_required", not j.get("salary_min"), not j.get("visa_sponsorship")))
    picked, per_company = [], {}
    for j in fresh:
        n = per_company.get(j["company"], 0)
        if n < 2:
            picked.append(j)
            per_company[j["company"]] = n + 1
        if len(picked) == MAX_JOBS:
            break
    text = message(picked, len(fresh))
    if args.dry_run:
        print(text)
        return

    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, json={
        "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    if not r.ok:
        raise SystemExit(f"Telegram: sending failed: {r.status_code} {r.text[:300]}")
    for j in fresh:  # all of them count as posted: the digest links to the rest
        posted[j["id"]] = NOW.isoformat()
    STATE.write_text(json.dumps({"posted": posted, "last": NOW.isoformat()}), encoding="utf-8")
    print(f"Telegram: posted a digest of {len(fresh)} jobs")


if __name__ == "__main__":
    main()
