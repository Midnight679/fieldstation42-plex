#!/usr/bin/env python3
"""Summarize the video codecs and resolutions in your Plex libraries (nothing is played or downloaded).

Usage (from the repo root):
    set -a; source ~/.config/fs42/plex.env; set +a
    python3 tools/plex_media_report.py                 # every movie / TV library
    python3 tools/plex_media_report.py "Movies"        # only the named libraries

A Raspberry Pi 4 can hardware-decode H.264 up to 1080p. HEVC (H.265), 4K and very high bitrates are
usually too heavy for it and show up as "heavy" below. The output has no credentials in it.
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fs42.plex_source import PlexClient  # noqa: E402

HEAVY_BITRATE_KBPS = 25000


def is_heavy(media):
    codec = (media.get("videoCodec") or "").lower()
    height = media.get("height") or 0
    bitrate = media.get("bitrate") or 0
    return codec not in ("h264", "avc") or height > 1080 or bitrate > HEAVY_BITRATE_KBPS


def main():
    url, token = os.environ.get("PLEX_URL"), os.environ.get("PLEX_TOKEN")
    if not url or not token:
        sys.exit("Set PLEX_URL and PLEX_TOKEN first (e.g. source ~/.config/fs42/plex.env)")
    wanted = {a.lower() for a in sys.argv[1:]}
    c = PlexClient(url, token)

    for section in c._get("/library/sections").get("Directory", []):
        kind = section.get("type")
        if kind not in ("movie", "show") or (wanted and section["title"].lower() not in wanted):
            continue
        params = {"type": 4} if kind == "show" else {}  # type 4 = episodes, so each item carries its Media info
        items = c._get(f"/library/sections/{section['key']}/all", params).get("Metadata", [])
        counts, heavy = Counter(), []
        for item in items:
            media = (item.get("Media") or [None])[0]
            if not media:
                continue
            counts[((media.get("videoCodec") or "?").lower(), f"{media.get('height') or '?'}p")] += 1
            if is_heavy(media):
                heavy.append((item.get("grandparentTitle") or item.get("title", "?"), item.get("title", "?"), media))

        total = sum(counts.values())
        print(f"\n## {section['title']}: {total} items, {len(heavy)} heavy ({(100 * len(heavy) // total) if total else 0}%)")
        for (codec, res), n in counts.most_common():
            print(f"   {codec:8} {res:>6}  x{n}")
        if heavy:
            print("   Heaviest (not Pi 4 friendly):")
            for show, title, m in sorted(heavy, key=lambda h: -(h[2].get("bitrate") or 0))[:15]:
                label = show if show == title else f"{show} - {title}"
                print(f"     - {label[:60]}: {m.get('videoCodec')} {m.get('width')}x{m.get('height')} {m.get('bitrate')} kbps")


if __name__ == "__main__":
    main()
