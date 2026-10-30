"""Messages to the private Discord channel #social-drafts (DISCORD_SOCIAL_WEBHOOK_URL) for the "Social posts" workflow.

    python build/social_discord.py draft <post.json> <base_url> <approve_url>   # preview: images + caption + approve link
    python build/social_discord.py posted <posted.txt>                          # the links of the published post
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests


def send(content: str, embeds: list[dict] | None = None) -> None:
    hook = os.environ.get("DISCORD_SOCIAL_WEBHOOK_URL")
    if not hook:
        print("Discord: DISCORD_SOCIAL_WEBHOOK_URL not set, skipping")
        return
    requests.post(hook, timeout=30, json={"username": "Stellenly social", "content": content[:2000],
                                          "embeds": embeds or [], "allowed_mentions": {"parse": []}}).raise_for_status()


if __name__ == "__main__":
    if sys.argv[1:2] == ["draft"] and len(sys.argv) == 5:
        p = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        base = sys.argv[3].rstrip("/")
        send(f"📝 **New {p['kind']} post for {p['date']}**: {len(p['slides'])} image(s)\n"
             f"✅ Approve or ❌ reject here: <{sys.argv[4]}>\n\n>>> {p['caption']}",
             [{"image": {"url": f"{base}/{s}"}, "url": sys.argv[4]} for s in p["slides"][:10]])  # same url: one gallery
    elif sys.argv[1:2] == ["posted"] and len(sys.argv) == 3:
        links = Path(sys.argv[2]).read_text(encoding="utf-8").split() if Path(sys.argv[2]).exists() else []
        send("✅ Posted:\n" + "\n".join(f"<{u}>" for u in links) if links else "ℹ️ Nothing was posted (draft too old).")
    else:
        sys.exit(__doc__)
