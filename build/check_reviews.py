"""List guides whose fact check is due (front matter: reviewed + review_months).

    python build/check_reviews.py            # prints a Markdown checklist, nothing if all are current
    python build/check_reviews.py --soon 30  # also lists guides due within 30 days

Used by .github/workflows/guide-reviews.yml to open a reminder issue every month.
After re-checking a guide against its sources, set `reviewed:` to today's date.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_site import CONTENT, add_months, read_post  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--soon", type=int, default=0, help="also list guides due within N days")
    args = ap.parse_args()
    today = dt.date.today()
    rows = []
    for path in sorted((CONTENT / "blog").glob("*.md")):
        meta, _ = read_post(path)
        if meta.get("draft") == "true" or not meta.get("reviewed"):
            continue
        due = add_months(meta["reviewed"], int(meta.get("review_months") or 12))
        if due <= today + dt.timedelta(days=args.soon):
            rows.append(f"- [ ] **{meta['title']}** (`content/blog/{path.name}`) — last checked {meta['reviewed']}, "
                        f"due {due.isoformat()}")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
