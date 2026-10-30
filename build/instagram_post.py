"""Post an image to the Stellenly Instagram account (Instagram Graph API, content publishing).

Instagram downloads the image itself, so it must be a JPEG at a public URL (e.g. https://www.stellenly.com/social/x.jpg,
deployed from web/social/). Needs IG_USER_ID (the Instagram business account id) and IG_ACCESS_TOKEN (a system-user
token with instagram_basic + instagram_content_publish), both GitHub secrets.

    python build/instagram_post.py check                          # is the token valid, which account is it?
    python build/instagram_post.py post <image_url> <caption>     # publish one image
"""
from __future__ import annotations

import os
import sys
import time

import requests

API = "https://graph.facebook.com"


def call(method: str, path: str, **params) -> dict:
    r = requests.request(method, f"{API}/{path}", timeout=60,
                         params={**params, "access_token": os.environ["IG_ACCESS_TOKEN"]})
    data = r.json()
    if not r.ok or "error" in data:
        err = data.get("error", {})
        raise SystemExit(f"Instagram API: {r.status_code} {err.get('type', '')} {err.get('message', r.text[:300])}")
    return data


def check() -> None:
    me = call("GET", os.environ["IG_USER_ID"], fields="username,name,followers_count,media_count")
    print(f"Instagram: token works for @{me.get('username')} ({me.get('name')}): "
          f"{me.get('followers_count', 0)} followers, {me.get('media_count', 0)} posts")


def post(image_url: str, caption: str) -> str:
    """Upload (a "container"), wait until Instagram has processed it, publish. Returns the post's link."""
    ig = os.environ["IG_USER_ID"]
    container = call("POST", f"{ig}/media", image_url=image_url, caption=caption)["id"]
    for _ in range(30):
        status = call("GET", container, fields="status_code").get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise SystemExit(f"Instagram could not process the image ({status}): {image_url}")
        time.sleep(4)
    media = call("POST", f"{ig}/media_publish", creation_id=container)["id"]
    link = call("GET", media, fields="permalink").get("permalink", "")
    print(f"Instagram: posted {link}")
    return link


if __name__ == "__main__":
    if not os.environ.get("IG_USER_ID") or not os.environ.get("IG_ACCESS_TOKEN"):
        sys.exit("IG_USER_ID / IG_ACCESS_TOKEN not set")
    if sys.argv[1:2] == ["check"]:
        check()
    elif sys.argv[1:2] == ["post"] and len(sys.argv) == 4:
        post(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
