"""Plex content source for FieldStation42.

Catalog entries for Plex items are stored with a pseudo path of the form
``plex://<ratingKey>/<Display Name>.<ext>`` so the Plex token never lands in the
catalog database. The path is resolved to a real playback URL at playback time: a direct-play URL when the file is
something a small player can decode, or a live Plex transcode (e.g. 4K down to 1080p H.264) when not.
"""

import atexit
import logging
import os
import re
import threading
import uuid
from urllib.parse import quote, urlencode

import requests

from fs42.catalog_entry import CatalogEntry

PLEX_SCHEME = "plex://"
_PATH_RE = re.compile(r"^plex://(\d+)/")
_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def is_plex_path(path) -> bool:
    return isinstance(path, str) and path.startswith(PLEX_SCHEME)


class PlexClient:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, url, token, timeout=15, transcode="off", max_height=1080, max_bitrate=10000, playable_only=False,
                 max_direct_bitrate=25000):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        # transcode: "off" never transcodes, "auto" only when no playable version exists, "always" every time
        self.transcode = (transcode or "off").lower()
        self.max_height = int(max_height)
        self.max_bitrate = int(max_bitrate)  # kbps: the transcode target
        self.max_direct_bitrate = int(max_direct_bitrate)  # kbps: highest bitrate worth playing directly
        self._transcode_session = None
        # playable_only: leave out items that have no version this player can decode directly
        self.playable_only = bool(playable_only)
        self.last_skipped = 0
        self._l = logging.getLogger("PLEX")
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json", "X-Plex-Token": token})
        self._sections = None
        self._url_cache = {}

    @classmethod
    def get(cls):
        """Shared client built from main_config.json ("plex" block) or PLEX_URL / PLEX_TOKEN env vars."""
        with cls._lock:
            if cls._instance is None:
                from fs42.station_manager import StationManager

                conf = StationManager().server_conf.get("plex", {}) or {}
                url = os.environ.get("PLEX_URL") or conf.get("url")
                token = os.environ.get("PLEX_TOKEN") or conf.get("token")
                if not url or not token:
                    raise RuntimeError(
                        "Plex is not configured. Set PLEX_URL and PLEX_TOKEN, or add a \"plex\" block with "
                        "\"url\" and \"token\" to confs/main_config.json"
                    )
                cls._instance = cls(
                    url,
                    token,
                    conf.get("timeout", 15),
                    transcode=os.environ.get("PLEX_TRANSCODE") or conf.get("transcode", "off"),
                    max_height=os.environ.get("PLEX_MAX_HEIGHT") or conf.get("max_height", 1080),
                    max_bitrate=os.environ.get("PLEX_MAX_BITRATE") or conf.get("max_bitrate", 10000),
                    max_direct_bitrate=os.environ.get("PLEX_MAX_DIRECT_BITRATE") or conf.get("max_direct_bitrate", 25000),
                    playable_only=(os.environ.get("PLEX_PLAYABLE_ONLY", "").lower() in ("1", "true", "yes", "on"))
                    or bool(conf.get("playable_only", False)),
                )
                atexit.register(cls._instance.stop_transcode)
            return cls._instance

    @classmethod
    def from_env(cls):
        """A client configured only from PLEX_* environment variables (for the command line tools)."""
        url, token = os.environ.get("PLEX_URL"), os.environ.get("PLEX_TOKEN")
        if not url or not token:
            raise RuntimeError("Set PLEX_URL and PLEX_TOKEN first (e.g. source ~/.config/fs42/plex.env)")
        return cls(
            url,
            token,
            transcode=os.environ.get("PLEX_TRANSCODE", "off"),
            max_height=os.environ.get("PLEX_MAX_HEIGHT", 1080),
            max_bitrate=os.environ.get("PLEX_MAX_BITRATE", 10000),
            max_direct_bitrate=os.environ.get("PLEX_MAX_DIRECT_BITRATE", 25000),
            playable_only=os.environ.get("PLEX_PLAYABLE_ONLY", "").lower() in ("1", "true", "yes", "on"),
        )

    # ---- low level -------------------------------------------------------

    def _get(self, path, params=None):
        r = self._session.get(self.url + path, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("MediaContainer", {})

    def _section_id(self, library):
        if self._sections is None:
            self._sections = {d["title"].lower(): d["key"] for d in self._get("/library/sections").get("Directory", [])}
        key = self._sections.get(library.lower())
        if key is None:
            raise ValueError(f"Plex library '{library}' not found. Available: {sorted(self._sections)}")
        return key

    # ---- catalog side ----------------------------------------------------

    @staticmethod
    def _as_list(value):
        return value if isinstance(value, list) else [value]

    @staticmethod
    def _matches(item, spec):
        """Client-side filters over a movie/show metadata dict. All given filters must match."""
        def lowered(values):
            return {str(v).lower() for v in PlexClient._as_list(values)}

        title = item.get("title", "").lower()
        titles = set()
        if "show" in spec:
            titles |= lowered(spec["show"])
        if "titles" in spec:
            titles |= lowered(spec["titles"])
        if titles and title not in titles:
            return False
        if "exclude_titles" in spec and title in lowered(spec["exclude_titles"]):
            return False
        if "title_contains" in spec and not any(t in title for t in lowered(spec["title_contains"])):
            return False
        if "genre" in spec and not (lowered(spec["genre"]) & {g["tag"].lower() for g in item.get("Genre", [])}):
            return False
        if "label" in spec and not (lowered(spec["label"]) & {l["tag"].lower() for l in item.get("Label", [])}):
            return False
        year = item.get("year")
        if "year_min" in spec and (year is None or year < spec["year_min"]):
            return False
        if "year_max" in spec and (year is None or year > spec["year_max"]):
            return False
        if "ratings" in spec and str(item.get("contentRating", "")).lower() not in lowered(spec["ratings"]):
            return False
        return True

    def _items_for_spec(self, spec):
        """Return a flat list of playable Plex metadata dicts (movies / episodes) for a source spec.

        Selectors: show, titles, exclude_titles, title_contains, genre, label, year_min, year_max,
        ratings, collection. All given selectors must match (they narrow, not widen).
        """
        section = self._section_id(spec["library"])

        if "collection" in spec:
            colls = self._get(f"/library/sections/{section}/collections").get("Metadata", [])
            match = [c for c in colls if c["title"].lower() == spec["collection"].lower()]
            if not match:
                raise ValueError(f"Collection '{spec['collection']}' not found in '{spec['library']}'")
            top = self._get(f"/library/collections/{match[0]['ratingKey']}/children").get("Metadata", [])
        else:
            top = self._get(f"/library/sections/{section}/all").get("Metadata", [])

        selected = [i for i in top if self._matches(i, spec)]
        if not selected:
            self._l.warning(f"Plex spec {spec} matched nothing in '{spec['library']}'")
        return self._expand(selected)

    def _expand(self, items):
        out = []
        for item in items:
            kind = item.get("type")
            if kind == "show":
                out += self._get(f"/library/metadata/{item['ratingKey']}/allLeaves").get("Metadata", [])
            elif kind == "season":
                out += self._get(f"/library/metadata/{item['ratingKey']}/children").get("Metadata", [])
            elif kind in ("movie", "episode", "clip"):
                out.append(item)
        return out

    @staticmethod
    def _display_name(item, ext):
        if item.get("type") == "episode":
            name = f"{item.get('grandparentTitle', 'Unknown')} - S{item.get('parentIndex', 0):02d}E{item.get('index', 0):02d} - {item.get('title', '')}"
        else:
            year = f" ({item['year']})" if item.get("year") else ""
            name = f"{item.get('title', 'Unknown')}{year}"
        return _BAD_FILENAME_CHARS.sub("", name).strip() + "." + ext

    def build_entries(self, spec, tag, content_type="feature"):
        """Build CatalogEntry objects for every playable item matching spec."""
        entries = []
        playable_only = spec.get("playable_only", self.playable_only)
        skipped = 0
        for item in self._items_for_spec(spec):
            media = item.get("Media") or []
            duration_ms = item.get("duration") or (media[0].get("duration") if media else 0)
            if not media or not duration_ms:
                self._l.warning(f"Skipping '{item.get('title')}': no media or duration reported by Plex")
                continue
            if playable_only and not any(self._playable(m) for m in media):
                skipped += 1
                continue
            parts = media[0].get("Part") or []
            ext = (parts[0].get("container") if parts else None) or "mkv"
            path = f"{PLEX_SCHEME}{item['ratingKey']}/{self._display_name(item, ext)}"
            entries.append(CatalogEntry(path, duration_ms / 1000.0, tag, [], content_type=content_type))
        self.last_skipped = skipped
        extra = f" ({skipped} skipped: no version this player can decode)" if skipped else ""
        self._l.info(f"Plex spec {spec} -> {len(entries)} entries for tag '{tag}'{extra}")
        return entries

    # ---- playback side ---------------------------------------------------

    def _media_versions(self, rating_key):
        meta = self._get(f"/library/metadata/{rating_key}").get("Metadata", [])
        try:
            versions = [m for m in meta[0]["Media"] if m.get("Part")]
        except (IndexError, KeyError):
            versions = []
        if not versions:
            raise ValueError(f"Plex item {rating_key} has no playable media part")
        return versions

    def _playable(self, media):
        """True for versions a small player can decode directly: H.264 within the height and bitrate limits."""
        codec = (media.get("videoCodec") or "").lower()
        return (
            codec in ("h264", "avc")
            and (media.get("height") or 0) <= self.max_height
            and (media.get("bitrate") or 0) <= self.max_direct_bitrate
        )

    def _direct_url(self, media):
        return f"{self.url}{quote(media['Part'][0]['key'])}?download=0&X-Plex-Token={self.token}"

    def stop_transcode(self):
        """Best effort: tell Plex to end the previous transcode session so channel flipping does not pile them up."""
        session, self._transcode_session = self._transcode_session, None
        if session:
            try:
                self._session.get(f"{self.url}/video/:/transcode/universal/stop", params={"session": session}, timeout=5)
            except requests.RequestException:
                pass

    def _transcode_url(self, rating_key, offset):
        self.stop_transcode()
        self._transcode_session = uuid.uuid4().hex
        width = int(self.max_height * 16 / 9)
        query = urlencode({
            "path": f"/library/metadata/{rating_key}",
            "mediaIndex": 0,
            "partIndex": 0,
            "protocol": "hls",
            "fastSeek": 1,
            "directPlay": 0,
            "directStream": 1,
            "offset": int(offset),
            "maxVideoBitrate": self.max_bitrate,
            "videoResolution": f"{width}x{self.max_height}",
            "session": self._transcode_session,
            "X-Plex-Session-Identifier": self._transcode_session,
            "X-Plex-Client-Identifier": "fieldstation42",
            # Plex answers 400 to a bare request; it accepts one that looks like its own web player
            "X-Plex-Product": "Plex Web",
            "X-Plex-Platform": "Chrome",
            "X-Plex-Version": "4.0",
            "X-Plex-Device": "Linux",
            "X-Plex-Device-Name": "FieldStation42",
            "X-Plex-Model": "bundled",
            "hasMDE": 1,
            "location": "lan",
            "autoAdjustQuality": 0,
            "directStreamAudio": 1,
            "mediaBufferSize": 102400,
            "subtitleSize": 100,
            "audioBoost": 100,
            "Accept-Language": "en",
            "X-Plex-Token": self.token,
        })
        return f"{self.url}/video/:/transcode/universal/start.m3u8?{query}"

    def playback_target(self, path, offset=0):
        """Return (location, consumed_offset) for a plex:// path.

        consumed_offset is how many seconds of the requested offset the location already skips, because a
        live transcode starts at the requested point. The caller seeks only the remainder (zero for transcodes).
        """
        m = _PATH_RE.match(path)
        if not m:
            raise ValueError(f"Not a plex path: {path}")
        rating_key = m.group(1)
        versions = self._media_versions(rating_key)
        playable = sorted(
            (v for v in versions if self._playable(v)),
            key=lambda v: (-(v.get("height") or 0), v.get("bitrate") or 0),
        )

        if self.transcode != "always" and (playable or self.transcode == "off"):
            self.stop_transcode()
            chosen = playable[0] if playable else versions[0]
            self._l.info(
                f"Plex item {rating_key}: direct play {chosen.get('videoCodec')} {chosen.get('width')}x{chosen.get('height')}"
            )
            return self._direct_url(chosen), 0

        top = versions[0]
        self._l.info(
            f"Plex item {rating_key}: transcoding {top.get('videoCodec')} {top.get('width')}x{top.get('height')} "
            f"to <= {self.max_height}p at {self.max_bitrate} kbps, starting at {int(offset)}s"
        )
        return self._transcode_url(rating_key, offset), int(offset)

    def resolve(self, path):
        """Direct-play URL for a plex:// path (the best playable version, token included)."""
        m = _PATH_RE.match(path)
        if not m:
            raise ValueError(f"Not a plex path: {path}")
        versions = self._media_versions(m.group(1))
        playable = [v for v in versions if self._playable(v)]
        return self._direct_url(playable[0] if playable else versions[0])


def playback_headers(path):
    """HTTP headers the player must send for this path.

    A Plex transcode hands the player a playlist whose links carry no token, so the token has to travel as a
    header on every request. It is sent only for Plex items, never to any other server.
    """
    if is_plex_path(path):
        return [f"X-Plex-Token: {PlexClient.get().token}"]
    return []


def resolve_for_playback(path, offset=0):
    """Return (location, consumed_offset) for playback. Plex pseudo paths are resolved; anything else passes through."""
    if is_plex_path(path):
        return PlexClient.get().playback_target(path, offset)
    if PlexClient._instance is not None:
        PlexClient._instance.stop_transcode()
    return path, 0
