"""A small local relay that lets mpv play YouTube live streams without talking to YouTube itself.

On some systems (Ubuntu's FFmpeg uses GnuTLS) mpv fails on YouTube's video servers with "tls: Error decoding the received
TLS packet" and plays nothing. This relay fetches everything with Python's own HTTPS code and hands mpv plain local HTTP:

    http://127.0.0.1:PORT/yt/<video id>    a playlist that joins the video and audio of that live stream
    http://127.0.0.1:PORT/live/<channel>   the same for whatever a YouTube channel is streaming right now, so a channel that
                                           restarts its stream under a new address keeps working. <channel> is @handle,
                                           channel/UC... or user/name
    http://127.0.0.1:PORT/p/<token>        anything else the playlists point at (rewritten playlists, video pieces)

It is started by tools/live_stream_picker.py (--relay-port), or on its own with `python3 -m fs42.hls_relay --port 8099`,
and is meant for localhost only.
"""

import base64
import logging
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlparse
import re

import requests

log = logging.getLogger("hls_relay")

DEFAULT_FORMAT = "bestvideo[height<=720][vcodec^=avc1]+bestaudio"
RESOLVE_TTL = 240  # seconds a resolved stream address is reused
# the only channel addresses the relay will resolve, so it cannot be pointed at arbitrary sites
CHANNEL_RE = re.compile(r"^(@[\w.\-]+|channel/UC[\w\-]{20,}|user/[\w.\-]+)$")


def _b64(url):
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def _unb64(token):
    return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()


def rewrite_playlist(text, base_url):
    """Point every address in an HLS playlist back at the relay."""
    def fix_attr(match):
        return 'URI="/p/' + _b64(urljoin(base_url, match.group(1))) + '"'

    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
        elif stripped.startswith("#"):
            out.append(re.sub(r'URI="([^"]*)"', fix_attr, line))
        else:
            out.append("/p/" + _b64(urljoin(base_url, stripped)))
    return "\n".join(out) + "\n"


def master_playlist(video_url, audio_url):
    """One playlist that joins a video-only and an audio-only stream."""
    return "\n".join([
        "#EXTM3U",
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="audio",DEFAULT=YES,AUTOSELECT=YES,URI="/p/' + _b64(audio_url) + '"',
        '#EXT-X-STREAM-INF:BANDWIDTH=3500000,AUDIO="aud"',
        "/p/" + _b64(video_url),
        "",
    ])


class Resolver:
    """Asks yt-dlp for the playlist addresses of a live stream, and remembers them briefly."""

    def __init__(self, ytdlp, fmt):
        self.ytdlp = ytdlp
        self.fmt = fmt
        self._cache = {}
        self._lock = threading.Lock()

    def resolve(self, video_id):
        return self.resolve_url("https://www.youtube.com/watch?v=" + video_id)

    def resolve_url(self, url):
        with self._lock:
            hit = self._cache.get(url)
            if hit and time.time() - hit[0] < RESOLVE_TTL:
                return hit[1]
            cmd = self.ytdlp + ["--no-warnings", "--no-playlist", "-g", "-f", self.fmt, url]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            urls = [l.strip() for l in out.stdout.splitlines() if l.strip().startswith("http")]
            if not urls:
                raise RuntimeError(out.stderr.strip()[-200:] or "yt-dlp returned no addresses")
            self._cache[url] = (time.time(), urls)
            return urls


def make_handler(resolver, session):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, code, body=b"", ctype="text/plain", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            try:
                if self.path.startswith("/yt/"):
                    return self._youtube(resolver.resolve(self.path[4:].split("?")[0]))
                if self.path.startswith("/live/"):
                    channel = self.path[6:].split("?")[0]
                    if not CHANNEL_RE.match(channel):
                        return self._send(400, b"Not a channel address.")
                    return self._youtube(resolver.resolve_url(f"https://www.youtube.com/{channel}/live"))
                if self.path.startswith("/p/"):
                    return self._proxy(_unb64(self.path[3:].split("?")[0]))
                self._send(404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                log.warning(f"{self.path[:60]}: {e}")
                try:
                    self._send(502, str(e).encode())
                except Exception:
                    pass

        do_HEAD = do_GET

        def _youtube(self, urls):
            if len(urls) >= 2:
                body = master_playlist(urls[0], urls[1])
            else:  # a single combined stream
                body = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=3500000\n/p/" + _b64(urls[0]) + "\n"
            self._send(200, body.encode(), "application/vnd.apple.mpegurl")

        def _proxy(self, url):
            if urlparse(url).scheme not in ("http", "https"):
                return self._send(400)
            headers = {"User-Agent": "Mozilla/5.0"}
            if self.headers.get("Range"):
                headers["Range"] = self.headers["Range"]
            r = session.get(url, headers=headers, stream=True, timeout=20)
            ctype = r.headers.get("Content-Type", "application/octet-stream")
            # video piece addresses can contain ".m3u8" in the middle of the path, so only the end counts
            is_playlist = urlparse(url).path.lower().endswith(".m3u8") or "mpegurl" in ctype.lower()
            if is_playlist and r.status_code == 200:
                body = rewrite_playlist(r.text, r.url).encode()
                return self._send(200, body, "application/vnd.apple.mpegurl")
            self.send_response(r.status_code)
            self.send_header("Content-Type", ctype)
            if r.headers.get("Content-Length"):
                self.send_header("Content-Length", r.headers["Content-Length"])
                if r.headers.get("Content-Range"):
                    self.send_header("Content-Range", r.headers["Content-Range"])
                self.end_headers()
                if self.command != "HEAD":
                    for chunk in r.iter_content(65536):
                        self.wfile.write(chunk)
            else:  # no length: send the data in chunks
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                if self.command != "HEAD":
                    for chunk in r.iter_content(65536):
                        self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")

    return Handler


def start(port, ytdlp, fmt=DEFAULT_FORMAT):
    """Run the relay in a background thread. Returns the server."""
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Resolver(ytdlp, fmt), requests.Session()))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="hls-relay").start()
    log.info(f"HLS relay listening on 127.0.0.1:{port}")
    return server


def relay_url(port, watch_url):
    """The relay address for a YouTube watch address, or None if it is not one."""
    m = re.search(r"[?&]v=([\w-]{6,})", watch_url)
    return f"http://127.0.0.1:{port}/yt/{m.group(1)}" if m else None


if __name__ == "__main__":
    import argparse
    import shutil
    import sys

    ap = argparse.ArgumentParser(description="Run the local YouTube relay on its own.")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--ytdlp", help="how to run yt-dlp if it is not on the PATH (for example /home/me/.local/bin/yt-dlp)")
    ap.add_argument("--format", default=DEFAULT_FORMAT)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    found = shutil.which("yt-dlp")
    cmd = a.ytdlp.split() if a.ytdlp else ([found] if found else [sys.executable, "-m", "yt_dlp"])
    start(a.port, cmd, a.format)
    threading.Event().wait()
