# Plex content source

Instead of scanning folders, a station can build its catalog from your Plex server and stream items directly to mpv.

## Server config (`confs/main_config.json`)

```json
{ "plex": { "url": "http://<plex-server-ip>:32400", "token": "YOUR_PLEX_TOKEN" } }
```

`PLEX_URL` / `PLEX_TOKEN` environment variables override the file (preferred, so the token stays out of config files).

If you run FieldStation42 as systemd services, put them in `~/.config/fs42/plex.env` instead; see [install/systemd/README.md](../install/systemd/README.md).

## Station config

Add a `plex_sources` map. Each key is a **tag** (the same tag you use in the weekly schedule slots, or a `commercial_dir` / `bump_dir` value); each value says what in Plex that tag means:

```json
"plex_sources": {
  "Seinfeld":    { "library": "TV Shows", "show": "Seinfeld" },
  "80sAction":   { "library": "Movies",   "collection": "80s Action" }
}
```

Selectors (all of the ones you give must match, so each one narrows the result; give just `library` for everything in it):

| Selector | Meaning |
|----------|---------|
| `show` | One show by exact title |
| `titles` / `exclude_titles` | A list of exact titles to include / leave out |
| `title_contains` | Text (or a list of text) the title must contain |
| `genre` | A genre (or list; any one matches), e.g. `["Action", "Adventure"]` |
| `label` | A Plex label (or list) |
| `collection` | A Plex collection |
| `year_min` / `year_max` | Release year range |
| `ratings` | Allowed content ratings, e.g. `["G", "PG"]` (items with no rating never match) |

Titles and genres are case-insensitive. Run `tools/plex_check_station.py` (below) to see what each tag matches. Tags that are not in `plex_sources` are scanned from `content_dir` as usual, so you can mix local and Plex content.

## How it works

- Durations come from Plex, so no `ffprobe` pass is needed.
- The catalog stores `plex://<ratingKey>/<name>.mkv` paths; the real direct-play URL (with token) is resolved at playback time.
- Rebuild the catalog after changing Plex content, as with local folders.
- Commercials and bumps stay local. Leave them out of `plex_sources` and they are scanned from folders under `content_dir` exactly as upstream does.

## Recommended layout: Plex shows, local commercials and bumps

```json
{"station_conf": {
  "network_name": "plexTV",
  "channel_number": 2,
  "schedule_increment": 30,
  "break_strategy": "end",
  "content_dir": "catalog/plexTV",
  "commercial_dir": "commercial",
  "bump_dir": "bump",
  "plex_sources": {
    "Seinfeld": { "library": "TV Shows", "show": "Seinfeld" }
  },
  "monday": { "8": { "tags": "Seinfeld", "title": "Seinfeld" } }
}}
```

Put commercial clips in `catalog/plexTV/commercial/` and bumps in `catalog/plexTV/bump/` on the box. `content_dir` is still required because those folders are relative to it, but it doesn't need a `Seinfeld` folder. (Keep the `clip_shows`, sign-off and off-air settings from the upstream examples as needed.)

Shows and movies rarely fill their time slot exactly (a 91-minute movie in a 2-hour slot leaves about 29 minutes), and the gap is filled from the `bump` folder (or the `commercial` folder when `commercial_free` is `false`). If those folders are empty or missing, the gap is filled with your `be_right_back_media` image and a one-time warning is logged. Add short video clips to the folders to fill gaps properly.

## Seeing what's in your Plex

To list your libraries, titles, genres and collections (no credentials in the output) so you can plan channels:

```bash
set -a; source ~/.config/fs42/plex.env; set +a
python3 tools/plex_inventory.py > plex_inventory.txt
```

## Checking a channel before you rebuild

`tools/plex_check_station.py` is a dry run: it reads station configs, asks Plex what each tag matches, and prints the item count and hours per tag. It also flags tags that are scheduled but have no `plex_sources` entry.

```bash
set -a; source ~/.config/fs42/plex.env; set +a
python3 tools/plex_check_station.py confs/mychannel.json
```

## Playing 4K and HEVC on a small device (Raspberry Pi 4)

A Pi 4 can hardware-decode H.264 up to 1080p, but not 4K or most HEVC (H.265). When a Plex item has
no version the player can handle, the fork can ask Plex to convert it on the fly to a 1080p H.264 stream,
starting at the point in the schedule that is currently on air. Plex does the heavy lifting on the server.

Set these as environment variables (for example in `~/.config/fs42/plex.env`), or as keys of the `plex`
block in `confs/main_config.json` (`transcode`, `max_height`, `max_bitrate`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `PLEX_TRANSCODE` | `off` | `off` never transcodes, `auto` only when no playable version exists, `always` every time |
| `PLEX_MAX_HEIGHT` | `1080` | Tallest picture the player can handle, and the transcode size |
| `PLEX_MAX_BITRATE` | `10000` | Transcode target in kbps |
| `PLEX_MAX_DIRECT_BITRATE` | `25000` | Highest bitrate in kbps still played directly (1080p H.264 is well within a Pi 4's hardware decoder) |
| `PLEX_PLAYABLE_ONLY` | off | `true` leaves out of the catalog any item with no version the player can decode directly (also a per-source `"playable_only"` setting) |

Whatever the mode, if an item has several versions (for example a 4K and a 1080p copy), the best
version within these limits is chosen for direct play. Transcodes take a few seconds to start, so also set
`"video_seek_timeout": 30` in `confs/main_config.json`. Plex needs enough CPU or GPU to transcode in real
time. The fork asks Plex to end the previous transcode when the next one starts, so changing channels does
not leave sessions running.

Live transcoding needs a server that can convert video in real time. A server with no hardware
transcoding (an older machine, or a NAS) usually cannot convert 4K HEVC fast enough, and Plex may refuse or
stall. In that case set `PLEX_TRANSCODE=off` and `PLEX_PLAYABLE_ONLY=true`: only items the player can decode
directly are scheduled, and heavy items join the channels automatically once a playable copy exists
(for example a 1080p H.264 file made with Plex's Optimized Versions, HandBrake or ffmpeg). Rebuild the
catalogs after adding copies. `tools/plex_transcode_test.py` checks whether your server accepts transcode
requests, and `tools/plex_check_station.py` shows how many items each tag keeps.

To see how much of your library needs this, run `tools/plex_media_report.py`. It prints the codec and
resolution mix of each library and lists the heaviest files, without playing anything.
