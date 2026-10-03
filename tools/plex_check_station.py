#!/usr/bin/env python3
"""Dry-run a station config against your Plex server (no catalog is written).

Usage (from the repo root):
    set -a; source ~/.config/fs42/plex.env; set +a
    python3 tools/plex_check_station.py confs/mychannel.json [more.json ...]

For every tag in plex_sources it prints how many items (and hours of content) Plex returns, and it
flags tags used in the schedule that have no Plex source (those would be read from content_dir).
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fs42.plex_source import PlexClient  # noqa: E402


def schedule_tags(node):
    """Collect every tag name used anywhere in the schedule parts of a station config."""
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("tags", "start_clip", "end_clip", "fallback_tag"):
                found |= set(value if isinstance(value, list) else [value]) if isinstance(value, (str, list)) else set()
            elif isinstance(value, (dict, list)):
                found |= schedule_tags(value)
    elif isinstance(node, list):
        for value in node:
            found |= schedule_tags(value)
    return found


def check(client, path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "station_conf" not in data:
        print(f"\n(skipping {os.path.basename(path)}: not a channel config)")
        return 0
    conf = data["station_conf"]
    print(f"\n=== {conf.get('network_name', path)} (channel {conf.get('channel_number')}) ===")
    sources = conf.get("plex_sources", {})
    problems = 0

    for tag, spec in sources.items():
        try:
            entries = client.build_entries(spec, tag)
        except Exception as e:  # report and keep checking the rest
            print(f"  [FAIL] {tag}: {e}")
            problems += 1
            continue
        hours = sum(e.duration for e in entries) / 3600
        status = "ok  " if entries else "EMPTY"
        left_out = f", {client.last_skipped} left out (no playable version)" if client.last_skipped else ""
        problems += 0 if entries else 1
        print(f"  [{status}] {tag}: {len(entries)} items, {hours:.1f} h{left_out}")

    skip_keys = {"plex_sources", "clip_shows"}
    used = schedule_tags({k: v for k, v in conf.items() if k not in skip_keys})
    for tag in sorted(used - set(sources)):
        print(f"  [WARN ] '{tag}' is scheduled but has no plex_sources entry (will be read from content_dir)")
    return problems


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url, token = os.environ.get("PLEX_URL"), os.environ.get("PLEX_TOKEN")
    if not url or not token:
        sys.exit("Set PLEX_URL and PLEX_TOKEN first (e.g. source ~/.config/fs42/plex.env)")
    logging.disable(logging.CRITICAL)
    client = PlexClient.from_env()  # same PLEX_* settings the player uses, so the counts match the real catalog
    if client.playable_only:
        print("PLEX_PLAYABLE_ONLY is on: items with no version this player can decode are left out.")
    else:
        print("PLEX_PLAYABLE_ONLY is off: every item counts, including ones the player cannot decode.")
    total = sum(check(client, p) for p in sys.argv[1:])
    print("\nAll good." if total == 0 else f"\n{total} problem(s) found.")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
