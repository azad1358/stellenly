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
def greenhouse(board: str, company: str, region: str | None = None) -> Iterator[dict]:
    host = "boards-api.eu.greenhouse.io" if region == "eu" else "boards-api.greenhouse.io"  # job-boards.eu.greenhouse.io
    r = requests.get(
        f"https://{host}/v1/boards/{board}/jobs",
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


def personio(board: str, company: str, region: str | None = None) -> Iterator[dict]:
    """Personio's public XML feed (<board>.jobs.personio.de, or .com when region == "com")."""
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    base = f"https://{board}.jobs.personio.{'com' if region == 'com' else 'de'}"
    root = ET.fromstring(_get(f"{base}/xml", params={"language": "en"}).content)
    for p in root.findall("position"):
        offices = [p.findtext("office") or ""] + [o.text or "" for o in p.findall("additionalOffices/office")]
        loc = next((o for o in offices if in_germany(o)), None)
        if not loc:
            continue
        parts = [f"<h3>{html.escape(d.findtext('name') or '')}</h3>{d.findtext('value') or ''}"
                 for d in p.findall("jobDescriptions/jobDescription")]
        yield {
            "source": f"personio:{board}",
            "source_id": p.findtext("id"),
            "url": f"{base}/job/{p.findtext('id')}?language=en",
            "title": p.findtext("name"),
            "company": company,
            "location": loc,
            "description_html": "".join(parts),
            "is_remote": "remote" in loc.lower(),
            "tags": [t for t in (p.findtext("department"), p.findtext("recruitingCategory")) if t],
            "job_types": [t for t in (p.findtext("employmentType"), p.findtext("schedule")) if t],
            "posted_at": p.findtext("createdAt"),
        }


def recruitee(board: str, company: str, region: str | None = None) -> Iterator[dict]:
    """Recruitee's public offers API (<board>.recruitee.com, or a custom careers domain passed as region)."""
    base = region if region and region.startswith("https://") else f"https://{board}.recruitee.com"
    for o in _get(f"{base}/api/offers/").json().get("offers", []):
        loc = ", ".join(x for x in (o.get("city"), o.get("country")) if x) or o.get("location") or ""
        if o.get("country_code") != "DE" and not in_germany(loc):
            continue
        published = (o.get("published_at") or o.get("created_at") or "").replace(" UTC", "+00:00").replace(" ", "T", 1)
        yield {
            "source": f"recruitee:{board}",
            "source_id": str(o.get("id")),
            "url": o.get("careers_url"),
            "title": o.get("title"),
            "company": company,
            "location": loc,
            "description_html": (o.get("description") or "") + (o.get("requirements") or ""),
            "is_remote": bool(o.get("remote")),
            "tags": [t for t in (o.get("department"),) if t],
            "job_types": [t for t in (o.get("employment_type_code"),) if t],
            "posted_at": published or None,
        }


def workable(board: str, company: str, region: str | None = None) -> Iterator[dict]:
    """Workable's public job widget API (apply.workable.com/<board>)."""
    data = _get(f"https://apply.workable.com/api/v1/widget/accounts/{board}", params={"details": "true"}).json()
    for j in data.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        if not in_germany(loc):
            continue
        yield {
            "source": f"workable:{board}",
            "source_id": j.get("shortcode"),
            "url": j.get("url") or j.get("application_url"),
            "title": j.get("title"),
            "company": company,
            "location": loc,
            "description_html": j.get("description") or "",
            "is_remote": bool(j.get("telecommuting")),
            "tags": [t for t in (j.get("department"),) if t],
            "job_types": [t for t in (j.get("employment_type"),) if t],
            "posted_at": j.get("published_on") or j.get("created_at"),
        }


def smartrecruiters(board: str, company: str, region: str | None = None, max_jobs: int = 150) -> Iterator[dict]:
    """SmartRecruiters' public postings API. Only English postings in Germany get their (separate) detail call."""
    api = f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
    listed, offset = [], 0
    while offset < 600:
        page = _get(api, params={"country": "de", "limit": 100, "offset": offset}).json()
        listed += page.get("content") or []
        offset += 100
        if offset >= (page.get("totalFound") or 0):
            break
    english = [p for p in listed if ((p.get("language") or {}).get("code") or "en").startswith("en")][:max_jobs]
    for p in english:
        d = _get(p["ref"]).json()
        sections = (d.get("jobAd") or {}).get("sections") or {}
        body = "".join(f"<h3>{html.escape(s.get('title') or '')}</h3>{s.get('text') or ''}" for s in sections.values() if s)
        loc = (d.get("location") or {}).get("fullLocation") or ""
        yield {
            "source": f"smartrecruiters:{board}",
            "source_id": str(d.get("id")),
            "url": d.get("postingUrl") or d.get("applyUrl"),
            "title": d.get("name"),
            "company": company,
            "location": loc,
            "description_html": body,
            "is_remote": bool((d.get("location") or {}).get("remote")),
            "tags": [t for t in ((d.get("department") or {}).get("label"), (d.get("function") or {}).get("label")) if t],
            "job_types": [t for t in ((d.get("typeOfEmployment") or {}).get("label"),) if t],
            "posted_at": d.get("releasedDate"),
        }
        time.sleep(0.2)


ATS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "personio": personio,
       "recruitee": recruitee, "workable": workable, "smartrecruiters": smartrecruiters}


def company_boards(config_path: Path, discovered: list[dict] | None = None) -> Iterator[dict]:
    """companies.json: [{"ats": "greenhouse", "board": "acme", "company": "Acme GmbH"}, ...] plus boards found
    automatically (discover.py). EU-hosted Greenhouse/Lever boards need "region": "eu", Personio .com boards
    "region": "com", Recruitee custom career domains "region": "https://careers.example.com"."""
    entries = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else []
    seen = {(e.get("ats", "").lower(), e.get("board", "").lower()) for e in entries}
    for e in discovered or []:
        if (e["ats"], e["board"].lower()) not in seen:
            seen.add((e["ats"], e["board"].lower()))
            entries.append(e)
    for entry in entries:
        fn = ATS.get(entry.get("ats", "").lower())
        if not fn:
            continue
        try:
            extra = {"region": entry["region"]} if entry.get("region") else {}
            yield from fn(entry["board"], entry.get("company") or entry["board"], **extra)
        except Exception as e:  # one broken board must not stop the run
            print(f"  ! {entry.get('ats')}:{entry.get('board')} failed: {e}")
        time.sleep(0.5)
