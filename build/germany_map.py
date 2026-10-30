"""Inline SVG map of Germany's 16 states for the location pages (jobs/state-*.html, jobs/city-*.html).

Outlines: data/germany_states.geo.json (github.com/isellsoap/deutschlandGeoJSON, low resolution, Unlicense; from
diva-gis.org), keyed by ISO code ("DE-BY"). The page's state is highlighted, every state links to its page, and
our cities are dots sized by their open jobs. No map tiles, nothing loaded from other sites.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

_GEO = json.loads((Path(__file__).resolve().parent.parent / "data" / "germany_states.geo.json").read_text(encoding="utf-8"))
_LAT0, _SCALE = 51.2, 60  # equirectangular around Germany's middle: x shrinks by cos(latitude)


def _rings(geom: dict) -> list[list[list[float]]]:
    return geom["coordinates"] if geom["type"] == "Polygon" else [r for poly in geom["coordinates"] for r in poly]


_ALL = [p for f in _GEO["features"] for ring in _rings(f["geometry"]) for p in ring]
_W0, _N0 = min(p[0] for p in _ALL), max(p[1] for p in _ALL)


def xy(lat: float, lon: float) -> tuple[float, float]:
    return ((lon - _W0) * math.cos(math.radians(_LAT0)) * _SCALE, (_N0 - lat) * _SCALE)


def _path(geom: dict) -> str:
    out = []
    for ring in _rings(geom):
        pts, last = [], None
        for lon, lat in ring:
            p = tuple(round(v, 1) for v in xy(lat, lon))
            if p != last:
                pts.append(f"{p[0]:g},{p[1]:g}")
                last = p
        out.append("M" + "L".join(pts) + "Z")
    return "".join(out)


_PATHS = {f["properties"]["id"]: _path(f["geometry"]) for f in _GEO["features"]}
GERMAN_NAMES = {f["properties"]["id"]: f["properties"]["name"] for f in _GEO["features"]}  # "DE-BY": "Bayern"
_WIDTH = round(max(xy(p[1], p[0])[0] for p in _ALL), 1)
_HEIGHT = round(max(xy(p[1], p[0])[1] for p in _ALL), 1)


def svg(highlight: str | None, state_url: dict[str, str], names: dict[str, str], dots: list[dict]) -> str:
    """highlight: "DE-BY" or None; state_url: code -> link (states without a page aren't links);
    dots: [{"n": "Munich", "lat": .., "lon": .., "k": 1097, "u": "city-munich.html", "h": True}]."""
    e = html.escape
    shapes = []
    for code, d in _PATHS.items():
        cls = "st on" if code == highlight else "st"
        shape = f'<path class="{cls}" d="{d}"><title>{e(names.get(code, code))}</title></path>'
        shapes.append(f'<a href="{e(state_url[code])}">{shape}</a>' if code in state_url and code != highlight else shape)
    circles = []
    for c in sorted(dots, key=lambda c: -c["k"]):  # big first, so small cities stay clickable on top
        x, y = xy(c["lat"], c["lon"])
        r = min(2.5 + math.sqrt(c["k"]) * 0.45, 14)
        circles.append(f'<a href="{e(c["u"])}"><circle class="dot{" here" if c.get("h") else ""}" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}">'
                       f'<title>{e(c["n"])}: {c["k"]:,} job{"s" if c["k"] != 1 else ""}</title></circle></a>')
    return (f'<svg class="de-map" viewBox="-4 -4 {_WIDTH + 8} {_HEIGHT + 8}" role="img" '
            f'aria-label="Map of Germany{" with " + e(names[highlight]) + " highlighted" if highlight in names else ""}">'
            f'{"".join(shapes)}{"".join(circles)}</svg>')
