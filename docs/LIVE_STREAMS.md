# Live stream channels that follow what is on

A `streaming` channel plays live feeds (YouTube live streams, HLS `.m3u8` feeds) one after another. The stock channel
rotates a fixed list on a timer, so a feed that is not live leaves dead air, and nothing can jump to a feed that
has just gone live. This fork adds three things:

- **A stream list that can change.** `streams_file` points at a JSON file the player re-reads each time it needs the list.
- **Dead streams are skipped.** A stream that is down for 30 seconds (`stream_down_skip_seconds`) is dropped and the player
  moves to the next one, and a stream that would not play goes to the back of the list for ten minutes.
- **Priority streams.** A stream marked `"priority": true` that sits first in the list takes over from whatever is playing,
  within about 30 seconds. Use it for things that matter now, such as a rocket launch.

`tools/live_stream_picker.py` keeps that file up to date by checking which candidates are live.

## Station config

```json
{
  "station_conf": {
    "network_name": "Live",
    "network_type": "streaming",
    "channel_number": 16,
    "content_dir": "catalog/live",
    "streams_file": "runtime/live_streams.json",
    "streams": [
      {"url": "https://www.youtube.com/@SomeChannel/live", "duration": 900, "title": "Fallback"}
    ]
  }
}
```

`streams` is used only if the file is missing or unreadable. Create the `catalog/live` folder (every channel's
`content_dir` must exist).

## The candidates file

A list of what the picker may choose from (see the top of `tools/live_stream_picker.py` for every option):

```json
{
  "candidates": [
    {"name": "Launch coverage", "url": "https://www.youtube.com/@SomeChannel/live", "priority": 100, "duration": 10800},
    {"name": "Station view",    "url": "https://www.youtube.com/@AnotherChannel/live", "duration": 900}
  ],
  "fallback": [
    {"name": "Always on", "url": "https://www.youtube.com/@AnotherChannel/live", "duration": 900}
  ]
}
```

- A channel's `/live` address always means "what that channel is streaming now", so nothing goes stale.
- Entries with a `priority` go first, highest first, and stay up for their `duration`. The rest rotate as filler, starting
  from a different one each cycle.
- Nothing live at all? The `fallback` list is used.

Run it once to see what it finds, then keep it running:

```bash
python3 tools/live_stream_picker.py --candidates ~/candidates.json --out runtime/live_streams.json
python3 tools/live_stream_picker.py --candidates ~/candidates.json --out runtime/live_streams.json --loop 120
```

To keep it running in the background, make a user service (`~/.config/systemd/user/fs42-streams.service`), then
`systemctl --user enable --now fs42-streams`:

```ini
[Unit]
Description=FieldStation42 live stream picker
After=network-online.target

[Service]
WorkingDirectory=/home/YOU/fieldstation42-plex
ExecStart=/home/YOU/fieldstation42-plex/env/bin/python3 tools/live_stream_picker.py --candidates /home/YOU/candidates.json --out runtime/live_streams.json --loop 120 --relay-port 8099 --ytdlp /home/YOU/.local/bin/yt-dlp
Restart=on-failure

[Install]
WantedBy=default.target
```

## Playing YouTube on a Raspberry Pi

### If mpv fails with "tls: Error decoding the received TLS packet"

Ubuntu's FFmpeg uses GnuTLS, which mishandles how YouTube's video servers close connections: mpv finds the stream, then plays
nothing and exits with "Errors when loading file" (curl and Python fetch the same pieces without trouble). The picker can run a
small relay that does the fetching with Python instead and gives mpv a plain local address. Add `--relay-port 8099` to the
picker's command (as in the service above) and the playlist will contain addresses like `http://127.0.0.1:8099/yt/<id>`. The
relay needs `yt-dlp` (below) but not the mpv settings further down.

### A channel that is just one always-on YouTube stream

No picker is needed for a feed that is simply always on. Any running relay also answers
`http://127.0.0.1:PORT/live/<channel>` with whatever that YouTube channel is streaming right now (`<channel>` is `@handle`,
`channel/UC...` or `user/name`), so it keeps working when the channel restarts its stream under a new address. Use it as the
stream address in an ordinary streaming channel:

```json
{
  "station_conf": {
    "network_name": "Always On",
    "network_type": "streaming",
    "channel_number": 997,
    "content_dir": "catalog/alwayson",
    "stream_down_message": "STAND BY",
    "streams": [{"url": "http://127.0.0.1:8099/live/@SomeChannel", "duration": 21600, "title": "Always On"}]
  }
}
```

The relay is whichever one a picker started with `--relay-port`, or one run on its own:
`python3 -m fs42.hls_relay --port 8099 --ytdlp /home/YOU/.local/bin/yt-dlp`. If the stream is offline the channel shows the
stand-by message and tries again.

### yt-dlp

mpv plays YouTube addresses through `yt-dlp`, which has to be installed and kept up to date, because YouTube changes
often and old versions stop working. The standalone download is the simplest:

```bash
mkdir -p ~/.local/bin
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux_aarch64 -o ~/.local/bin/yt-dlp
chmod +x ~/.local/bin/yt-dlp
~/.local/bin/yt-dlp -U      # run now and then to update it
```

Then tell mpv where it is (the player service does not see `~/.local/bin`) and to pick a stream a Pi 4 can decode
(H.264, 720p or lower). YouTube live feeds come as separate video and audio streams, so the format joins the two. Add these lines to `~/.config/mpv/mpv.conf`:

```
script-opts=ytdl_hook-ytdl_path=/home/YOU/.local/bin/yt-dlp
ytdl-format=bestvideo[height<=720][vcodec^=avc1]+bestaudio/bestvideo[height<=720]+bestaudio/best
```

Test a feed before trusting it: `mpv --ao=null --vo=null --length=15 "https://www.youtube.com/@SomeChannel/live"` should
print the video and audio it found (for example `h264 1280x720`) and run for 15 seconds. (The player keeps the sound device
open while it runs, so a test that plays sound only works with the player stopped.)
If YouTube feeds do not start, update yt-dlp first; its documentation lists any extra requirements for YouTube.
Direct `.m3u8` feeds do not need yt-dlp at all.
