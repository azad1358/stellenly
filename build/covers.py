"""Cover illustrations for guides and sections, generated as SVG.

No stock photos: every cover is drawn from the section's colour and icon, with
a pattern that varies per article, so the blog looks consistent, costs nothing
and loads nothing from third parties.
"""
from __future__ import annotations

import random

# 24×24 line icons (stroke), drawn large on the cover.
ICONS = {
    "passport": '<rect x="5" y="2.5" width="14" height="19" rx="2"/><circle cx="12" cy="10" r="3.2"/>'
                '<path d="M8.8 10h6.4M12 6.8c1.2 1.6 1.2 4.8 0 6.4M12 6.8c-1.2 1.6-1.2 4.8 0 6.4M8.5 17h7"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2.2"/><path d="M9 7V5.2A1.2 1.2 0 0 1 10.2 4h3.6A1.2 1.2 0 0 1 15 5.2V7'
                 'M3 12.5h18M10.5 12.5v1.6h3v-1.6"/>',
    "euro": '<circle cx="12" cy="12" r="9"/><path d="M15.6 8.4a4.6 4.6 0 1 0 0 7.2M7 10.8h6.2M7 13.4h6.2"/>',
    "home": '<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.5V20h13V9.5"/><path d="M10 20v-5.5h4V20"/>',
    "chart": '<path d="M3.5 20.5h17"/><rect x="5" y="12" width="3" height="6.5" rx=".8"/>'
             '<rect x="10.5" y="7" width="3" height="11.5" rx=".8"/><rect x="16" y="10" width="3" height="8.5" rx=".8"/>'
             '<path d="M5.5 8.5 11 4.5l5.5 3 3-2"/>',
    "book": '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20"/>'
            '<path d="M8 7.5h8M8 11h6"/>',
    "bank": '<path d="M3 9.5 12 4l9 5.5"/><path d="M4.5 10v8M9 10v8M15 10v8M19.5 10v8M3 20.5h18"/>',
    "shield": '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6z"/><path d="m8.8 12 2.2 2.2 4.4-4.4"/>',
    "chat": '<path d="M4 5.5h11a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H9l-4 3.5v-3.5H4a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2z"/>'
            '<path d="M17 9.5h3a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-1v3l-3-3h-3.5"/>',
}


def cover_svg(hue: int, icon: str, seed: str, width: int = 1200, height: int = 560) -> str:
    """A soft gradient with floating shapes and a large line icon. Same seed → same picture."""
    rnd = random.Random(seed)
    h2 = (hue + 38) % 360
    shapes = []
    for _ in range(14):
        x, y = rnd.uniform(0, width), rnd.uniform(0, height)
        r = rnd.uniform(18, 120)
        op = rnd.uniform(0.05, 0.16)
        if rnd.random() < 0.55:
            shapes.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" fill="#fff" fill-opacity="{op:.2f}"/>')
        else:
            shapes.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{r * 1.6:.0f}" height="{r * 1.6:.0f}" rx="{r * .35:.0f}" '
                          f'fill="#fff" fill-opacity="{op:.2f}" transform="rotate({rnd.uniform(-25, 25):.0f} {x:.0f} {y:.0f})"/>')
    dots = "".join(f'<circle cx="{40 + c * 34}" cy="{40 + r * 34}" r="2.2" fill="#fff" fill-opacity=".22"/>'
                   for r in range(4) for c in range(6))
    size = min(height * 0.62, width * 0.28)
    ix = width * (0.8 if width / height > 3 else 0.66) - size / 2 + rnd.uniform(-30, 30)
    iy = (height - size) / 2 + rnd.uniform(-height * 0.04, height * 0.04)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid slice" role="img" aria-hidden="true">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="hsl({hue} 72% 56%)"/><stop offset="1" stop-color="hsl({h2} 70% 44%)"/>
    </linearGradient>
    <radialGradient id="glow" cx="72%" cy="45%" r="55%">
      <stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#g)"/>
  <rect width="{width}" height="{height}" fill="url(#glow)"/>
  {"".join(shapes)}
  <g transform="translate({width * 0.05:.0f} {height * 0.08:.0f})">{dots}</g>
  <g transform="translate({ix:.0f} {iy:.0f}) scale({size / 24:.2f})" fill="none" stroke="#fff" stroke-width="1.35"
     stroke-linecap="round" stroke-linejoin="round" opacity=".95">{ICONS.get(icon, ICONS["book"])}</g>
</svg>'''
