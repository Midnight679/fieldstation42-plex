"""Plex content source for FieldStation42.

Catalog entries for Plex items are stored with a pseudo path of the form
``plex://<ratingKey>/<Display Name>.<ext>`` so the Plex token never lands in the
catalog database. The path is resolved to a real direct-play URL at playback time.
"""

import logging
import os
import re
import threading
from urllib.parse import quote

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

    def __init__(self, url, token, timeout=15):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
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
                cls._instance = cls(url, token, conf.get("timeout", 15))
            return cls._instance

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

    def _items_for_spec(self, spec):
        """Return a flat list of playable Plex metadata dicts (movies / episodes) for a source spec."""
        section = self._section_id(spec["library"])
        params = {}
        if "label" in spec:
            params["label"] = spec["label"]
        if "genre" in spec:
            params["genre"] = spec["genre"]

        if "collection" in spec:
            colls = self._get(f"/library/sections/{section}/collections").get("Metadata", [])
            match = [c for c in colls if c["title"].lower() == spec["collection"].lower()]
            if not match:
                raise ValueError(f"Collection '{spec['collection']}' not found in '{spec['library']}'")
            children = self._get(f"/library/collections/{match[0]['ratingKey']}/children").get("Metadata", [])
            return self._expand(children)

        if "show" in spec:
            shows = self._get(f"/library/sections/{section}/all", {"type": 2, "title": spec["show"]}).get("Metadata", [])
            shows = [s for s in shows if s["title"].lower() == spec["show"].lower()]
            if not shows:
                raise ValueError(f"Show '{spec['show']}' not found in '{spec['library']}'")
            return self._expand(shows)

        # whole library (optionally filtered by label/genre); episodes for show libraries, movies otherwise
        top = self._get(f"/library/sections/{section}/all", params).get("Metadata", [])
        return self._expand(top)

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
        for item in self._items_for_spec(spec):
            media = item.get("Media") or []
            duration_ms = item.get("duration") or (media[0].get("duration") if media else 0)
            if not media or not duration_ms:
                self._l.warning(f"Skipping '{item.get('title')}': no media or duration reported by Plex")
                continue
            parts = media[0].get("Part") or []
            ext = (parts[0].get("container") if parts else None) or "mkv"
            path = f"{PLEX_SCHEME}{item['ratingKey']}/{self._display_name(item, ext)}"
            entries.append(CatalogEntry(path, duration_ms / 1000.0, tag, [], content_type=content_type))
        self._l.info(f"Plex spec {spec} -> {len(entries)} entries for tag '{tag}'")
        return entries

    # ---- playback side ---------------------------------------------------

    def resolve(self, path):
        """Turn a plex:// pseudo path into a direct-play URL (token included)."""
        if path in self._url_cache:
            return self._url_cache[path]
        m = _PATH_RE.match(path)
        if not m:
            raise ValueError(f"Not a plex path: {path}")
        meta = self._get(f"/library/metadata/{m.group(1)}").get("Metadata", [])
        try:
            part_key = meta[0]["Media"][0]["Part"][0]["key"]
        except (IndexError, KeyError):
            raise ValueError(f"Plex item {m.group(1)} has no playable media part")
        url = f"{self.url}{quote(part_key)}?download=0&X-Plex-Token={self.token}"
        self._url_cache[path] = url
        return url


def resolve_for_playback(path):
    """Return a playable location for path: Plex pseudo paths are resolved, anything else passes through."""
    if is_plex_path(path):
        return PlexClient.get().resolve(path)
    return path
