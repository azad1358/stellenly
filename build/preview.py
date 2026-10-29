"""Local preview: rebuild all generated pages from live data, then serve the site.

    python build/preview.py            # http://localhost:8000
    python build/preview.py --port 8080 --no-build

Uses the public Supabase URL and anon key from web/js/config.js (read-only), so no
secrets are needed. The rebuilt pages (web/blog, web/companies, ...) are the
same files the daily GitHub build commits; don't commit them from a branch.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import os
import re
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-build", action="store_true", help="serve without rebuilding the pages")
    args = ap.parse_args()

    if not args.no_build:
        config = (WEB / "js" / "config.js").read_text(encoding="utf-8")
        for env, key in (("SUPABASE_URL", "SUPABASE_URL"), ("SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY")):
            m = re.search(rf'{key}:\s*"([^"]*)"', config)
            if not os.environ.get(env) and m and m.group(1):
                os.environ[env] = m.group(1)
        if not os.environ.get("SUPABASE_URL"):
            sys.exit("web/js/config.js has no SUPABASE_URL — set it, or run with --no-build.")
        print("Building pages from live data …")
        sys.path.insert(0, str(ROOT / "build"))
        import build_site  # noqa: E402  (imported here so the env vars above are set first)
        sys.argv = [sys.argv[0]]
        build_site.main()

    url = f"http://localhost:{args.port}/"
    print(f"\nPreview running at {url}  (Ctrl+C to stop)")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    try:
        webbrowser.open(url)
    except Exception:
        pass
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
