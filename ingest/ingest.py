"""Fetch jobs from all sources, enrich them, and upsert into Supabase.

Run locally:
    export SUPABASE_URL=https://xxxx.supabase.co
    export SUPABASE_SERVICE_ROLE_KEY=...      # secret! never put it in the frontend
    python ingest/ingest.py

Options:
    --dry-run          enrich and print stats, don't write to Supabase
    --max-pages N      how many Arbeitnow pages to read (default 40, ~100 jobs/page)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from enrich import enrich  # noqa: E402
import sources  # noqa: E402

BATCH = 200


def rpc(name: str, body: dict) -> requests.Response:
    url = os.environ["SUPABASE_URL"].rstrip("/") + f"/rest/v1/rpc/{name}"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    r = requests.post(
        url,
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        data=json.dumps(body, default=str),
        timeout=120,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"{name} failed: {r.status_code} {r.text[:500]}")
    return r


def collect(max_pages: int) -> list[dict]:
    raw_iters = [
        ("arbeitnow", sources.arbeitnow(max_pages=max_pages)),
        ("company boards", sources.company_boards(Path(__file__).parent / "companies.json")),
    ]
    rows: dict[str, dict] = {}
    stats = collections.Counter()
    for label, it in raw_iters:
        try:
            for raw in it:
                stats["seen"] += 1
                row = enrich(raw)
                if row is None:
                    stats["skipped (not English / incomplete)"] += 1
                    continue
                if row["id"] in rows:
                    stats["duplicates merged"] += 1
                    continue
                rows[row["id"]] = row
                stats[f"german: {row['german_level']}"] += 1
                if row["salary_min"]:
                    stats["with salary"] += 1
        except Exception as e:
            print(f"! source '{label}' failed: {e}")
    print("Stats:", dict(stats))
    return list(rows.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", 40)))
    args = ap.parse_args()

    rows = collect(args.max_pages)
    print(f"{len(rows)} English jobs ready")
    if args.dry_run:
        for r in rows[:5]:
            print(json.dumps({k: r[k] for k in r if k != "description"}, ensure_ascii=False, default=str))
        return

    written = 0
    for i in range(0, len(rows), BATCH):
        r = rpc("ingest_jobs", {"payload": rows[i:i + BATCH]})
        written += int(r.text or 0)
    expired = rpc("expire_jobs", {"max_age_days": 45}).text
    print(f"Upserted {written} rows, expired {expired} old jobs")


if __name__ == "__main__":
    main()
