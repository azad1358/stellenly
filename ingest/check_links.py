"""Dead-link checker: re-opens the original posting of the least recently
checked active jobs and hides the ones that are gone (404/410, or redirected
to a generic careers / home page).

    python ingest/check_links.py --limit 600
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).parent))
from ingest import rpc  # noqa: E402

UA = {"User-Agent": "jobs-in-germany-english/1.0 link-checker"}
GENERIC_PATHS = {"", "/", "/jobs", "/careers", "/career", "/karriere", "/en/careers", "/de/karriere"}
CLOSED_WORDS = ("no longer available", "position has been filled", "job is closed",
                "no longer accepting", "nicht mehr verfügbar", "stelle ist bereits besetzt")


def fetch_batch(limit: int) -> list[dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/jobs"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    r = requests.get(
        url,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        params={"select": "id,url", "is_active": "eq.true",
                "order": "last_checked_at.asc.nullsfirst", "limit": str(limit)},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def is_dead(url: str) -> bool | None:
    """True = gone, False = alive, None = unknown (network error → try later)."""
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True, stream=True)
        if r.status_code in (404, 410):
            return True
        if r.status_code >= 400:
            return None  # 403/429/5xx: don't punish the job for bot protection
        if urlparse(r.url).path.rstrip("/").lower() in GENERIC_PATHS and \
                urlparse(url).path.rstrip("/").lower() not in GENERIC_PATHS:
            return True
        head = next(r.iter_content(65536), b"").decode("utf-8", "ignore").lower()
        return any(w in head for w in CLOSED_WORDS)
    except requests.RequestException:
        return None
    finally:
        time.sleep(0.2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=600)
    args = ap.parse_args()

    jobs = fetch_batch(args.limit)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda j: is_dead(j["url"]), jobs))
    alive = [j["id"] for j, d in zip(jobs, results) if d is False]
    dead = [j["id"] for j, d in zip(jobs, results) if d is True]
    rpc("mark_checked", {"alive_ids": alive, "dead_ids": dead})
    print(f"Checked {len(jobs)}: {len(alive)} alive, {len(dead)} dead, "
          f"{len(jobs) - len(alive) - len(dead)} unknown")


if __name__ == "__main__":
    main()
