"""Stream lists for streaming channels that change while the player runs.

A streaming channel normally plays the fixed `streams` list in its station config. With `streams_file` set, the
list is read from a JSON file each time the player needs it, so a helper (tools/live_stream_picker.py) can keep it
pointed at whatever is live right now:

    {"streams": [{"url": "...", "duration": 900, "title": "...", "priority": false}, ...]}

An entry with `"priority": true` is something the viewer should be on right away (for example a rocket launch).
"""

import json
import logging
import os
import time

_l = logging.getLogger("LiveStreams")

# project root: fs42/live_streams.py -> one level up
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# streams that would not play are tried last for a while, so a stream that is listed but broken cannot trap the channel
FAILED_RETRY_AFTER = 600
_failed = {}


def mark_failed(url):
    _failed[url] = time.time()


def _recently_failed(url):
    t = _failed.get(url)
    return t is not None and time.time() - t < FAILED_RETRY_AFTER


def _healthy_first(streams):
    return [s for s in streams if not _recently_failed(s["url"])] + [s for s in streams if _recently_failed(s["url"])]


def _read_file(path):
    full = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
    try:
        with open(full, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        _l.warning(f"Could not read streams file {path}: {e}")
        return None
    streams = data.get("streams") if isinstance(data, dict) else data
    if not isinstance(streams, list):
        return None
    good = [s for s in streams if isinstance(s, dict) and s.get("url") and s.get("duration")]
    return good or None


def load_streams(station_conf):
    """Streams for a streaming channel: from `streams_file` if it is set and readable, else the config's `streams`."""
    path = station_conf.get("streams_file")
    if path:
        streams = _read_file(path)
        if streams:
            return _healthy_first(streams)
    return list(station_conf.get("streams", []))


def first_live_stream(station_conf):
    """The first stream in `streams_file` that has not recently failed, or None. For web channels that give way to a live feed."""
    path = station_conf.get("streams_file")
    if not path:
        return None
    streams = _read_file(path)
    if not streams:
        return None
    for s in _healthy_first(streams):
        if not _recently_failed(s["url"]):
            return s
    return None


def priority_stream_changed(station_conf, current_url):
    """True if the streams file now starts with a priority stream that is not the one playing."""
    path = station_conf.get("streams_file")
    if not path:
        return False
    streams = _read_file(path)
    if not streams:
        return False
    first = _healthy_first(streams)[0]
    if _recently_failed(first["url"]):
        return False
    return bool(first.get("priority")) and first.get("url") != current_url
