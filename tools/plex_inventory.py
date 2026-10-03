#!/usr/bin/env python3
"""Print a token-free inventory of your Plex libraries (titles, years, genres, collections).

Usage (from the repo root):
    set -a; source ~/.config/fs42/plex.env; set +a
    python3 tools/plex_inventory.py > plex_inventory.txt

The output contains no credentials, so it is safe to share when planning channels.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fs42.plex_source import PlexClient  # noqa: E402


def main():
    url, token = os.environ.get("PLEX_URL"), os.environ.get("PLEX_TOKEN")
    if not url or not token:
        sys.exit("Set PLEX_URL and PLEX_TOKEN first (e.g. source ~/.config/fs42/plex.env)")
    c = PlexClient(url, token)

    for section in c._get("/library/sections").get("Directory", []):
        kind = section.get("type")
        if kind not in ("movie", "show"):
            continue
        print(f"\n## Library: {section['title']} ({kind})")
        colls = c._get(f"/library/sections/{section['key']}/collections").get("Metadata", [])
        if colls:
            print("Collections: " + ", ".join(sorted(x["title"] for x in colls)))
        items = c._get(f"/library/sections/{section['key']}/all").get("Metadata", [])
        for item in sorted(items, key=lambda i: i.get("title", "").lower()):
            genres = ", ".join(g["tag"] for g in item.get("Genre", []))
            year = f" ({item['year']})" if item.get("year") else ""
            extra = f" [{item['childCount']} seasons]" if kind == "show" and item.get("childCount") else ""
            mins = f" {round(item['duration'] / 60000)}min" if kind == "movie" and item.get("duration") else ""
            rating = f" {item['contentRating']}" if item.get("contentRating") else ""
            print(f"- {item.get('title', '?')}{year}{extra}{mins}{rating} | {genres}")


if __name__ == "__main__":
    main()
