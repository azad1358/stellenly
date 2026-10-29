"""Geocoding with a committed cache (data/cache/geocache.json).

Used to (1) tell whether a job board location like "Geeste" or "Bristol" is in
Germany and (2) give the companies map coordinates for each city.
Lookups go to OpenStreetMap Nominatim at most once per second, and every
answer (including "not found") is cached, so each place is asked only once.
Policy: https://operations.osmfoundation.org/policies/nominatim/
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "geocache.json"
UA = {"User-Agent": "stellenly/1.0 (+https://github.com/azad1358/stellenly)"}

_cache: dict[str, dict | None] | None = None
_last_call = 0.0
lookups_left = int(os.environ.get("GEO_LOOKUPS", 600))  # per run; the rest waits for the next run


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    return _cache


def save() -> None:
    if _cache is not None:
        CACHE_PATH.write_text(json.dumps(dict(sorted(_cache.items())), ensure_ascii=False, indent=0) + "\n",
                              encoding="utf-8")


def _key(query: str, country: str | None) -> str:
    return f"{country or '*'}|{' '.join(query.lower().split())}"


def lookup(query: str, country: str | None = None) -> dict | None | bool:
    """{"cc": "de", "lat": .., "lon": ..} · None if the place is unknown ·
    False if it isn't cached and this run's lookup budget is used up."""
    global _last_call, lookups_left
    cache = _load()
    key = _key(query, country)
    if key in cache:
        return cache[key]
    if lookups_left <= 0:
        return False
    lookups_left -= 1
    time.sleep(max(0.0, 1.1 - (time.monotonic() - _last_call)))
    params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1, "accept-language": "en"}
    if country:
        params["countrycodes"] = country
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=UA, timeout=20)
        r.raise_for_status()
        hits = r.json()
    except Exception as e:
        print(f"  ! geocode '{query}' failed: {e}")
        return False  # not cached: try again next run
    finally:
        _last_call = time.monotonic()
    cache[key] = ({"cc": (hits[0].get("address") or {}).get("country_code"),
                   "lat": round(float(hits[0]["lat"]), 4), "lon": round(float(hits[0]["lon"]), 4)}
                  if hits else None)
    return cache[key]


def cached_country(query: str) -> str | None:
    """Country code from the cache only (never calls the network)."""
    hit = _load().get(_key(query, None))
    return hit["cc"] if hit else None


def city_coords(city: str) -> tuple[float, float] | None:
    """Cached coordinates of a German city (never calls the network)."""
    hit = _load().get(_key(city, "de"))
    return (hit["lat"], hit["lon"]) if hit else None
