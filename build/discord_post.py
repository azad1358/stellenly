"""Post site updates to the #changelog channel of the Stellenly Discord.

Runs after each deploy (deploy-website.yml), so the changes are live when the post appears.
Lists the code commits since the last announced one: short commit id (linked), the title and
the "- " lines of the description. Merge commits and the bot's data commits are skipped, so
the every-6-hours job updates stay quiet. Remembers the last announced commit in a small state
file kept in the GitHub Actions cache; the first run only remembers it. Skips quietly without
DISCORD_WEBHOOK_URL.

    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... python build/discord_post.py
    python build/discord_post.py --dry-run --since <commit>    # print what would be posted
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import requests

STATE = Path(os.environ.get("DISCORD_STATE", Path(__file__).parent / ".discord_state.json"))
SITE_URL = os.environ.get("SITE_URL") or "https://www.stellenly.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
BOTS = {"site-bot", "github-actions[bot]"}
MAX_COMMITS, LIMIT = 15, 1900  # Discord allows 2,000 characters per message


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def commits_since(sha: str) -> list[dict]:
    out = git("log", f"{sha}..HEAD", "--no-merges", "--reverse", "--format=%H%x1f%an%x1f%B%x1e")
    items = []
    for raw in filter(str.strip, out.split("\x1e")):
        full, author, body = raw.strip().split("\x1f")
        if author in BOTS:
            continue
        lines = body.strip().splitlines()
        items.append({"sha": full, "title": lines[0].strip(),
                      "points": [ln.strip()[2:] for ln in lines[1:] if ln.strip().startswith("- ")]})
    return items


def messages(items: list[dict]) -> list[str]:
    head = f"🚀 **Stellenly updated** — {SITE_URL}\n"
    blocks = []
    for c in items[-MAX_COMMITS:]:
        ref = f"[`{c['sha'][:7]}`](<https://github.com/{REPO}/commit/{c['sha']}>)" if REPO else f"`{c['sha'][:7]}`"
        blocks.append("\n".join([f"**{c['title']}** {ref}"] + [f"• {p}" for p in c["points"]]))
    out, cur = [], head
    for b in blocks:
        if len(cur) + len(b) + 2 > LIMIT and cur != head:
            out.append(cur)
            cur = ""
        cur += "\n" + b[:LIMIT] + "\n"
    return out + [cur]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the messages instead of sending them")
    ap.add_argument("--since", help="announce the commits after this one (instead of the remembered one)")
    args = ap.parse_args()
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not hook and not args.dry_run:
        print("Discord: DISCORD_WEBHOOK_URL not set, skipping")
        return

    head = git("rev-parse", "HEAD").strip()
    last = args.since or (json.loads(STATE.read_text(encoding="utf-8")).get("sha") if STATE.exists() else None)
    if not last or subprocess.run(["git", "merge-base", "--is-ancestor", last, head]).returncode != 0:
        print(f"Discord: nothing remembered yet (or history was rewritten), starting from {head[:7]}")
    else:
        items = commits_since(last)
        if not items:
            print("Discord: no code changes since the last post")
        for text in messages(items) if items else []:
            if args.dry_run:
                print(text, "\n----")
                continue
            r = requests.post(hook, json={"content": text, "allowed_mentions": {"parse": []}, "flags": 4},  # 4 = no link previews
                              timeout=30)
            r.raise_for_status()
        if items and not args.dry_run:
            print(f"Discord: posted {len(items)} change(s)")
    if not args.dry_run:
        STATE.write_text(json.dumps({"sha": head}), encoding="utf-8")


if __name__ == "__main__":
    main()
