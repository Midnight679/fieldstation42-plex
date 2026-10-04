"""Reads public news feeds (RSS or Atom) for the headlines page.

A web page cannot read another site's feed directly (browsers block it), so the page asks this server, which fetches the
feed, boils it down to headlines, and remembers the answer for a few minutes. Only public web addresses are fetched: anything
that points at this machine or another device on the local network is refused.
"""

import html
import ipaddress
import logging
import re
import socket
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import requests
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/news", tags=["news"])
logger = logging.getLogger("news_api")

CACHE_SECONDS = 300
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
_cache = {}


def _is_public_host(host):
    """True only if every address the host resolves to is a public one."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return bool(infos)


def _fetch(url):
    """GET a public address, following a few redirects and checking each hop."""
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or not _is_public_host(parts.hostname):
            raise HTTPException(status_code=400, detail="Only public http(s) feed addresses are allowed.")
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (FieldStation42 news)"}, timeout=12,
                         stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"])
            continue
        r.raise_for_status()
        data = r.raw.read(MAX_BYTES + 1, decode_content=True)
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="Feed is too large.")
        return data
    raise HTTPException(status_code=502, detail="Too many redirects.")


def _text(node, *names):
    for name in names:
        found = node.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _clean(value, limit=400):
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = re.sub(r"\s+", " ", html.unescape(value)).strip()
    return value if len(value) <= limit else value[:limit].rsplit(" ", 1)[0] + "…"


def _when(value):
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value or ""


def parse_feed(data):
    """Turn RSS 2.0 or Atom into {"source": str, "items": [{"title", "summary", "published"}]}."""
    head = data[:4000].lower()
    if b"<!doctype" in head or b"<!entity" in data[:20000].lower():
        raise HTTPException(status_code=422, detail="Unsupported feed.")  # keeps entity-expansion tricks out
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise HTTPException(status_code=422, detail=f"Not a readable feed: {e}")

    items = []
    ns = "{http://www.w3.org/2005/Atom}"
    if root.tag.endswith("rss") or root.find("channel") is not None:
        channel = root.find("channel")
        source = _clean(_text(channel, "title"), 80)
        for it in channel.findall("item"):
            items.append({"title": _clean(_text(it, "title"), 200),
                          "summary": _clean(_text(it, "description"), 400),
                          "published": _when(_text(it, "pubDate"))})
    else:
        source = _clean(_text(root, ns + "title"), 80)
        for it in root.findall(ns + "entry"):
            items.append({"title": _clean(_text(it, ns + "title"), 200),
                          "summary": _clean(_text(it, ns + "summary", ns + "content"), 400),
                          "published": _text(it, ns + "updated", ns + "published")})
    return {"source": source, "items": [i for i in items if i["title"]]}


@router.get("/feed")
def get_feed(u: str, limit: int = 15):
    """Headlines from one feed address. Answers are kept for five minutes."""
    now = time.time()
    hit = _cache.get(u)
    if hit and now - hit[0] < CACHE_SECONDS:
        data = hit[1]
    else:
        try:
            data = parse_feed(_fetch(u))
        except HTTPException:
            raise
        except requests.RequestException as e:
            logger.warning(f"Feed fetch failed for {urlparse(u).hostname}: {e}")
            if hit:  # a stale answer beats none
                data = hit[1]
            else:
                raise HTTPException(status_code=502, detail="Could not fetch the feed.")
        else:
            _cache[u] = (now, data)
    return {"source": data["source"], "items": data["items"][: max(1, min(limit, 50))]}
