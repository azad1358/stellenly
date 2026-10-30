"""Post to the Stellenly Instagram account and Facebook Page (Meta Graph API).

Instagram and Facebook download the images themselves, so they must be JPEGs at public URLs. Needs IG_USER_ID (the
Instagram business account id), IG_ACCESS_TOKEN (a system-user token with instagram_basic, instagram_content_publish
and pages_manage_posts) and, for Facebook, FB_PAGE_ID: all GitHub secrets.

    python build/instagram_post.py check                          # is the token valid, which account is it?
    python build/instagram_post.py post <image_url> <caption>     # publish one image on Instagram
    python build/instagram_post.py publish <post.json> <base_url> # a post from social_posts.py: Instagram + Facebook
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://graph.facebook.com"


def call(method: str, path: str, token: str | None = None, **params) -> dict:
    r = requests.request(method, f"{API}/{path}", timeout=60,
                         params={**params, "access_token": token or os.environ["IG_ACCESS_TOKEN"]})
    data = r.json()
    if not r.ok or "error" in data:
        err = data.get("error", {})
        raise SystemExit(f"Meta API: {r.status_code} {err.get('type', '')} {err.get('message', r.text[:300])}")
    return data


def check() -> None:
    me = call("GET", os.environ["IG_USER_ID"], fields="username,name,followers_count,media_count")
    print(f"Instagram: token works for @{me.get('username')} ({me.get('name')}): "
          f"{me.get('followers_count', 0)} followers, {me.get('media_count', 0)} posts")


def _ready(container: str) -> None:
    """Instagram processes each uploaded image first; publishing before FINISHED fails."""
    for _ in range(30):
        status = call("GET", container, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise SystemExit(f"Instagram could not process an image ({status})")
        time.sleep(4)
    raise SystemExit("Instagram took too long to process the images")


def post(image_urls: list[str], caption: str) -> str:
    """One image, or a carousel of 2-10. Returns the post's link."""
    ig = os.environ["IG_USER_ID"]
    if len(image_urls) == 1:
        container = call("POST", f"{ig}/media", image_url=image_urls[0], caption=caption)["id"]
    else:
        children = []
        for url in image_urls[:10]:
            child = call("POST", f"{ig}/media", image_url=url, is_carousel_item="true")["id"]
            _ready(child)
            children.append(child)
        container = call("POST", f"{ig}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    _ready(container)
    media = call("POST", f"{ig}/media_publish", creation_id=container)["id"]
    link = call("GET", media, fields="permalink").get("permalink", "")
    print(f"Instagram: posted {link}")
    return link


def post_facebook(image_urls: list[str], caption: str) -> str:
    """The same images and text as one post on the Facebook Page. Returns the post's link."""
    page = os.environ["FB_PAGE_ID"]
    token = call("GET", page, fields="access_token")["access_token"]  # the Page's own token, from the system user
    photos = [call("POST", f"{page}/photos", token, url=url, published="false")["id"] for url in image_urls[:10]]
    post_id = call("POST", f"{page}/feed", token, message=caption,
                   attached_media=json.dumps([{"media_fbid": p} for p in photos]))["id"]
    link = call("GET", post_id, token, fields="permalink_url").get("permalink_url", "")
    print(f"Facebook: posted {link}")
    return link


def publish(post_file: str, base_url: str) -> list[str]:
    """A post made by social_posts.py (post.json + slide JPEGs at base_url). Skips drafts older than a day, so a
    late approval never posts last week's numbers."""
    p = json.loads(Path(post_file).read_text(encoding="utf-8"))
    if dt.date.fromisoformat(p["date"]) < dt.date.today() - dt.timedelta(days=1):
        print(f"Skipped: the draft is from {p['date']}, more than a day ago")
        return []
    urls = [base_url.rstrip("/") + "/" + s for s in p["slides"]]
    links = [post(urls, p["caption"])]
    if os.environ.get("FB_PAGE_ID"):
        try:
            links.append(post_facebook(urls, p["caption"]))
        except SystemExit as err:  # Instagram is out already: report Facebook, don't fail the run
            print(f"Facebook failed: {err}")
    return links


if __name__ == "__main__":
    if not os.environ.get("IG_USER_ID") or not os.environ.get("IG_ACCESS_TOKEN"):
        sys.exit("IG_USER_ID / IG_ACCESS_TOKEN not set")
    cmd = sys.argv[1:2]
    if cmd == ["check"]:
        check()
    elif cmd == ["post"] and len(sys.argv) == 4:
        post([sys.argv[2]], sys.argv[3])
    elif cmd == ["publish"] and len(sys.argv) == 4:
        links = publish(sys.argv[2], sys.argv[3])
        Path("posted.txt").write_text("\n".join(links), encoding="utf-8")
    else:
        sys.exit(__doc__)
