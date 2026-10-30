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
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from enrich import abroad, enrich, generic_location, in_germany  # noqa: E402
import discover  # noqa: E402
import geo  # noqa: E402
import sources  # noqa: E402

BATCH = 100


def upsert(rows: list[dict]) -> int:
    """ingest_jobs() for a batch; on a statement timeout (busy database) retry it in two halves."""
    try:
        return int(rpc("ingest_jobs", {"payload": rows}).text or 0)
    except RuntimeError as err:
        if "57014" not in str(err) or len(rows) == 1:
            raise
        print(f"  timeout on {len(rows)} rows, retrying in halves")
        return upsert(rows[:len(rows) // 2]) + upsert(rows[len(rows) // 2:])


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


def located_in_germany(raw: dict) -> bool | None:
    """Arbeitnow lists jobs from all over Europe. None = not geocoded yet (next run)."""
    loc = (raw.get("location") or "").strip()
    if in_germany(loc):
        return True
    if abroad(loc):
        return False
    if generic_location(loc):  # "Remote", "EMEA", "Remote - Europe timezone": open to people in Germany
        return bool(raw.get("is_remote"))
    hit = geo.lookup(loc)
    if hit is False:
        return None
    if hit is None:  # unplaceable: keep only remote roles
        return bool(raw.get("is_remote"))
    return hit["cc"] == "de"


def collect(max_pages: int) -> tuple[list[dict], list[str], collections.Counter]:
    """Returns (German jobs, ids of jobs found to be outside Germany, jobs found per source)."""
    rows: dict[str, dict] = {}
    foreign: list[str] = []
    stats = collections.Counter()
    per_source = collections.Counter()
    arbeitnow_raws: list[dict] = []

    def take(label: str, raw: dict) -> None:
        stats["seen"] += 1
        per_source[label] += 1
        row = enrich(raw)
        if row is None:
            stats["skipped (not English / incomplete)"] += 1
            return
        if raw["source"] == "arbeitnow":
            german = located_in_germany(raw)
            if german is None:
                stats["skipped (location not geocoded yet)"] += 1
                return
            if not german:
                stats["skipped (outside Germany)"] += 1
                foreign.append(row["id"])
                return
            arbeitnow_raws.append(raw)
        old = rows.get(row["id"])
        if old:
            stats["duplicates merged"] += 1
            if not (old["source"] == "arbeitnow" and raw["source"] != "arbeitnow"):
                return  # keep the first — but the employer's own board beats Arbeitnow's copy
        rows[row["id"]] = row
        stats[f"german: {row['german_level']}"] += 1
        if row["salary_min"]:
            stats["with salary"] += 1

    try:
        for raw in sources.arbeitnow(max_pages=max_pages):
            take("arbeitnow", raw)
    except Exception as e:
        print(f"! source 'arbeitnow' failed: {e}")

    # Learn employers' own boards from Arbeitnow's apply links, then read every board directly.
    config = Path(__file__).parent.parent / "data" / "career_boards.json"
    known = {(e["ats"], e["board"]) for e in json.loads(config.read_text(encoding="utf-8"))}
    try:
        added = discover.update(arbeitnow_raws, known, max_new=int(os.environ.get("DISCOVER_MAX", 120)))
        print(f"Discovered {added} new company boards ({len(discover.boards())} in total)")
    except Exception as e:  # discovery must never stop the import
        print(f"! board discovery failed: {e}")
    try:
        for raw in sources.company_boards(config, discover.boards()):
            take("company boards", raw)
    except Exception as e:
        print(f"! source 'company boards' failed: {e}")

    # Coordinates for the companies map (build_site.py reads them from the cache).
    for city in sorted({r["city"] for r in rows.values() if r.get("city") and r["city"] != "Remote"}):
        geo.lookup(city, "de")
    geo.save()
    sources_of_rows = collections.Counter(r["source"].split(":")[0] for r in rows.values())
    print("Stats:", dict(stats))
    print("Jobs kept per source:", dict(sources_of_rows.most_common()))
    return list(rows.values()), foreign, per_source


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", 40)))
    args = ap.parse_args()

    run_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    rows, foreign, per_source = collect(args.max_pages)
    print(f"{len(rows)} English jobs ready, {len(foreign)} outside Germany")
    # A source that returns nothing at all is broken (API down, format changed): fail the run so GitHub emails us.
    dead = [s for s in ("arbeitnow", "company boards") if not per_source[s]]
    if args.dry_run:
        for r in rows[:5]:
            print(json.dumps({k: r[k] for k in r if k != "description"}, ensure_ascii=False, default=str))
        return

    written = 0
    for i in range(0, len(rows), BATCH):
        written += upsert(rows[i:i + BATCH])
    for i in range(0, len(foreign), 1000):  # hide ones stored before the country check existed
        rpc("mark_checked", {"alive_ids": [], "dead_ids": foreign[i:i + 1000]})
    expired = rpc("expire_jobs", {"max_age_days": 45}).text
    print(f"Upserted {written} rows, expired {expired} old jobs")
    # Jobs that visitors reported as gone from the company's site (report_job on the website).
    threshold = int(os.environ.get("REPORT_THRESHOLD") or 3)
    reported = rpc("deactivate_reported", {"p_threshold": threshold}).text
    print(f"Hid {reported} jobs reported closed by {threshold}+ visitors")

    # Hide jobs that are gone from their source — only for sources read completely in this run.
    # Arbeitnow and the company boards are checked separately, each with the safety limit.
    share = float(os.environ.get("DEACTIVATE_MAX_SHARE") or 0.6)
    groups = [["arbeitnow"] if "arbeitnow" in sources.COMPLETE else [],
              sorted(s for s in sources.COMPLETE if s != "arbeitnow")]
    for group in (g for g in groups if g):
        n = int(rpc("deactivate_unseen", {"p_sources": group, "p_before": run_start.isoformat(),
                                          "p_max_share": share}).text or 0)
        label = "Arbeitnow" if group == ["arbeitnow"] else f"{len(group)} company boards"
        if n < 0:
            print(f"! {label}: too many jobs would disappear at once (> {share:.0%}); nothing hidden — check the source")
        else:
            print(f"{label}: hid {n} jobs that are no longer listed")
    if dead:
        sys.exit(f"ALERT: no jobs at all from {', '.join(dead)} — check the source (the other sources were saved)")


if __name__ == "__main__":
    main()
