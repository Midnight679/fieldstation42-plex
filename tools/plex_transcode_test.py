#!/usr/bin/env python3
"""Check that your Plex server can start a live transcode, and find a request it accepts.

Usage (from the repo root):
    set -a; source ~/.config/fs42/plex.env; set +a
    python3 tools/plex_transcode_test.py "Movie Title" [offset_seconds] [library]
    python3 tools/plex_transcode_test.py --mpv "Movie Title" [offset_seconds]   # also play it in mpv, no screen needed

It asks Plex for a transcode using several variants of the request, one after another, and prints the
HTTP status each one gets (with your token blanked out). For the first variant Plex accepts, it also
times the first playlist and the first video segment. Nothing is played.
"""

import os
import sys
import time
import uuid
from urllib.parse import urlencode, urljoin

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fs42.plex_source import PlexClient  # noqa: E402

WEB_EXTRAS = {
    "hasMDE": 1,
    "location": "lan",
    "autoAdjustQuality": 0,
    "directStreamAudio": 1,
    "mediaBufferSize": 102400,
    "subtitleSize": 100,
    "audioBoost": 100,
    "Accept-Language": "en",
    "X-Plex-Version": "4.0",
    "X-Plex-Device": "Linux",
    "X-Plex-Device-Name": "FieldStation42",
    "X-Plex-Model": "bundled",
}


def header_experiments(c, rating_key, offset, token):
    """Send the player's own request with different Accept / token headers, one change at a time.

    Every case starts from a clean slate: any earlier session is stopped and we wait before and after,
    so one case cannot affect the next.
    """
    import requests

    print("Which headers does Plex need? (the player's own request, one change at a time)")
    cases = [
        ("Accept: application/json + token header", {"Accept": "application/json", "X-Plex-Token": token}),
        ("Accept: */*             + token header", {"Accept": "*/*", "X-Plex-Token": token}),
        ("no Accept header        + token header", {"Accept": None, "X-Plex-Token": token}),
        ("Accept: application/json, no token header", {"Accept": "application/json"}),
        ("Accept: */*,              no token header", {"Accept": "*/*"}),
        ("like ffmpeg: Accept */*, Range, Icy, Lavf agent + token header",
         {"Accept": "*/*", "Range": "bytes=0-", "Icy-MetaData": "1", "User-Agent": "Lavf/60.16.100", "X-Plex-Token": token}),
    ]
    both = {"Accept": "application/json", "X-Plex-Token": token}
    cases += [
        ("Accept: application/json + token header + Lavf agent", dict(both, **{"User-Agent": "Lavf/60.16.100"})),
        ("Accept: application/json + token header + Range", dict(both, **{"Range": "bytes=0-"})),
        ("(repeat of the first case)", dict(both)),
        ("(repeat of the first case, again)", dict(both)),
    ]
    results = []
    for name, headers in cases:
        c.stop_transcode()
        time.sleep(3)
        url = c._transcode_url(rating_key, offset)
        try:
            r = requests.get(url, headers=headers, timeout=60)
            status = r.status_code
        except Exception as e:  # noqa: BLE001
            status = f"ERR {str(e)[:40]}"
        results.append((name, status))
        print(f"  HTTP {status}  {name}")
        c.stop_transcode()
        time.sleep(3)
    print()
    return results


def run_mpv(c, token, rating_key, offset, redact):
    """Open the player's own request in mpv (no video or sound output) and print what mpv says, timestamped."""
    import subprocess
    url = c._transcode_url(rating_key, offset)
    cmd = ["mpv", "--no-config", "--vo=null", "--ao=null", "--length=8", "--msg-level=all=info,ffmpeg=v,demux=v",
           f"--http-header-fields=X-Plex-Token: {token}", url]
    print("\n--- mpv, as the player runs it (token header on, no config file) ---")
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    keep = ("http", "hls", "error", "fail", "open", "stream", "video", "audio", "playing", "exiting", "timeout", "401", "403", "404", "400", "av:")
    try:
        for line in proc.stdout:
            low = line.lower()
            if any(k in low for k in keep):
                print(f"  [{time.time() - t0:5.1f}s] {redact(line.rstrip())[:170]}")
            if time.time() - t0 > 60:
                proc.kill()
                print("  mpv still had not finished after 60s; stopped it")
                break
    finally:
        proc.wait()
    print(f"mpv exited with code {proc.returncode} after {time.time() - t0:.1f}s")
    c.stop_transcode()


