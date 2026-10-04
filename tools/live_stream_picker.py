#!/usr/bin/env python3
"""Keep a streaming channel pointed at what is live right now.

Reads a list of candidate streams, checks which ones are actually live, and writes the playlist the player reads
(`streams_file` in the station config). Streams marked as priority (for example a rocket launch) go first and play for
a long time; the rest rotate as filler. Dead streams are left out, so the channel has as little dead air as possible.

Usage (from the repo root, with the environment active):
    python3 tools/live_stream_picker.py --candidates ~/space_candidates.json --out runtime/live_streams.json
    python3 tools/live_stream_picker.py --candidates ~/space_candidates.json --out runtime/live_streams.json --loop 120

Candidates file:
    {
      "candidates": [
        {"name": "Launch coverage", "url": "https://www.youtube.com/@SomeChannel/live", "priority": 100, "duration": 7200},
        {"name": "Station view",    "url": "https://www.youtube.com/@AnotherChannel/live", "duration": 900},
        {"name": "Direct feed",     "url": "https://example.com/feed/master.m3u8", "duration": 900}
      ],
      "fallback": [{"name": "Always on", "url": "https://example.com/other.m3u8", "duration": 900}]
    }

  priority   higher goes first; anything above 0 counts as a priority stream. Leave it out for filler.
  duration   seconds to stay on the stream before moving on (the player also moves on by itself if a stream dies).
  fallback   used only when nothing else is live.

YouTube addresses (youtube.com/@channel/live or a watch link) are checked with yt-dlp, which must be installed
(`yt-dlp` on the PATH, or give --ytdlp). A channel's /live address always means "whatever that channel is streaming
now", so the list never goes stale. Other addresses are checked with a plain request (.m3u8 playlists must have
video segments and no end marker).
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fs42 import hls_relay  # noqa: E402

log = logging.getLogger("live_stream_picker")

DEFAULT_PRIORITY_SECONDS = 7200
DEFAULT_FILLER_SECONDS = 900


def is_youtube(url):
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("youtube.com") or host == "youtu.be"


def check_youtube(url, ytdlp):
    """Return (state, watch_url, title). state is "live", "offline" or "error" (could not tell)."""
    cmd = ytdlp + ["--skip-download", "--no-warnings", "--no-playlist", "--print", "%(live_status)s\t%(id)s\t%(title)s", url]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning(f"yt-dlp failed for {url}: {e}")
        return "error", None, None
    lines = [l for l in out.stdout.splitlines() if "\t" in l]
    if lines:
        status, vid, title = (lines[-1].split("\t", 2) + ["", ""])[:3]
        if status == "is_live":
            return "live", f"https://www.youtube.com/watch?v={vid}", title
        return "offline", None, None
    err = out.stderr.lower()
    if "not currently live" in err or "does not have a live" in err or "this live event will begin" in err or "no live" in err:
        return "offline", None, None
    log.warning(f"Could not check {url}: {out.stderr.strip()[:200]}")
    return "error", None, None


def check_http(url):
    """Return "live", "offline" or "error" for a direct address (HLS playlists are looked into)."""
    try:
        r = requests.get(url, timeout=15)
    except requests.RequestException as e:
        log.warning(f"Could not reach {url}: {e}")
        return "error"
    if r.status_code in (404, 410):
        return "offline"
    if r.status_code != 200:
        return "error"
    if ".m3u8" not in url.lower() and "#EXTM3U" not in r.text[:20]:
        return "live"
    text = r.text
    if "#EXTM3U" not in text:
        return "offline"
    if "#EXT-X-STREAM-INF" in text:  # a master playlist: look at its first variant
        variants = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
        if not variants:
            return "offline"
        try:
            text = requests.get(requests.compat.urljoin(url, variants[0]), timeout=15).text
        except requests.RequestException:
            return "error"
    if "#EXTINF" not in text or "#EXT-X-ENDLIST" in text:
        return "offline"
    return "live"


def find_ytdlp(explicit):
    if explicit:
        return explicit.split()
    found = shutil.which("yt-dlp")
    return [found] if found else [sys.executable, "-m", "yt_dlp"]


def probe(candidate, ytdlp, relay_port=0):
    """Add a "state" (live/offline/error) and the playable "play_url" to a candidate."""
    url = candidate["url"]
    c = dict(candidate)
    if is_youtube(url):
        c["state"], c["play_url"], title = check_youtube(url, ytdlp)
        if relay_port and c["play_url"]:
            c["play_url"] = hls_relay.relay_url(relay_port, c["play_url"]) or c["play_url"]
        if title and not c.get("title"):
            # live titles end with the current date and time, which would change every check
            c["title"] = re.sub(r"\s+\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", "", title)
    else:
        c["state"] = check_http(url)
        c["play_url"] = url
    return c


def build_playlist(probed, fallback, now=None):
    """Order the live candidates: priority ones first (highest first), then filler rotated so each cycle starts differently."""
    now = time.time() if now is None else now
    live = [c for c in probed if c["state"] == "live"]
    priority = sorted((c for c in live if c.get("priority", 0) > 0), key=lambda c: -c["priority"])
    filler = [c for c in live if not c.get("priority", 0) > 0]

    entries = []
    for c in priority:
        entries.append({"url": c["play_url"], "title": c.get("title") or c.get("name", ""),
                        "duration": int(c.get("duration", DEFAULT_PRIORITY_SECONDS)), "priority": True})
    if filler:
        cycle = sum(int(c.get("duration", DEFAULT_FILLER_SECONDS)) for c in filler)
        shift = int(now // max(cycle, 1)) % len(filler)
        for c in filler[shift:] + filler[:shift]:
            entries.append({"url": c["play_url"], "title": c.get("title") or c.get("name", ""),
                            "duration": int(c.get("duration", DEFAULT_FILLER_SECONDS)), "priority": False})
    if not entries:
        for c in fallback:
            entries.append({"url": c["url"], "title": c.get("title") or c.get("name", ""),
                            "duration": int(c.get("duration", DEFAULT_FILLER_SECONDS)), "priority": False})
    return entries


def write_atomic(path, payload):
    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def run_once(args, ytdlp):
    with open(os.path.expanduser(args.candidates), encoding="utf-8") as f:
        conf = json.load(f)
    probed = [probe(c, ytdlp, args.relay_port) for c in conf.get("candidates", [])]
    for c in probed:
        log.info(f"{c['state']:8} {c.get('name', c['url'])}")
    if probed and all(c["state"] == "error" for c in probed):
        log.warning("Every check failed (no network?). Leaving the playlist as it is.")
        return
    fallback = []
    for fb in conf.get("fallback", []):
        c = probe(fb, ytdlp, args.relay_port)
        fallback.append(dict(fb, url=c["play_url"] if c["state"] == "live" and c["play_url"] else fb["url"]))
    entries = build_playlist(probed, fallback)
    write_atomic(args.out, {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "streams": entries})
    log.info("Playlist: " + " | ".join(f"{'*' if e['priority'] else ' '}{e['title'][:40]}" for e in entries))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", required=True, help="JSON file listing the streams to choose from")
    ap.add_argument("--out", required=True, help="playlist file the station config names as streams_file")
    ap.add_argument("--loop", type=int, default=0, metavar="SECONDS", help="keep running, checking again every N seconds")
    ap.add_argument("--relay-port", type=int, default=0, metavar="PORT",
                    help="run a local relay on this port and play YouTube feeds through it (needed where mpv cannot "
                         "talk to YouTube directly, see docs/LIVE_STREAMS.md)")
    ap.add_argument("--ytdlp", help="how to run yt-dlp, if it is not on the PATH (for example /home/me/.local/bin/yt-dlp)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    ytdlp = find_ytdlp(args.ytdlp)
    if args.relay_port:
        hls_relay.start(args.relay_port, ytdlp)
    while True:
        try:
            run_once(args, ytdlp)
        except Exception as e:  # keep the loop alive through a bad file or a network hiccup
            log.error(f"Check failed: {e}")
            if not args.loop:
                raise
        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
