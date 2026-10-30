"""Coats of arms of German states and cities for the location pages (jobs/state-*.html, jobs/city-*.html).

Wikidata names each place's coat of arms (property P94); the image comes from Wikimedia Commons as a small PNG
in web/img/coa/<slug>.png. A city is matched by its name AND by being within 25 km of our coordinates, so a
village with the same name elsewhere is never used. Every answer (also "none found") is remembered in
data/cache/coats_of_arms.json, so each place is asked only once; build_site.py only reads that file.

    python build/coats_of_arms.py            # look up the states and the cities with a page that are missing
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "coats_of_arms.json"
OUT = ROOT / "web" / "img" / "coa"
UA = {"User-Agent": "stellenly/1.0 (+https://www.stellenly.com; info@stellenly.com)"}
API = "https://www.wikidata.org/w/api.php"


def load() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def image(key: str) -> str | None:
    """Path of the coat of arms below web/ ("img/coa/bavaria.png"), or None (never calls the network)."""
    return (load().get(key) or {}).get("img")


def _get(params: dict) -> dict:
    for attempt in range(4):
        time.sleep(0.5 + 5 * attempt)  # polite: Wikidata asks bots to go slowly, and to wait when it is busy
        r = requests.get(API, params={**params, "format": "json"}, headers=UA, timeout=30)
        r.raise_for_status()
        if "error" not in r.json():
            return r.json()
    raise requests.RequestException(f"Wikidata keeps answering {r.json()['error'].get('code')}")


def _download(file: str, slug: str) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    time.sleep(0.5)
    r = requests.get(f"https://commons.wikimedia.org/wiki/Special:FilePath/{requests.utils.quote(file)}",
                     params={"width": 96}, headers=UA, timeout=30)
    r.raise_for_status()
    (OUT / f"{slug}.png").write_bytes(r.content)
    return f"img/coa/{slug}.png"


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dy, dx = (a[0] - b[0]) * 111, (a[1] - b[1]) * 111 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def _state_file(code: str) -> str | None:
    q = f'SELECT ?f WHERE {{ ?s wdt:P300 "{code}"; wdt:P94 ?f }} LIMIT 1'
    time.sleep(0.5)
    r = requests.get("https://query.wikidata.org/sparql", params={"query": q, "format": "json"}, headers=UA, timeout=60)
    r.raise_for_status()
    rows = r.json()["results"]["bindings"]
    return requests.utils.unquote(rows[0]["f"]["value"].rsplit("/", 1)[-1]) if rows else None


def _city_file(name: str, near: tuple[float, float]) -> str | None:
    hits = _get({"action": "wbsearchentities", "search": name, "language": "en", "type": "item", "limit": 7})["search"]
    if not hits:
        return None
    ents = _get({"action": "wbgetentities", "ids": "|".join(h["id"] for h in hits), "props": "claims"})["entities"]
    for h in hits:  # search order: the best name match first
        claims = ents.get(h["id"], {}).get("claims", {})
        coa = claims.get("P94") or []
        coord = (((claims.get("P625") or [{}])[0].get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if coa and coord and _km((coord["latitude"], coord["longitude"]), near) < 25:
            return coa[0]["mainsnak"]["datavalue"]["value"]
    return None


def update(states: dict[str, str], cities: dict[str, tuple[float, float]], slugify) -> int:
    """states: {"DE-BY": "Bavaria"}, cities: {"Munich": (lat, lon)}. Looks up the ones not cached yet."""
    cache, found = load(), 0
    todo = [("state", code, name) for code, name in states.items() if f"state:{code}" not in cache]
    todo += [("city", name, xy) for name, xy in cities.items() if f"city:{name}" not in cache]
    for kind, key, extra in todo:
        try:
            file = _state_file(key) if kind == "state" else _city_file(key, extra)
            slug = slugify(extra if kind == "state" else key)
            cache[f"{kind}:{key}"] = {"file": file, "img": _download(file, f"{kind}-{slug}") if file else None}
            found += bool(file)
        except requests.RequestException as err:  # not cached: try again next time
            print(f"  ! coat of arms for {key} failed: {err}")
            continue
        CACHE.write_text(json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return found


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "ingest"))
    sys.path.insert(0, str(ROOT / "build"))
    import build_site as b  # noqa: E402
    import geo  # noqa: E402
    jobs = b.load_jobs(None)
    counts: dict[str, int] = {}
    for j in jobs:
        if j.get("city") and j["city"] != "Remote" and b.normalize_city(j["city"]) == j["city"]:
            counts[j["city"]] = counts.get(j["city"], 0) + 1
    cities = {c: xy for c, n in counts.items() if n >= b.MIN_JOBS and (xy := geo.city_coords(c))}
    print(f"Coats of arms: {update(b.STATES, cities, b.slugify)} new found")
