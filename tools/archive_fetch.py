#!/usr/bin/env python3
"""Download the original video files of an Internet Archive item, several at a time.

Usage (needs the `requests` package, which the FieldStation42 environment already has):
    python3 tools/archive_fetch.py --item SOME-ITEM-ID --dest ~/media/clips
    python3 tools/archive_fetch.py --item SOME-ITEM-ID --dest ~/media/clips --jobs 6

What it does:
  * reads the item's file list from archive.org and picks the original video files (not the derived copies or thumbnails)
  * downloads --jobs files at the same time (default 6; the Archive is shared, so it is capped at 8)
  * resumes interrupted downloads and skips files that are already complete, so it is safe to run again
  * checks every file against the checksum the Archive lists, and re-downloads a file that does not match
It exits with a non-zero status if any file could not be fetched, after trying all the others.
"""

import argparse
import concurrent.futures
import hashlib
import os
import sys
import threading
import time
from urllib.parse import quote

import requests

VIDEO_EXT = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm")
MAX_JOBS = 8
CHUNK = 1 << 20
UA = "FieldStation42-archive-fetch/1.0"


def list_files(item, session):
    """The original video files of an item as [{"name", "size", "md5"}], sorted by name."""
    r = session.get(f"https://archive.org/metadata/{quote(item)}", timeout=60)
    r.raise_for_status()
    data = r.json()
    if not data.get("files"):
        raise SystemExit(f"Item '{item}' was not found or has no files.")
    out = []
    for f in data["files"]:
        name = f.get("name", "")
        if f.get("source") != "original" or not name.lower().endswith(VIDEO_EXT) or "/" in name:
            continue
        out.append({"name": name, "size": int(f.get("size") or 0), "md5": f.get("md5")})
    return sorted(out, key=lambda f: f["name"])


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def fetch_one(item, f, dest, session, progress, verify_existing=False, retries=4):
    """Download one file. Returns "skipped", "downloaded" or raises after the last retry."""
    final = os.path.join(dest, f["name"])
    part = final + ".part"
    if os.path.exists(final) and (f["size"] == 0 or os.path.getsize(final) == f["size"]):
        if not verify_existing or not f["md5"] or md5_of(final) == f["md5"]:
            return "skipped"
        os.remove(final)

    url = f"https://archive.org/download/{quote(item)}/{quote(f['name'])}"
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if f["size"] and have > f["size"]:
                os.remove(part)
                have = 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            with session.get(url, headers=headers, stream=True, timeout=60) as r:
                if r.status_code == 416:      # the part file is already the whole file
                    have = f["size"]
                elif r.status_code in (200, 206):
                    if r.status_code == 200 and have:   # the server ignored the range: start again
                        have = 0
                    with open(part, "ab" if have else "wb") as out:
                        for block in r.iter_content(CHUNK):
                            out.write(block)
                            progress(len(block))
                else:
                    r.raise_for_status()
            if f["size"] and os.path.getsize(part) != f["size"]:
                raise IOError(f"size {os.path.getsize(part)} instead of {f['size']}")
            if f["md5"] and md5_of(part) != f["md5"]:
                os.remove(part)
                raise IOError("checksum does not match")
            os.replace(part, final)
            return "downloaded"
        except (requests.RequestException, IOError, OSError) as e:
            last_error = e
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"{f['name']}: {last_error}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--item", required=True, help="the item id (the last part of its archive.org/details/ address)")
    ap.add_argument("--dest", required=True, help="folder to put the files in")
    ap.add_argument("--jobs", type=int, default=6, help="files to download at once (default 6, at most 8)")
    ap.add_argument("--verify-existing", action="store_true", help="also checksum files that are already complete (slow)")
    ap.add_argument("--list", action="store_true", help="only list what would be downloaded")
    args = ap.parse_args(argv)

    jobs = max(1, min(args.jobs, MAX_JOBS))
    dest = os.path.expanduser(args.dest)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    files = list_files(args.item, session)
    total_bytes = sum(f["size"] for f in files)
    print(f"{len(files)} files, {total_bytes / 1e9:.1f} GB in item '{args.item}'")
    if args.list:
        for f in files:
            print(f"  {f['size'] / 1e6:8.1f} MB  {f['name']}")
        return 0
    os.makedirs(dest, exist_ok=True)

    lock = threading.Lock()
    state = {"bytes": 0, "done": 0, "skipped": 0, "failed": []}
    started = time.time()

    def progress(n):
        with lock:
            state["bytes"] += n

    def work(f):
        try:
            result = fetch_one(args.item, f, dest, session, progress, args.verify_existing)
            with lock:
                state["done"] += 1
                state["skipped"] += result == "skipped"
        except Exception as e:                         # keep going: report at the end
            with lock:
                state["done"] += 1
                state["failed"].append(str(e))

    stop = threading.Event()

    def reporter():
        while not stop.wait(10):
            with lock:
                mb = state["bytes"] / 1e6
                done, skipped = state["done"], state["skipped"]
            rate = mb / max(time.time() - started, 1)
            print(f"  {done}/{len(files)} files ({skipped} already had), {mb:,.0f} MB fetched, {rate:.1f} MB/s", flush=True)

    threading.Thread(target=reporter, daemon=True).start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(work, files))
    stop.set()

    print(f"Finished: {len(files) - len(state['failed'])} of {len(files)} files in place, {state['skipped']} were already there.")
    for msg in state["failed"]:
        print(f"  FAILED {msg}", file=sys.stderr)
    return 1 if state["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
