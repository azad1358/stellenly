"""Tell Google about new and closed job pages with the Indexing API (made for JobPosting pages).

A notified URL is usually crawled within hours instead of days; our jobs stay open ~5 days on average.
Runs after the deploy (deploy-website.yml). The service account in GOOGLE_INDEXING_KEY is a verified owner of
stellenly.com (Site Verification API, DNS TXT record), which the Indexing API requires.

    python build/google_indexing.py            # needs GOOGLE_INDEXING_KEY + SUPABASE_URL + SUPABASE_ANON_KEY
    python build/google_indexing.py --dry-run  # only print what it would send

Newest jobs first, then closed jobs (URL_DELETED). The job URLs Google was told about and today's request
count are kept in build/.google_indexing_state.json (Actions cache).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from build_site import SITE_URL  # noqa: E402
from job_pages import load_light  # noqa: E402

STATE = Path(__file__).parent / ".google_indexing_state.json"
DAILY_LIMIT = 200  # Google's default quota; it resets at midnight Pacific time
PER_RUN = 50       # ~4 deploys a day: leave room for the jobs that arrive later in the day
API = "https://indexing.googleapis.com/v3/urlNotifications:publish"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not os.environ.get("GOOGLE_INDEXING_KEY"):
        print("GOOGLE_INDEXING_KEY not set: skipped")
        return

    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"sent": [], "day": "", "count": 0}
    today = dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    if state["day"] != today:
        state.update(day=today, count=0)
    sent = set(state["sent"])

    active = {j["id"]: j for j in load_light("id,first_seen_at,source")
              if j.get("source") != "amazon"}  # title-only pages are noindex
    new = sorted((i for i in active if i not in sent), key=lambda i: active[i].get("first_seen_at") or "", reverse=True)
    gone = [i for i in sent if i not in active]
    todo = [(i, "URL_UPDATED") for i in new] + [(i, "URL_DELETED") for i in gone]
    room = max(0, min(PER_RUN, DAILY_LIMIT - state["count"]))
    print(f"Google Indexing API: {len(new)} new, {len(gone)} closed, sending {min(room, len(todo))} "
          f"({state['count']}/{DAILY_LIMIT} used today)")
    if args.dry_run:
        for i, kind in todo[:room]:
            print(f"  {kind} {SITE_URL}/job/{i}.html")
        return

    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_INDEXING_KEY"]), scopes=["https://www.googleapis.com/auth/indexing"])
    session = AuthorizedSession(creds)
    ok = 0
    for i, kind in todo[:room]:
        r = session.post(API, json={"url": f"{SITE_URL}/job/{i}.html", "type": kind}, timeout=30)
        state["count"] += 1
        if r.status_code == 429:
            print("! Daily quota used up")
            break
        if not r.ok:
            print(f"! {kind} {i}: HTTP {r.status_code} {r.text[:200]}")
            continue
        ok += 1
        (sent.add if kind == "URL_UPDATED" else sent.discard)(i)
    state["sent"] = sorted(sent)
    STATE.write_text(json.dumps(state), encoding="utf-8")
    print(f"Google Indexing API: {ok} sent")


if __name__ == "__main__":
    main()
