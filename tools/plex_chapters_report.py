#!/usr/bin/env python3
"""See how much chapter and marker data your Plex files carry (nothing is played or changed).

Usage (from the repo root):
    set -a; source ~/.config/fs42/plex.env; set +a
    python3 tools/plex_chapters_report.py                  # a sample from every movie / TV library
    python3 tools/plex_chapters_report.py "TV Shows" 60    # a named library, 60 items

Chapters can be used as the points where a show is cut for ad breaks. Markers (intro, credits, and for recorded
TV, commercial) are listed too. The output contains no credentials.
"""

import os
import random
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fs42.plex_source import PlexClient  # noqa: E402


def main():
    wanted = sys.argv[1].lower() if len(sys.argv) > 1 else None
    sample_size = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    c = PlexClient.from_env()
    random.seed(42)

    for section in c._get("/library/sections").get("Directory", []):
        kind = section.get("type")
        if kind not in ("movie", "show") or (wanted and section["title"].lower() != wanted):
            continue
        params = {"type": 4} if kind == "show" else {}
        items = c._get(f"/library/sections/{section['key']}/all", params).get("Metadata", [])
        sample = random.sample(items, min(sample_size, len(items)))

        with_chapters, counts, spacing, generic, marker_types, total_len = 0, [], [], 0, Counter(), 0
        for it in sample:
            meta = c._get(f"/library/metadata/{it['ratingKey']}", {"includeChapters": 1, "includeMarkers": 1}).get("Metadata", [{}])[0]
            chapters = meta.get("Chapter") or []
            markers = meta.get("Marker") or []
            for m in markers:
                marker_types[m.get("type", "?")] += 1
            if chapters:
                with_chapters += 1
                counts.append(len(chapters))
                dur = (meta.get("duration") or it.get("duration") or 0) / 1000
                if dur and len(chapters) > 1:
                    spacing.append(dur / len(chapters) / 60)
                if all((ch.get("tag") or "").lower().startswith("chapter ") or not ch.get("tag") for ch in chapters):
                    generic += 1

        n = len(sample)
        print(f"\n## {section['title']} ({kind}): sampled {n} of {len(items)} items")
        print(f"   with chapters: {with_chapters} ({100 * with_chapters // max(n, 1)}%)")
        if counts:
            print(f"   chapters per item: median {statistics.median(counts):.0f}, min {min(counts)}, max {max(counts)}")
        if spacing:
            print(f"   average length of a chapter: about {statistics.median(spacing):.1f} minutes")
            print(f"   items whose chapters are only generic ('Chapter 1', 'Chapter 2', ...): {generic}")
        print(f"   markers found: {dict(marker_types) if marker_types else 'none'}")


if __name__ == "__main__":
    main()