def main():
    use_mpv = "--mpv" in sys.argv
    if use_mpv:
        sys.argv.remove("--mpv")
    run_variants = "--variants" in sys.argv
    if run_variants:
        sys.argv.remove("--variants")
    once = "--once" in sys.argv
    if once:
        sys.argv.remove("--once")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    title = sys.argv[1]
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    library = sys.argv[3] if len(sys.argv) > 3 else "Movies"
    base_url, token = os.environ.get("PLEX_URL"), os.environ.get("PLEX_TOKEN")
    if not base_url or not token:
        sys.exit("Set PLEX_URL and PLEX_TOKEN first (e.g. source ~/.config/fs42/plex.env)")

    height = int(os.environ.get("PLEX_MAX_HEIGHT", 1080))
    kbps = int(os.environ.get("PLEX_MAX_BITRATE", 8000))
    c = PlexClient(base_url, token, transcode="always", max_height=height, max_bitrate=kbps)

    def redact(text):
        return text.replace(token, "<token>")

    entries = c.build_entries({"library": library, "titles": [title]}, "t")
    if not entries:
        sys.exit(f"No item titled '{title}' in library '{library}'")
    rating_key = entries[0].path.split("/")[2]
    if once:
        import datetime
        url = c._transcode_url(rating_key, offset)
        r = c._session.get(url, timeout=60)
        stamp = datetime.datetime.now().strftime('%H:%M:%S')
        print(f"{stamp}  one transcode request: HTTP {r.status_code}")
        time.sleep(2)
        c.stop_transcode()
        print(f"{datetime.datetime.now().strftime('%H:%M:%S')}  stopped the session")
        return
    header_experiments(c, rating_key, offset, token)
    if not run_variants:
        if use_mpv:
            run_mpv(c, token, rating_key, offset, redact)
        return

    def params(**override):
        session = uuid.uuid4().hex
        p = {
            "path": f"/library/metadata/{rating_key}",
            "mediaIndex": 0,
            "partIndex": 0,
            "protocol": "hls",
            "fastSeek": 1,
            "directPlay": 0,
            "directStream": 1,
            "offset": offset,
            "maxVideoBitrate": kbps,
            "videoResolution": f"{int(height * 16 / 9)}x{height}",
            "session": session,
            "X-Plex-Session-Identifier": session,
            "X-Plex-Client-Identifier": "fieldstation42",
            "X-Plex-Product": "FieldStation42",
            "X-Plex-Platform": "Linux",
            "X-Plex-Token": token,
        }
        p.update(override)
        return {k: v for k, v in p.items() if v is not None}

    web = dict(WEB_EXTRAS, **{"X-Plex-Platform": "Chrome", "X-Plex-Product": "Plex Web"})
    ANY = {"Accept": "*/*"}
    # name, endpoint, params, headers
    variants = [
        ("current request", "start.m3u8", params(), {}),
        ("accept any content type", "start.m3u8", params(), ANY),
        ("minimal (no size or bitrate limits)", "start.m3u8", params(maxVideoBitrate=None, videoResolution=None), ANY),
        ("like Plex Web", "start.m3u8", params(**web), ANY),
        ("like Plex Web, no start offset", "start.m3u8", params(offset=None, **web), ANY),
        ("progressive mkv like Plex Web", "start.mkv", params(protocol="http", **web), ANY),
    ]

    # the exact request the player builds, tried first
    real = c._transcode_url(rating_key, offset)
    session_real = c._transcode_session
    variants.insert(0, ("THE PLAYER'S OWN REQUEST", None, None, real))

    # ask Plex WHY it would accept or refuse: the "decision" call explains itself
    print("Plex's own explanation (decision call):")
    try:
        dec_url = real.replace("/start.m3u8", "/decision")
        d = c._session.get(dec_url, headers={"Accept": "application/json"}, timeout=60)
        print(f"  HTTP {d.status_code}")
        if d.headers.get("Content-Type", "").startswith("application/json"):
            mc = d.json().get("MediaContainer", {})
            for key in sorted(mc):
                if key.lower().startswith(("general", "direct", "transcode", "mde")) and not isinstance(mc[key], (list, dict)):
                    print(f"  {key}: {mc[key]}")
        else:
            print("  ", redact(d.text[:160].replace("\n", " ")))
    except Exception as e:  # noqa: BLE001
        print("  could not ask:", redact(str(e))[:100])

    print(f"\nTrying {len(variants)} request variants (offset {offset}s) ...\n")
    winner = None
    for name, endpoint, p, headers in variants:
        if endpoint is None:  # the player's own, pre-built request
            url, headers, p = headers, {}, {"session": session_real}
        else:
            url = f"{base_url.rstrip('/')}/video/:/transcode/universal/{endpoint}?{urlencode(p)}"
        t0 = time.time()
        try:
            r = c._session.get(url, headers=headers, timeout=90)
            took = time.time() - t0
            note = redact(r.text[:90].replace("\n", " ")) if r.status_code != 200 else r.headers.get("Content-Type", "")
            print(f"  HTTP {r.status_code} in {took:4.1f}s  {name}  [{note}]")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR  {name}: {redact(str(e))[:100]}")
            continue
        if r.status_code == 200 and winner is None:
            winner = (name, url, headers, r, t0, p["session"])
        else:
            try:
                c._session.get(f"{base_url.rstrip('/')}/video/:/transcode/universal/stop", params={"session": p["session"]}, timeout=5)
            except Exception:  # noqa: BLE001
                pass

    if not winner:
        print("\nPlex rejected every variant. Check the Plex server's logs, and that the token is valid.")
        sys.exit(1)

    name, url, headers, r, t0, session = winner
    if use_mpv:
        run_mpv(c, token, rating_key, offset, redact)
    print(f"\nFirst accepted variant: {name}")
    print("--- first lines of the response ---")
    print("\n".join(redact(line) for line in r.text.splitlines()[:10]))

    current, text = url, r.text
    for _ in range(3):
        uris = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
        if not uris:
            break
        nxt = urljoin(current, uris[0])
        t1 = time.time()
        rr = c._session.get(nxt, headers=headers, timeout=120)
        playlist = "mpegurl" in (rr.headers.get("Content-Type") or "").lower() or rr.content[:7] == b"#EXTM3U"
        print(f"Next {'playlist' if playlist else 'segment'}: HTTP {rr.status_code}, {len(rr.content)} bytes in {time.time() - t1:.1f}s")
        if rr.status_code != 200:
            print("Plex said:", redact(rr.text[:300]))
            break
        if not playlist:
            print(f"Total time to first video segment: {time.time() - t0:.1f}s")
            break
        current, text = nxt, rr.text

    try:
        c._session.get(f"{base_url.rstrip('/')}/video/:/transcode/universal/stop", params={"session": session}, timeout=5)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
