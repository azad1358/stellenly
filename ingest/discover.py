"""Find employers' own job boards from Arbeitnow postings, so we can read them directly.

Every Arbeitnow job has an /apply link that redirects to the employer's applicant tracking
system (Ashby, Greenhouse, Lever, Personio, Recruitee, Workable, SmartRecruiters ...).
We follow that redirect once per company, recognise the system and the board name, check
that the board's public API answers, and remember it in data/cache/discovered_boards.json. From then
on the ingester reads that company directly — so we depend less on Arbeitnow every day.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

PATH = Path(__file__).parent.parent / "data" / "cache" / "discovered_boards.json"
UA = {"User-Agent": "stellenly/1.0 (+https://github.com/azad1358/stellenly)"}
RECHECK_DAYS = 30  # companies without a recognised board are tried again after this

# host pattern -> (ats, how to read the board name, region)
_RULES = [
    (r"^jobs\.ashbyhq\.com$", "ashby", "path", None),
    (r"^(job-)?boards\.greenhouse\.io$", "greenhouse", "path", None),
    (r"^(job-)?boards\.eu\.greenhouse\.io$", "greenhouse", "path", "eu"),
    (r"^jobs\.lever\.co$", "lever", "path", None),
    (r"^jobs\.eu\.lever\.co$", "lever", "path", "eu"),
    (r"^([\w-]+)\.jobs\.personio\.de$", "personio", "sub", None),
    (r"^([\w-]+)\.jobs\.personio\.com$", "personio", "sub", "com"),
    (r"^([\w-]+)\.recruitee\.com$", "recruitee", "sub", None),
    (r"^apply\.workable\.com$", "workable", "path", None),
    (r"^(careers|jobs)\.smartrecruiters\.com$|^jobs\.smartrecruiters\.com$", "smartrecruiters", "path", None),
]


def parse_board(url: str) -> dict | None:
    """'https://jobs.ashbyhq.com/n8n/0123/application' -> {"ats": "ashby", "board": "n8n"}."""
    u = urlparse(url or "")
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    for pat, ats, kind, region in _RULES:
        m = re.match(pat, host)
        if not m:
            continue
        if kind == "sub":
            board = m.group(1)
        else:
            board = parts[0] if parts else ""
            if ats == "workable" and board == "j":
                return None  # apply.workable.com/j/<code> doesn't name the account
        if not board or not re.fullmatch(r"[\w.-]{2,80}", board):
            return None
        out = {"ats": ats, "board": board}
        if region:
            out["region"] = region
        return out
    # Recruitee also runs on custom career domains: https://careers.example.com/o/<job-slug>
    if len(parts) >= 2 and parts[0] == "o":
        return {"ats": "recruitee", "board": host.split(".")[-2] if host.count(".") else host,
                "region": f"https://{host}"}
    return None


def _api_ok(entry: dict) -> bool:
    """Does the board's public API answer? (cheap check before we start reading it every run)"""
    b, r = entry["board"], entry.get("region")
    url = {
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{b}",
        "greenhouse": f"https://boards-api{'.eu' if r == 'eu' else ''}.greenhouse.io/v1/boards/{b}/jobs",
        "lever": f"https://api{'.eu' if r == 'eu' else ''}.lever.co/v0/postings/{b}?mode=json",
        "personio": f"https://{b}.jobs.personio.{'com' if r == 'com' else 'de'}/xml",
        "recruitee": f"{r if r and r.startswith('https://') else f'https://{b}.recruitee.com'}/api/offers/",
        "workable": f"https://apply.workable.com/api/v1/widget/accounts/{b}",
        "smartrecruiters": f"https://api.smartrecruiters.com/v1/companies/{b}/postings?limit=1",
    }[entry["ats"]]
    try:
        return requests.get(url, headers=UA, timeout=20).status_code == 200
    except requests.RequestException:
        return False


def _company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def load() -> dict:
    data = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}
    data.setdefault("boards", {})
    data.setdefault("none", {})
    return data


def save(data: dict) -> None:
    out = {"boards": dict(sorted(data["boards"].items())), "none": dict(sorted(data["none"].items()))}
    PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def boards(data: dict | None = None) -> list[dict]:
    """Discovered boards in the format company_boards() takes."""
    return list((data or load())["boards"].values())


def update(jobs: list[dict], known: set[tuple[str, str]], max_new: int = 120, pause: float = 0.8) -> int:
    """jobs = Arbeitnow raw jobs (company + /apply url). Resolves one job per unknown company.
    known = {(ats, board)} already listed in data/career_boards.json. Returns the number of boards added."""
    data = load()
    today = dt.date.today()
    first_url: dict[str, tuple[str, str]] = {}
    for j in jobs:
        key = _company_key(j.get("company"))
        if key and j.get("url") and key not in first_url:
            first_url[key] = (j["company"], j["url"])
    todo = []
    for key, (company, url) in first_url.items():
        if key in data["boards"]:
            continue
        checked = data["none"].get(key)
        if checked and (today - dt.date.fromisoformat(checked)).days < RECHECK_DAYS:
            continue
        todo.append((key, company, url))
    added = 0
    for key, company, url in todo[:max_new]:
        try:
            r = requests.get(url, headers=UA, timeout=20, allow_redirects=False)
            target = r.headers.get("Location", "")
        except requests.RequestException:
            continue  # try again next run
        if r.status_code == 429:
            break  # Arbeitnow asks us to slow down: continue next run
        entry = parse_board(target)
        if not entry and target.startswith("http"):
            # Short links (grnh.se/…) and tracking redirects: follow the chain once to the real board.
            try:
                target = requests.get(target, headers=UA, timeout=20, allow_redirects=True, stream=True).url
                entry = parse_board(target)
            except requests.RequestException:
                pass
        if entry and (entry["ats"], entry["board"].lower()) not in {(a, b.lower()) for a, b in known} and _api_ok(entry):
            data["boards"][key] = {**entry, "company": company}
            data["none"].pop(key, None)
            added += 1
        else:
            data["none"][key] = today.isoformat()
        time.sleep(pause)
    save(data)
    return added
