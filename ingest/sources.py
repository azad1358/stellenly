"""Job sources. Each source yields raw dicts in a common shape:

    source, source_id, url, title, company, location, description_html,
    is_remote, tags, job_types, posted_at (ISO 8601 string)

Add a new source by writing one generator function and registering it in
ingest.py. Only free, public APIs are used — no scraping of sites that forbid it.
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import requests

from enrich import in_germany

UA = {"User-Agent": "stellenly/1.0 (+https://github.com/azad1358/stellenly)"}
TIMEOUT = 30


def _get(url: str, retries: int = 4, **kwargs) -> requests.Response:
    """GET that waits and retries when rate-limited (429) or on a 5xx."""
    for attempt in range(retries + 1):
        r = requests.get(url, headers=UA, timeout=TIMEOUT, **kwargs)
        if r.status_code != 429 and r.status_code < 500 or attempt == retries:
            r.raise_for_status()
            return r
        retry_after = r.headers.get("Retry-After", "")
        wait = int(retry_after) if retry_after.isdigit() else 15 * 2 ** attempt
        print(f"  {r.status_code} from {url}, retrying in {min(wait, 120)}s")
        time.sleep(min(wait, 120))


def _iso_from_unix(ts: float | int | None) -> str | None:
    if not ts:
        return None
    if ts > 10_000_000_000:  # milliseconds
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Arbeitnow — free public API, no key. Docs: https://www.arbeitnow.com/api/job-board-api
# ---------------------------------------------------------------------------
def arbeitnow(max_pages: int = 40, pause: float = 2.0) -> Iterator[dict]:
    url = "https://www.arbeitnow.com/api/job-board-api"
    page = 0
    while url and page < max_pages:
        payload = _get(url).json()
        for j in payload.get("data", []):
            yield {
                "source": "arbeitnow",
                "source_id": j.get("slug"),
                # <job page>/apply redirects to the employer's own application page
                "url": j["url"].rstrip("/") + "/apply" if j.get("url") else None,
                "title": j.get("title"),
                "company": j.get("company_name"),
                "location": j.get("location"),
                "description_html": j.get("description"),
                "is_remote": bool(j.get("remote")),
                "tags": j.get("tags") or [],
                "job_types": j.get("job_types") or [],
                "posted_at": _iso_from_unix(j.get("created_at")),
            }
        url = (payload.get("links") or {}).get("next")
        page += 1
        time.sleep(pause)  # be polite


# ---------------------------------------------------------------------------
# Company career pages via public ATS APIs (Greenhouse / Lever / Ashby).
# List the company board names in companies.json. Many Berlin startups post
# in English here, so this is the highest-quality source you can add.
# ---------------------------------------------------------------------------
def greenhouse(board: str, company: str) -> Iterator[dict]:
    r = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
        params={"content": "true"}, headers=UA, timeout=TIMEOUT,
    )
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name")
        if not in_germany(loc):
            continue
        yield {
            "source": f"greenhouse:{board}",
            "source_id": j.get("id"),
            "url": j.get("absolute_url"),
            "title": j.get("title"),
            "company": company,
            "location": loc,
            "description_html": html.unescape(j.get("content") or ""),  # content is HTML-escaped
            "is_remote": "remote" in (loc or "").lower(),
            "tags": [d.get("name") for d in j.get("departments", []) if d.get("name")],
            "job_types": [],
            "posted_at": j.get("first_published") or j.get("updated_at"),
        }


def lever(board: str, company: str, region: str | None = None) -> Iterator[dict]:
    host = "api.eu.lever.co" if region == "eu" else "api.lever.co"  # jobs.eu.lever.co boards
    r = requests.get(
        f"https://{host}/v0/postings/{board}", params={"mode": "json"},
        headers=UA, timeout=TIMEOUT,
    )
    r.raise_for_status()
    for j in r.json():
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        if not in_germany(loc):
            continue
        lists = "".join(
            f"<h3>{l.get('text', '')}</h3><ul>{l.get('content', '')}</ul>" for l in j.get("lists") or []
        )
        yield {
            "source": f"lever:{board}",
            "source_id": j.get("id"),
            "url": j.get("hostedUrl"),
            "title": j.get("text"),
            "company": company,
            "location": loc,
            "description_html": (j.get("description") or "") + lists + (j.get("additional") or ""),
            "is_remote": (j.get("workplaceType") or "") == "remote",
            "tags": [t for t in (cats.get("team"), cats.get("department")) if t],
            "job_types": [cats["commitment"]] if cats.get("commitment") else [],
            "posted_at": _iso_from_unix(j.get("createdAt")),
        }


def ashby(board: str, company: str) -> Iterator[dict]:
    r = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{board}",
        params={"includeCompensation": "true"}, headers=UA, timeout=TIMEOUT,
    )
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        locs = [j.get("location") or ""] + [
            (s.get("location") or "") for s in j.get("secondaryLocations") or []
        ]
        loc = next((l for l in locs if in_germany(l)), None)
        if not loc:
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        yield {
            "source": f"ashby:{board}",
            "source_id": j.get("id"),
            "url": j.get("jobUrl"),
            "title": j.get("title"),
            "company": company,
            "location": loc,
            "description_html": (j.get("descriptionHtml") or "") + (f"<p>Salary: {comp}</p>" if comp else ""),
            "is_remote": bool(j.get("isRemote")),
            "tags": [t for t in (j.get("department"), j.get("team")) if t],
            "job_types": [j["employmentType"]] if j.get("employmentType") else [],
            "posted_at": j.get("publishedAt"),
        }


ATS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


def company_boards(config_path: Path) -> Iterator[dict]:
    """companies.json: [{"ats": "greenhouse", "board": "acme", "company": "Acme GmbH"}, ...]
    Lever boards hosted on jobs.eu.lever.co also need "region": "eu"."""
    if not config_path.exists():
        return
    for entry in json.loads(config_path.read_text(encoding="utf-8")):
        fn = ATS.get(entry.get("ats", "").lower())
        if not fn:
            continue
        try:
            extra = {"region": entry["region"]} if entry.get("region") else {}
            yield from fn(entry["board"], entry.get("company") or entry["board"], **extra)
        except Exception as e:  # one broken board must not stop the run
            print(f"  ! {entry.get('ats')}:{entry.get('board')} failed: {e}")
        time.sleep(0.5)
